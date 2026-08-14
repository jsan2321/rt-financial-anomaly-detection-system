"""
Unit tests for ML Anomaly Scorer (Isolation Forest).
Tests fail-closed behavior on missing/corrupt models, feature vector extraction, and score normalization.
"""

from datetime import datetime, timezone
from decimal import Decimal
import json
import pickle
import uuid
import numpy as np
import pytest
from sklearn.ensemble import IsolationForest

from services.processor.domain.ml_model import (
    MLAnomalyScorer,
    MLMetadata,
    MLModelLoadError,
)
from services.processor.domain.schemas import TransactionContext, VelocityContext


@pytest.fixture
def trained_isolation_forest():
    """Generates a small trained IsolationForest model for testing."""
    rng = np.random.RandomState(42)
    # 5 features: [amount, hour, country_tier, category_risk, rolling_count]
    X_train = rng.normal(loc=100.0, scale=20.0, size=(100, 5))
    model = IsolationForest(n_estimators=10, random_state=42)
    model.fit(X_train)
    return model


@pytest.fixture
def sample_metadata() -> MLMetadata:
    return MLMetadata(
        model_version="1.0.0-test",
        min_score=-0.25,
        max_score=0.25,
    )


@pytest.fixture
def sample_transaction() -> TransactionContext:
    return TransactionContext(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        amount=Decimal("1250.50"),
        currency="USD",
        country="US",
        merchant_category="electronics",
        created_at=datetime(2026, 8, 13, 14, 30, tzinfo=timezone.utc),
    )


class TestMLMetadata:
    def test_serialization_roundtrip(self, sample_metadata):
        data = sample_metadata.to_dict()
        assert data["model_version"] == "1.0.0-test"
        assert data["min_score"] == -0.25
        assert data["max_score"] == 0.25

        restored = MLMetadata.from_dict(data)
        assert restored.model_version == sample_metadata.model_version
        assert restored.min_score == sample_metadata.min_score
        assert restored.max_score == sample_metadata.max_score


class TestMLAnomalyScorer:
    def test_feature_extraction(self, trained_isolation_forest, sample_metadata, sample_transaction):
        scorer = MLAnomalyScorer(model=trained_isolation_forest, metadata=sample_metadata)
        velocity = VelocityContext(
            user_id=sample_transaction.user_id,
            window_minutes=10,
            transaction_count=4,
            total_amount=Decimal("3000.00"),
        )
        features = scorer.extract_features(sample_transaction, velocity)
        assert features.shape == (1, 5)
        # amount, hour_of_day, country_risk, category_risk, rolling_count
        assert features[0, 0] == 1250.50
        assert features[0, 1] == 14.0
        assert features[0, 2] == 0.1  # US tier
        assert features[0, 3] == 0.5  # electronics category
        assert features[0, 4] == 4.0  # rolling count

    def test_score_produces_valid_decimal_in_range(
        self,
        trained_isolation_forest,
        sample_metadata,
        sample_transaction,
    ):
        scorer = MLAnomalyScorer(model=trained_isolation_forest, metadata=sample_metadata)
        score = scorer.score(sample_transaction)
        assert isinstance(score, Decimal)
        assert Decimal("0.0000") <= score <= Decimal("1.0000")

    def test_load_from_disk_success(self, tmp_path, trained_isolation_forest, sample_metadata):
        model_path = tmp_path / "model.pkl"
        meta_path = tmp_path / "model_meta.json"

        with open(model_path, "wb") as f:
            pickle.dump(trained_isolation_forest, f)

        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(sample_metadata.to_dict(), f)

        scorer = MLAnomalyScorer.load(model_path, meta_path)
        assert scorer.metadata.model_version == "1.0.0-test"

    def test_fail_closed_on_missing_model_file(self, tmp_path, sample_metadata):
        model_path = tmp_path / "non_existent_model.pkl"
        meta_path = tmp_path / "model_meta.json"

        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(sample_metadata.to_dict(), f)

        with pytest.raises(MLModelLoadError) as exc_info:
            MLAnomalyScorer.load(model_path, meta_path)
        assert "Isolation Forest model artifact missing" in exc_info.value.message

    def test_fail_closed_on_missing_meta_file(self, tmp_path, trained_isolation_forest):
        model_path = tmp_path / "model.pkl"
        meta_path = tmp_path / "non_existent_meta.json"

        with open(model_path, "wb") as f:
            pickle.dump(trained_isolation_forest, f)

        with pytest.raises(MLModelLoadError) as exc_info:
            MLAnomalyScorer.load(model_path, meta_path)
        assert "Model metadata JSON missing" in exc_info.value.message

    def test_fail_closed_on_corrupted_model_file(self, tmp_path, sample_metadata):
        model_path = tmp_path / "corrupted_model.pkl"
        meta_path = tmp_path / "model_meta.json"

        with open(model_path, "wb") as f:
            f.write(b"NOT_A_VALID_PICKLE_FILE")

        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(sample_metadata.to_dict(), f)

        with pytest.raises(MLModelLoadError) as exc_info:
            MLAnomalyScorer.load(model_path, meta_path)
        assert "Failed to unpickle model artifact" in exc_info.value.message
