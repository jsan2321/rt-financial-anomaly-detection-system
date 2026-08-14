"""
Unit tests for RT-FADS offline ML model training pipeline.
"""

from decimal import Decimal
import json
from pathlib import Path
import pickle
import sys
import numpy as np
import pytest
from sklearn.ensemble import IsolationForest

# Ensure scripts directory is on sys.path
scripts_path = Path(__file__).resolve().parents[2] / "scripts"
if str(scripts_path) not in sys.path:
    sys.path.insert(0, str(scripts_path))

from train_model import (
    FEATURE_NAMES,
    build_metadata,
    generate_synthetic_training_data,
    parse_args,
    run_training_pipeline,
    save_artifacts,
    train_isolation_forest,
)
from services.processor.domain.ml_model import MLAnomalyScorer
from services.processor.domain.schemas import TransactionContext


def test_generate_synthetic_training_data() -> None:
    X = generate_synthetic_training_data(n_samples=500, contamination=0.10, random_seed=42)
    assert isinstance(X, np.ndarray)
    assert X.shape == (500, 5)

    # Validate feature ranges
    amounts = X[:, 0]
    hours = X[:, 1]
    countries = X[:, 2]
    categories = X[:, 3]
    rolling = X[:, 4]

    assert np.all(amounts >= 2.50)
    assert np.all(hours >= 0.0) and np.all(hours <= 23.0)
    assert np.all(countries >= 0.1) and np.all(countries <= 1.0)
    assert np.all(categories >= 0.1) and np.all(categories <= 1.0)
    assert np.all(rolling >= 0.0)


def test_train_isolation_forest() -> None:
    X = generate_synthetic_training_data(n_samples=200, contamination=0.05, random_seed=42)
    model, min_score, max_score = train_isolation_forest(
        X=X,
        n_estimators=15,
        contamination=0.05,
        random_seed=42,
    )

    assert isinstance(model, IsolationForest)
    assert min_score < max_score
    assert isinstance(min_score, float)
    assert isinstance(max_score, float)


def test_build_metadata() -> None:
    meta = build_metadata(
        min_score=-0.25,
        max_score=0.25,
        sample_size=1000,
        contamination=0.05,
        n_estimators=50,
        model_version="1.2.0",
    )

    assert meta["model_version"] == "1.2.0"
    assert meta["min_score"] == -0.25
    assert meta["max_score"] == 0.25
    assert meta["feature_names"] == FEATURE_NAMES
    assert meta["training_sample_size"] == 1000
    assert meta["contamination"] == 0.05
    assert meta["n_estimators"] == 50
    assert "US" in meta["country_risk_tiers"]
    assert "groceries" in meta["merchant_category_map"]
    assert "trained_at" in meta


def test_save_and_load_artifacts(tmp_path) -> None:
    X = generate_synthetic_training_data(n_samples=150, contamination=0.05, random_seed=42)
    model, min_s, max_s = train_isolation_forest(X=X, n_estimators=10, random_seed=42)
    meta = build_metadata(min_score=min_s, max_score=max_s, sample_size=150, contamination=0.05, n_estimators=10)

    model_path, meta_path = save_artifacts(model, meta, output_dir=tmp_path)
    assert model_path.exists()
    assert meta_path.exists()

    # Load using Processor's MLAnomalyScorer
    scorer = MLAnomalyScorer.load(model_path, meta_path)
    assert scorer.metadata.model_version == "1.0.0"

    import uuid
    from datetime import datetime, timezone
    sample_txn = TransactionContext(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        amount=Decimal("150.00"),
        currency="USD",
        country="US",
        merchant_category="groceries",
        created_at=datetime.now(timezone.utc),
    )
    score = scorer.score(sample_txn)
    assert isinstance(score, Decimal)
    assert Decimal("0.0000") <= score <= Decimal("1.0000")


def test_run_training_pipeline(tmp_path) -> None:
    result = run_training_pipeline(
        samples=250,
        contamination=0.05,
        n_estimators=10,
        output_dir=tmp_path,
        random_seed=123,
    )

    assert result["status"] == "success"
    assert result["samples"] == 250
    assert Path(result["model_path"]).exists()
    assert Path(result["metadata_path"]).exists()


def test_parse_args_defaults() -> None:
    opts = parse_args([])
    assert opts.samples == 10000
    assert opts.contamination == 0.05
    assert opts.estimators == 100
    assert opts.output_dir == "models"
    assert opts.model_name == "model.pkl"
    assert opts.meta_name == "model_meta.json"
    assert opts.random_seed == 42
    assert opts.model_version == "1.0.0"


def test_parse_args_custom() -> None:
    opts = parse_args([
        "--samples", "20000",
        "--contamination", "0.08",
        "--estimators", "150",
        "--output-dir", "custom_models",
        "--model-name", "custom.pkl",
        "--meta-name", "custom_meta.json",
        "--random-seed", "99",
        "--model-version", "2.0.0",
    ])
    assert opts.samples == 20000
    assert opts.contamination == 0.08
    assert opts.estimators == 150
    assert opts.output_dir == "custom_models"
    assert opts.model_name == "custom.pkl"
    assert opts.meta_name == "custom_meta.json"
    assert opts.random_seed == 99
    assert opts.model_version == "2.0.0"
