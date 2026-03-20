"""MLflow experiment tracking for prediction sub-models."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

DEFAULT_TRACKING_DIR = Path("mlruns")
EXPERIMENT_NAME = "quant-engine-prediction"


def setup_tracking(tracking_dir: Path | None = None) -> str:
    """Configure MLflow with local file store. Returns the tracking URI."""
    import mlflow

    uri = (tracking_dir or DEFAULT_TRACKING_DIR).resolve().as_uri()
    mlflow.set_tracking_uri(uri)
    mlflow.set_experiment(EXPERIMENT_NAME)
    logger.info("mlflow_tracking_uri", uri=uri)
    return uri


def log_training_run(
    model_type: str,
    params: dict[str, Any],
    metrics: dict[str, float],
    artifact_path: Path | None = None,
    tags: dict[str, str] | None = None,
) -> str:
    """Log a training run (params, metrics, optional model artifact). Returns run_id."""
    import mlflow

    with mlflow.start_run() as run:
        mlflow.set_tag("model_type", model_type)
        if tags:
            for k, v in tags.items():
                mlflow.set_tag(k, v)
        mlflow.log_params({k: str(v)[:250] for k, v in params.items()})
        mlflow.log_metrics(metrics)
        if artifact_path is not None and artifact_path.exists():
            mlflow.log_artifact(str(artifact_path))
        run_id: str = run.info.run_id
        logger.info("mlflow_run_logged", model_type=model_type, run_id=run_id, metrics=metrics)
        return run_id


def log_direction_run(
    params: dict[str, Any],
    metrics: dict[str, float],
    model_path: Path | None = None,
) -> str:
    return log_training_run("direction_classifier", params, metrics, model_path)


def log_regime_run(
    params: dict[str, Any],
    metrics: dict[str, float],
    model_path: Path | None = None,
) -> str:
    return log_training_run("regime_classifier", params, metrics, model_path)


def log_volatility_run(
    params: dict[str, Any],
    metrics: dict[str, float],
    model_path: Path | None = None,
) -> str:
    return log_training_run("volatility_forecaster", params, metrics, model_path)
