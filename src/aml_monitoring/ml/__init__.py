"""ML anomaly detection layer (optional — gracefully degrades if sklearn unavailable)."""

from __future__ import annotations

try:
    from aml_monitoring.ml.anomaly import score_anomaly, train_anomaly_model
    from aml_monitoring.ml.features import build_feature_matrix, extract_single_features

    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False

__all__ = [
    "ML_AVAILABLE",
    "build_feature_matrix",
    "extract_single_features",
    "train_anomaly_model",
    "score_anomaly",
]
