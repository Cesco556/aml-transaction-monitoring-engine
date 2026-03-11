"""ML Anomaly Detection rule — wraps the Isolation Forest model as a BaseRule."""

from __future__ import annotations

from logging import getLogger
from typing import Any

from aml_monitoring.rules.base import BaseRule, RuleContext
from aml_monitoring.schemas import RuleResult

logger = getLogger(__name__)

# Lazy imports to keep ML layer optional
_ml_available = True
try:
    from aml_monitoring.ml.anomaly import load_model, score_anomaly
    from aml_monitoring.ml.features import extract_single_features
except ImportError:
    _ml_available = False


class MLAnomalyRule(BaseRule):
    """Rule that scores transactions using a trained Isolation Forest model.

    Gracefully skips if:
    - sklearn is not installed
    - model file doesn't exist on disk
    """

    rule_id = "MLAnomaly"

    def __init__(self, config: dict[str, Any]) -> None:
        self.threshold = float(config.get("threshold", 0.7))
        self.model_path = config.get("model_path", "models/isolation_forest.joblib")
        self.severity = str(config.get("severity", "medium"))
        self.score_delta = float(config.get("score_delta", 20.0))
        self._model_artifact: dict[str, Any] | None = None
        self._load_attempted = False

    def _ensure_model(self) -> bool:
        """Attempt to load model once. Returns True if available."""
        if self._model_artifact is not None:
            return True
        if self._load_attempted:
            return False
        self._load_attempted = True

        if not _ml_available:
            logger.warning(
                "MLAnomalyRule: scikit-learn not installed — rule disabled."
            )
            return False

        artifact = load_model(self.model_path)
        if artifact is None:
            logger.warning(
                "MLAnomalyRule: no model at %s — rule disabled. Run 'aml train-ml' first.",
                self.model_path,
            )
            return False

        self._model_artifact = artifact
        logger.info(
            "MLAnomalyRule: loaded model from %s (data_hash=%s)",
            self.model_path,
            artifact.get("data_hash", "?"),
        )
        return True

    def evaluate(self, ctx: RuleContext) -> list[RuleResult]:
        """Score transaction through the anomaly model."""
        if not self._ensure_model():
            return []

        try:
            features = extract_single_features(ctx, ctx.session)
            anomaly_score = score_anomaly(features, self._model_artifact)  # type: ignore[arg-type]
        except Exception:
            logger.exception("MLAnomalyRule: scoring failed for txn %s", ctx.transaction_id)
            return []

        if anomaly_score >= self.threshold:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    severity=self.severity,
                    reason=(
                        f"ML anomaly score {anomaly_score:.3f} >= threshold {self.threshold}"
                    ),
                    evidence_fields={
                        "anomaly_score": round(anomaly_score, 4),
                        "threshold": self.threshold,
                        "model_path": self.model_path,
                        "features": {k: round(v, 4) for k, v in features.items()},
                    },
                    score_delta=self.score_delta,
                )
            ]
        return []
