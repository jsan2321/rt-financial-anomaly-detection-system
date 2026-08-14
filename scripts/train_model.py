"""
Offline ML Model Training Pipeline for RT-FADS.
Generates synthetic transaction feature distributions, fits scikit-learn Isolation Forest,
calibrates score normalization bounds, and exports model artifacts for the Processor service.
"""

import argparse
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import pickle
import sys
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
from sklearn.ensemble import IsolationForest

# Setup logger
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("train_model")

FEATURE_NAMES = [
    "amount",
    "hour_of_day",
    "country_risk_tier",
    "merchant_category_code",
    "user_rolling_count",
]

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


def generate_synthetic_training_data(
    n_samples: int = 10000,
    contamination: float = 0.05,
    random_seed: int = 42,
) -> np.ndarray:
    """
    Generates a 5-dimensional feature matrix X of synthetic financial transactions.
    Features: [amount, hour_of_day, country_risk_tier, merchant_category_code, user_rolling_count]
    """
    rng = np.random.RandomState(random_seed)
    n_anomalies = int(n_samples * contamination)
    n_normal = n_samples - n_anomalies

    # 1. Normal Transactions (Benign behavioral distribution)
    normal_amounts = np.clip(rng.lognormal(mean=3.8, sigma=1.0, size=n_normal), 2.50, 750.0)
    normal_hours = np.clip(rng.normal(loc=14.0, scale=4.0, size=n_normal), 0.0, 23.0)
    normal_countries = rng.choice([0.1, 0.4], size=n_normal, p=[0.95, 0.05])
    normal_categories = rng.choice([0.1, 0.2, 0.4, 0.5], size=n_normal, p=[0.45, 0.35, 0.10, 0.10])
    normal_rolling = np.clip(rng.poisson(lam=1.5, size=n_normal), 0, 5).astype(float)

    normal_matrix = np.column_stack([
        normal_amounts,
        normal_hours,
        normal_countries,
        normal_categories,
        normal_rolling,
    ])

    # 2. Anomalous Transactions (Extreme outliers across dimensions)
    anom_amounts = rng.uniform(low=8500.0, high=50000.0, size=n_anomalies)
    anom_hours = rng.choice([1.0, 2.0, 3.0, 4.0, 23.0], size=n_anomalies)
    anom_countries = rng.choice([0.8, 1.0], size=n_anomalies, p=[0.60, 0.40])
    anom_categories = rng.choice([0.8, 0.9, 0.95, 1.0], size=n_anomalies, p=[0.30, 0.30, 0.25, 0.15])
    anom_rolling = rng.uniform(low=8.0, high=30.0, size=n_anomalies)

    anomaly_matrix = np.column_stack([
        anom_amounts,
        anom_hours,
        anom_countries,
        anom_categories,
        anom_rolling,
    ])

    # Combine and shuffle
    combined = np.vstack([normal_matrix, anomaly_matrix])
    shuffled_indices = rng.permutation(len(combined))
    return combined[shuffled_indices]


def train_isolation_forest(
    X: np.ndarray,
    n_estimators: int = 100,
    contamination: float = 0.05,
    random_seed: int = 42,
) -> Tuple[IsolationForest, float, float]:
    """
    Fits an Isolation Forest model and computes min/max raw decision scores for normalization.
    """
    logger.info(
        f"Fitting IsolationForest (estimators={n_estimators}, contamination={contamination}, samples={len(X)})..."
    )
    model = IsolationForest(
        n_estimators=n_estimators,
        contamination=contamination,
        max_samples="auto",
        random_state=random_seed,
        n_jobs=-1,
    )
    model.fit(X)

    # Invert decision function so higher = more abnormal
    raw_scores = -model.decision_function(X)
    min_score = float(np.min(raw_scores))
    max_score = float(np.max(raw_scores))

    # Add a slight boundary margin to avoid saturation at calibration endpoints
    calibrated_min = round(min_score - 0.02, 4)
    calibrated_max = round(max_score + 0.02, 4)

    logger.info(f"Model calibrated: raw_score range = [{min_score:.4f}, {max_score:.4f}] -> bounds [{calibrated_min}, {calibrated_max}]")
    return model, calibrated_min, calibrated_max


def build_metadata(
    min_score: float,
    max_score: float,
    sample_size: int,
    contamination: float,
    n_estimators: int,
    model_version: str = "1.0.0",
) -> Dict[str, Any]:
    """Builds the metadata dictionary conforming to MLMetadata."""
    return {
        "model_version": model_version,
        "min_score": min_score,
        "max_score": max_score,
        "feature_names": FEATURE_NAMES,
        "country_risk_tiers": DEFAULT_COUNTRY_TIERS,
        "merchant_category_map": DEFAULT_CATEGORY_MAP,
        "training_sample_size": sample_size,
        "contamination": contamination,
        "n_estimators": n_estimators,
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }


def save_artifacts(
    model: IsolationForest,
    metadata: Dict[str, Any],
    output_dir: Path,
    model_filename: str = "model.pkl",
    meta_filename: str = "model_meta.json",
) -> Tuple[Path, Path]:
    """Serializes the model and metadata to disk."""
    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / model_filename
    meta_path = output_dir / meta_filename

    logger.info(f"Writing model artifact to {model_path}...")
    with open(model_path, "wb") as f:
        pickle.dump(model, f, protocol=pickle.HIGHEST_PROTOCOL)

    logger.info(f"Writing metadata to {meta_path}...")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    return model_path, meta_path


def run_training_pipeline(
    samples: int = 10000,
    contamination: float = 0.05,
    n_estimators: int = 100,
    output_dir: Union[str, Path] = "models",
    model_filename: str = "model.pkl",
    meta_filename: str = "model_meta.json",
    random_seed: int = 42,
    model_version: str = "1.0.0",
) -> Dict[str, Any]:
    """Full execution handler for generating data, training model, and persisting artifacts."""
    out_path = Path(output_dir)
    logger.info("=" * 70)
    logger.info("RT-FADS Offline ML Model Training Pipeline")
    logger.info(f"Sample Count:      {samples:,}")
    logger.info(f"Contamination:     {contamination * 100:.1f}%")
    logger.info(f"Trees (Estimators):{n_estimators}")
    logger.info(f"Output Directory:  {out_path.resolve()}")
    logger.info("=" * 70)

    # 1. Generate Synthetic Training Data
    X = generate_synthetic_training_data(
        n_samples=samples,
        contamination=contamination,
        random_seed=random_seed,
    )
    logger.info(f"Generated synthetic training matrix with shape {X.shape}")

    # 2. Train and Calibrate Model
    model, min_s, max_s = train_isolation_forest(
        X=X,
        n_estimators=n_estimators,
        contamination=contamination,
        random_seed=random_seed,
    )

    # 3. Assemble Metadata
    meta = build_metadata(
        min_score=min_s,
        max_score=max_s,
        sample_size=samples,
        contamination=contamination,
        n_estimators=n_estimators,
        model_version=model_version,
    )

    # 4. Save Artifacts
    model_file, meta_file = save_artifacts(
        model=model,
        metadata=meta,
        output_dir=out_path,
        model_filename=model_filename,
        meta_filename=meta_filename,
    )

    print("\n" + "=" * 70)
    print(" RT-FADS MODEL TRAINING COMPLETE")
    print("=" * 70)
    print(f" Model Artifact:     {model_file.resolve()}")
    print(f" Metadata Artifact:  {meta_file.resolve()}")
    print(f" Calibration Bounds: [{min_s:.4f}, {max_s:.4f}]")
    print(f" Training Samples:   {samples:,} records (5 features)")
    print("=" * 70 + "\n")

    return {
        "status": "success",
        "model_path": str(model_file),
        "metadata_path": str(meta_file),
        "min_score": min_s,
        "max_score": max_s,
        "samples": samples,
    }


def parse_args(args: Optional[List[str]] = None) -> argparse.Namespace:
    """Parses command-line arguments for model training."""
    parser = argparse.ArgumentParser(
        description="RT-FADS Offline ML Model Training Pipeline — Fits and exports Isolation Forest model.",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=10000,
        help="Number of synthetic training samples to generate (default: 10000)",
    )
    parser.add_argument(
        "--contamination",
        type=float,
        default=0.05,
        help="Expected proportion of anomalies in dataset (default: 0.05)",
    )
    parser.add_argument(
        "--estimators",
        type=int,
        default=100,
        help="Number of trees in Isolation Forest ensemble (default: 100)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="models",
        help="Output directory for generated model artifacts (default: models)",
    )
    parser.add_argument(
        "--model-name",
        type=str,
        default="model.pkl",
        help="Filename for serialized model pickle (default: model.pkl)",
    )
    parser.add_argument(
        "--meta-name",
        type=str,
        default="model_meta.json",
        help="Filename for metadata JSON (default: model_meta.json)",
    )
    parser.add_argument(
        "--random-seed",
        type=int,
        default=42,
        help="Random seed for data generation and model fitting (default: 42)",
    )
    parser.add_argument(
        "--model-version",
        type=str,
        default="1.0.0",
        help="Model semantic version string (default: 1.0.0)",
    )
    return parser.parse_args(args)


def main() -> None:
    opts = parse_args()
    if opts.samples < 50:
        logger.error("Error: --samples must be at least 50.")
        sys.exit(1)
    if not (0.001 <= opts.contamination <= 0.5):
        logger.error("Error: --contamination must be between 0.001 and 0.5.")
        sys.exit(1)

    try:
        run_training_pipeline(
            samples=opts.samples,
            contamination=opts.contamination,
            n_estimators=opts.estimators,
            output_dir=opts.output_dir,
            model_filename=opts.model_name,
            meta_filename=opts.meta_name,
            random_seed=opts.random_seed,
            model_version=opts.model_version,
        )
    except Exception as exc:
        logger.error(f"Model training failed: {exc}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
