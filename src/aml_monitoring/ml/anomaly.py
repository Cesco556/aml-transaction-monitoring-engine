"""Isolation Forest anomaly detector — training, scoring, persistence."""

from __future__ import annotations

import hashlib
import json
from logging import getLogger
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sqlalchemy.orm import Session

from aml_monitoring.ml.features import build_feature_matrix

logger = getLogger(__name__)

# Feature columns used by default (matches config/default.yaml ml.anomaly_detection.features)
DEFAULT_FEATURES = [
    "amount_zscore",
    "velocity_1h",
    "velocity_24h",
    "counterparty_diversity",
    "country_diversity",
    "time_of_day_sin",
    "time_of_day_cos",
]


def _data_hash(X: np.ndarray, config: dict[str, Any]) -> str:
    """Deterministic hash of training data + config for model versioning."""
    data_bytes = X.tobytes()
    cfg_str = json.dumps(config, sort_keys=True)
    payload = data_bytes + cfg_str.encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def train_anomaly_model(
    session: Session,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Train an Isolation Forest on the current transaction feature matrix.

    Args:
        session: SQLAlchemy session with access to transactions.
        config: ML config dict (ml.anomaly_detection section).

    Returns:
        Dict with keys: model_path, sample_count, feature_count, anomaly_ratio, data_hash.
    """
    feature_names = config.get("features", DEFAULT_FEATURES)
    contamination = config.get("contamination", 0.05)
    n_estimators = config.get("n_estimators", 100)
    model_path = config.get("model_path", "models/isolation_forest.joblib")

    df = build_feature_matrix(session)
    if df.empty:
        raise ValueError("No transactions to train on — ingest data first.")

    # Ensure all requested features are present
    missing = [f for f in feature_names if f not in df.columns]
    if missing:
        raise ValueError(f"Missing features in matrix: {missing}")

    X = df[feature_names].values.astype(np.float64)

    model = IsolationForest(
        n_estimators=n_estimators,
        contamination=contamination,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X)

    # Anomaly ratio from training predictions
    predictions = model.predict(X)
    n_anomalies = int((predictions == -1).sum())
    anomaly_ratio = n_anomalies / len(predictions)

    # Persist model with metadata
    d_hash = _data_hash(X, config)
    artifact = {
        "model": model,
        "feature_names": feature_names,
        "data_hash": d_hash,
        "config": {
            "contamination": contamination,
            "n_estimators": n_estimators,
        },
        "sample_count": len(X),
    }

    Path(model_path).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, model_path)
    logger.info(
        "Saved anomaly model to %s (samples=%d, features=%d, anomaly_ratio=%.3f)",
        model_path,
        len(X),
        len(feature_names),
        anomaly_ratio,
    )

    return {
        "model_path": model_path,
        "sample_count": len(X),
        "feature_count": len(feature_names),
        "anomaly_ratio": anomaly_ratio,
        "data_hash": d_hash,
    }


def load_model(model_path: str) -> dict[str, Any] | None:
    """Load a saved model artifact. Returns None if file doesn't exist."""
    p = Path(model_path)
    if not p.exists():
        return None
    return joblib.load(model_path)


def score_anomaly(features: dict[str, float], model_artifact: dict[str, Any]) -> float:
    """Score a single transaction's features through the trained model.

    Returns a float between 0 and 1, where higher = more anomalous.
    """
    feature_names = model_artifact["feature_names"]
    model: IsolationForest = model_artifact["model"]

    X = np.array([[features.get(f, 0.0) for f in feature_names]], dtype=np.float64)

    # decision_function: lower (more negative) = more anomalous
    raw_score = model.decision_function(X)[0]

    # Normalize to 0-1 using sigmoid-like transform:
    # Isolation Forest decision_function centers near 0 for boundary;
    # negative = anomaly, positive = normal.
    # Map: score = 1 / (1 + exp(k * raw_score)) where k controls steepness.
    k = 5.0
    anomaly_score = 1.0 / (1.0 + np.exp(k * raw_score))

    return float(np.clip(anomaly_score, 0.0, 1.0))
