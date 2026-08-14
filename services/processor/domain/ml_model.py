"""
Machine Learning Anomaly Scoring wrapper using scikit-learn Isolation Forest.
Implements model loading, feature extraction, normalization, and fail-closed safety.
"""

from decimal import Decimal
import json
import os
from pathlib import Path
import pickle
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

from shared.errors.exceptions import RTFADSError

from .schemas import TransactionContext, VelocityContext


class MLModelLoadError(RTFADSError):
    """Raised when the ML model or metadata fails to load at startup (Fail-Closed)."""

    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(
            message=message,
            code="ML_MODEL_LOAD_FAILED",
            status_code=500,
            details=details,
        )


class MLMetadata:
    """Encapsulates training-time metadata, feature names, and normalization parameters."""

    DEFAULT_COUNTRY_TIERS: Dict[str, float] = {
        "US": 0.1,
        "CA": 0.1,
        "GB": 0.1,
        "DE": 0.1,
        "FR": 0.1,
        "AU": 0.1,
        "JP": 0.1,
        "SG": 0.1,
        "BR": 0.4,
        "IN": 0.4,
        "MX": 0.4,
        "ZA": 0.5,
        "NG": 0.8,
        "RU": 0.8,
        "KP": 1.0,
        "IR": 1.0,
        "SY": 1.0,
    }

    DEFAULT_CATEGORY_MAP: Dict[str, float] = {
        "groceries": 0.1,
        "supermarket": 0.1,
        "pharmacy": 0.1,
        "utilities": 0.1,
        "retail": 0.2,
        "restaurant": 0.2,
        "travel": 0.4,
        "electronics": 0.5,
        "jewelry": 0.7,
        "money_transfer": 0.8,
        "crypto": 0.9,
        "gambling": 0.95,
        "weapons": 1.0,
    }

    def __init__(
        self,
        model_version: str = "1.0.0",
        min_score: float = -0.30,
        max_score: float = 0.30,
        feature_names: Optional[List[str]] = None,
        country_risk_tiers: Optional[Dict[str, float]] = None,
        merchant_category_map: Optional[Dict[str, float]] = None,
    ):
        self.model_version = model_version
        self.min_score = float(min_score)
        self.max_score = float(max_score)
        self.feature_names = feature_names or [
            "amount",
            "hour_of_day",
            "country_risk_tier",
            "merchant_category_code",
            "user_rolling_count",
        ]
        self.country_risk_tiers = (
            country_risk_tiers
            if country_risk_tiers is not None
            else self.DEFAULT_COUNTRY_TIERS
        )
        self.merchant_category_map = (
            merchant_category_map
            if merchant_category_map is not None
            else self.DEFAULT_CATEGORY_MAP
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MLMetadata":
        return cls(
            model_version=data.get("model_version", "1.0.0"),
            min_score=float(data.get("min_score", -0.30)),
            max_score=float(data.get("max_score", 0.30)),
            feature_names=data.get("feature_names"),
            country_risk_tiers=data.get("country_risk_tiers"),
            merchant_category_map=data.get("merchant_category_map"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_version": self.model_version,
            "min_score": self.min_score,
            "max_score": self.max_score,
            "feature_names": self.feature_names,
            "country_risk_tiers": self.country_risk_tiers,
            "merchant_category_map": self.merchant_category_map,
        }


class MLAnomalyScorer:
    """
    Stateless scorer wrapping an Isolation Forest estimator.
    Converts transactions to standard feature vectors and normalizes raw scores to [0.0, 1.0].
    """

    def __init__(self, model: Any, metadata: MLMetadata):
        if not hasattr(model, "decision_function") and not hasattr(model, "score_samples"):
            raise MLModelLoadError(
                "Model object must implement `decision_function` or `score_samples`."
            )
        self.model = model
        self.metadata = metadata

    @classmethod
    def load(
        cls,
        model_path: Union[str, Path],
        metadata_path: Union[str, Path],
    ) -> "MLAnomalyScorer":
        """
        Loads model artifact and metadata from disk.
        Fails closed with MLModelLoadError if files are missing or corrupt.
        """
        m_path = Path(model_path)
        meta_path = Path(metadata_path)

        if not m_path.exists():
            raise MLModelLoadError(
                f"Isolation Forest model artifact missing at '{m_path}'. Service cannot start in fail-closed mode.",
                details={"model_path": str(m_path)},
            )
        if not meta_path.exists():
            raise MLModelLoadError(
                f"Model metadata JSON missing at '{meta_path}'. Service cannot start in fail-closed mode.",
                details={"metadata_path": str(meta_path)},
            )

        try:
            with open(m_path, "rb") as f:
                model = pickle.load(f)
        except Exception as e:
            raise MLModelLoadError(
                f"Failed to unpickle model artifact at '{m_path}': {str(e)}",
                details={"error": str(e)},
            )

        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                raw_meta = json.load(f)
            metadata = MLMetadata.from_dict(raw_meta)
        except Exception as e:
            raise MLModelLoadError(
                f"Failed to parse metadata JSON at '{meta_path}': {str(e)}",
                details={"error": str(e)},
            )

        return cls(model=model, metadata=metadata)

    def extract_features(
        self,
        transaction: TransactionContext,
        velocity: Optional[VelocityContext] = None,
    ) -> np.ndarray:
        """
        Extracts the 5 fixed features into a 2D numpy array:
        [amount, hour_of_day, country_risk_tier, merchant_category_code, user_rolling_count]
        """
        amount = float(transaction.amount)
        hour_of_day = float(transaction.created_at.hour)

        # Country risk tier
        country_code = transaction.country.strip().upper()
        country_risk = self.metadata.country_risk_tiers.get(country_code, 0.3)

        # Merchant category encoding
        cat = transaction.merchant_category.strip().lower()
        category_risk = self.metadata.merchant_category_map.get(cat, 0.3)

        # User rolling count
        rolling_count = float(velocity.transaction_count) if velocity else 0.0

        features = np.array(
            [[amount, hour_of_day, country_risk, category_risk, rolling_count]],
            dtype=np.float64,
        )
        return features

    def score(
        self,
        transaction: TransactionContext,
        velocity: Optional[VelocityContext] = None,
    ) -> Decimal:
        """
        Computes normalized anomaly score in [0.0000, 1.0000].
        1.0000 represents highest anomaly likelihood; 0.0000 represents typical behavior.
        """
        features = self.extract_features(transaction, velocity)

        if hasattr(self.model, "decision_function"):
            # IsolationForest decision_function: lower is more abnormal (< 0 = anomaly)
            raw_decision = float(self.model.decision_function(features)[0])
            # Invert so higher = more abnormal
            raw_score = -raw_decision
        else:
            raw_score = -float(self.model.score_samples(features)[0])

        # Min-max normalization
        min_s = self.metadata.min_score
        max_s = self.metadata.max_score

        if max_s > min_s:
            norm = (raw_score - min_s) / (max_s - min_s)
        else:
            norm = 0.5

        # Clamp to [0.0, 1.0]
        clamped = max(0.0, min(1.0, norm))

        # Return Decimal with 4 fractional digits
        return Decimal(f"{clamped:.4f}")
