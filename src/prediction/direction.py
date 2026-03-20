"""LightGBM direction classifier with Optuna hyperparameter search and walk-forward validation."""
from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import structlog
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)

logger = structlog.get_logger(__name__)


@dataclass
class ClassifierMetrics:
    accuracy: float
    precision: float
    recall: float
    brier_score: float
    auc: float

    def to_dict(self) -> dict[str, float]:
        return {
            "accuracy": self.accuracy,
            "precision": self.precision,
            "recall": self.recall,
            "brier_score": self.brier_score,
            "auc": self.auc,
        }


@dataclass
class WalkForwardResult:
    fold_metrics: list[ClassifierMetrics] = field(default_factory=list)

    @property
    def aggregated(self) -> ClassifierMetrics:
        if not self.fold_metrics:
            raise ValueError("No fold metrics available")
        n = len(self.fold_metrics)
        return ClassifierMetrics(
            accuracy=sum(m.accuracy for m in self.fold_metrics) / n,
            precision=sum(m.precision for m in self.fold_metrics) / n,
            recall=sum(m.recall for m in self.fold_metrics) / n,
            brier_score=sum(m.brier_score for m in self.fold_metrics) / n,
            auc=sum(m.auc for m in self.fold_metrics) / n,
        )


def compute_metrics(
    y_true: npt.NDArray[np.float64],
    y_prob: npt.NDArray[np.float64],
    threshold: float = 0.5,
) -> ClassifierMetrics:
    """Compute classification metrics from true labels and predicted probabilities."""
    y_pred = (y_prob >= threshold).astype(int)
    return ClassifierMetrics(
        accuracy=float(accuracy_score(y_true, y_pred)),
        precision=float(precision_score(y_true, y_pred, zero_division=0)),
        recall=float(recall_score(y_true, y_pred, zero_division=0)),
        brier_score=float(brier_score_loss(y_true, y_prob)),
        auc=float(roc_auc_score(y_true, y_prob)) if len(np.unique(y_true)) > 1 else 0.0,
    )


class DirectionClassifier:
    """LightGBM binary classifier predicting up/down over configurable N-day horizon."""

    def __init__(self, horizon: int = 5, params: dict[str, Any] | None = None) -> None:
        self.horizon = horizon
        self.params = params or self._default_params()
        self._model: Any = None
        self._feature_names: list[str] = []

    @staticmethod
    def _default_params() -> dict[str, Any]:
        return {
            "objective": "binary",
            "metric": "binary_logloss",
            "verbosity": -1,
            "num_leaves": 31,
            "learning_rate": 0.05,
            "n_estimators": 200,
            "min_child_samples": 20,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "reg_alpha": 0.1,
            "reg_lambda": 0.1,
        }

    def train(
        self,
        x_train: npt.NDArray[np.float64],
        y_train: npt.NDArray[np.float64],
        x_val: npt.NDArray[np.float64] | None = None,
        y_val: npt.NDArray[np.float64] | None = None,
        feature_names: list[str] | None = None,
    ) -> ClassifierMetrics | None:
        """Train the LightGBM model. Returns validation metrics if val data provided."""
        import lightgbm as lgb

        self._feature_names = feature_names or [f"f{i}" for i in range(x_train.shape[1])]
        callbacks: list[Any] = [lgb.log_evaluation(period=0)]
        if x_val is not None and y_val is not None:
            callbacks.append(lgb.early_stopping(stopping_rounds=20, verbose=False))

        self._model = lgb.LGBMClassifier(**self.params)
        eval_set: Any = [(x_val, y_val)] if x_val is not None and y_val is not None else None
        self._model.fit(
            x_train, y_train,
            eval_set=eval_set,
            callbacks=callbacks,
        )

        if x_val is not None and y_val is not None:
            proba: Any = self._model.predict_proba(x_val)
            y_prob: npt.NDArray[np.float64] = proba[:, 1].astype(np.float64)
            return compute_metrics(y_val, y_prob)
        return None

    def predict_proba(self, x: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        """Return probability of upward movement (class 1)."""
        if self._model is None:
            raise RuntimeError("Model not trained")
        result: Any = self._model.predict_proba(x)
        return np.asarray(result[:, 1], dtype=np.float64)

    def predict_direction(
        self, x: npt.NDArray[np.float64],
    ) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
        """Map probability to direction [-1, +1] and confidence [0, 1]."""
        proba = self.predict_proba(x)
        direction: npt.NDArray[np.float64] = np.where(
            proba > 0.5, 1.0, np.where(proba < 0.5, -1.0, 0.0),
        ).astype(np.float64)
        confidence: npt.NDArray[np.float64] = (np.abs(proba - 0.5) * 2.0).astype(np.float64)
        return direction, confidence

    @property
    def feature_names(self) -> list[str]:
        return list(self._feature_names)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({
                "model": self._model, "feature_names": self._feature_names,
                "horizon": self.horizon, "params": self.params,
            }, f)

    @classmethod
    def load(cls, path: Path) -> DirectionClassifier:
        with open(path, "rb") as f:
            data: dict[str, Any] = pickle.load(f)  # noqa: S301
        obj = cls(horizon=data["horizon"], params=data["params"])
        obj._model = data["model"]
        obj._feature_names = data["feature_names"]
        return obj


def walk_forward_validate(
    x: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
    step_size: int,
    min_train_size: int,
    params: dict[str, Any] | None = None,
    feature_names: list[str] | None = None,
) -> WalkForwardResult:
    """Expanding-window walk-forward validation. Train on [0, t], predict [t, t+step]."""
    result = WalkForwardResult()
    n = len(x)
    t = min_train_size
    while t + step_size <= n:
        x_train, y_train = x[:t], y[:t]
        x_val, y_val = x[t:t + step_size], y[t:t + step_size]
        clf = DirectionClassifier(params=params)
        clf.train(x_train, y_train, feature_names=feature_names)
        y_prob = clf.predict_proba(x_val)
        metrics = compute_metrics(y_val, y_prob)
        result.fold_metrics.append(metrics)
        t += step_size
    return result


def optuna_search(
    x_train: npt.NDArray[np.float64],
    y_train: npt.NDArray[np.float64],
    x_val: npt.NDArray[np.float64],
    y_val: npt.NDArray[np.float64],
    n_trials: int = 50,
    feature_names: list[str] | None = None,
) -> dict[str, Any]:
    """Bayesian hyperparameter optimization targeting accuracy and Brier score."""
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial: optuna.Trial) -> float:
        params: dict[str, Any] = {
            "objective": "binary",
            "metric": "binary_logloss",
            "verbosity": -1,
            "num_leaves": trial.suggest_int("num_leaves", 15, 63),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "n_estimators": trial.suggest_int("n_estimators", 50, 500),
            "min_child_samples": trial.suggest_int("min_child_samples", 5, 50),
            "subsample": trial.suggest_float("subsample", 0.5, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-3, 10.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-3, 10.0, log=True),
        }
        clf = DirectionClassifier(params=params)
        metrics = clf.train(x_train, y_train, x_val, y_val, feature_names=feature_names)
        if metrics is None:
            return 1.0
        return metrics.brier_score - metrics.accuracy

    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=n_trials)
    best: dict[str, Any] = dict(study.best_trial.params)
    best.update({"objective": "binary", "metric": "binary_logloss", "verbosity": -1})
    logger.info("optuna_best_params", params=best, score=study.best_value)
    return best
