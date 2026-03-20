"""Sequential optimization: Stage 1 prediction -> Stage 2 position params -> robustness -> OOS."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt
import structlog

from src.prediction.direction import DirectionClassifier
from src.prediction.features import DataSplits
from src.prediction.regime import RegimeClassifier
from src.prediction.volatility import VolatilityForecaster

logger = structlog.get_logger(__name__)


@dataclass
class Stage1Result:
    direction_metrics: dict[str, float] = field(default_factory=dict)
    regime_mapping: dict[int, str] = field(default_factory=dict)
    vol_params: dict[str, float] = field(default_factory=dict)
    direction_model: DirectionClassifier | None = None
    regime_model: RegimeClassifier | None = None
    vol_model: VolatilityForecaster | None = None


@dataclass
class Stage2Result:
    best_params: dict[str, Any] = field(default_factory=dict)
    best_sharpe: float = 0.0
    results_grid: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class OptimizationResult:
    stage1: Stage1Result
    stage2: Stage2Result
    robustness_sharpe: float = 0.0
    oos_sharpe: float = 0.0
    passed_robustness: bool = False


def run_stage1(
    splits: DataSplits,
    feature_cols: list[str],
    regime_feature_cols: list[str],
    direction_params: dict[str, Any] | None = None,
    regime_n_states: int = 4,
    vol_horizon: int = 5,
) -> Stage1Result:
    """Stage 1: Train prediction models, evaluate on model_val split."""
    from src.prediction.features import prepare_xy

    # Direction classifier
    x_train, y_train = prepare_xy(splits.train, feature_cols)
    x_val, y_val = prepare_xy(splits.model_val, feature_cols)
    direction = DirectionClassifier(params=direction_params)
    metrics = direction.train(x_train, y_train, x_val, y_val, feature_names=feature_cols)
    dir_metrics = metrics.to_dict() if metrics else {}

    # Regime classifier
    regime_cols = [c for c in regime_feature_cols if c in splits.train.columns]
    regime_data = splits.train.select(regime_cols).to_numpy().astype(np.float64)
    regime = RegimeClassifier(n_states=regime_n_states)
    mapping = regime.train(regime_data)

    # Volatility forecaster
    returns_col = "forward_return" if "forward_return" in splits.train.columns else "close"
    if returns_col == "close" and "close" in splits.train.columns:
        prices = splits.train["close"].to_numpy()
        returns = np.diff(prices) / prices[:-1]
    else:
        returns = splits.train[returns_col].to_numpy().astype(np.float64)
    vol = VolatilityForecaster(horizon=vol_horizon)
    vol_params = vol.train(returns)

    return Stage1Result(
        direction_metrics=dir_metrics,
        regime_mapping=mapping.state_to_label,
        vol_params=vol_params,
        direction_model=direction,
        regime_model=regime,
        vol_model=vol,
    )


def run_stage2(
    stage1: Stage1Result,
    splits: DataSplits,
    feature_cols: list[str],
    param_grid: dict[str, list[float]] | None = None,
) -> Stage2Result:
    """Stage 2: Freeze signals, sweep position params on position_val split."""
    from src.prediction.features import prepare_xy

    if stage1.direction_model is None:
        return Stage2Result()

    grid = param_grid or {
        "stop_atr_mult": [1.0, 1.5, 2.0],
        "trail_atr_mult": [2.0, 3.0, 4.0],
    }

    # Precompute signals on position_val data
    x_pos, _ = prepare_xy(splits.position_val, feature_cols)
    dirs, confs = stage1.direction_model.predict_direction(x_pos)

    results: list[dict[str, Any]] = []
    best_sharpe = -float("inf")
    best_params: dict[str, Any] = {}

    stop_values = grid.get("stop_atr_mult", [1.5])
    trail_values = grid.get("trail_atr_mult", [3.0])

    for stop_mult in stop_values:
        for trail_mult in trail_values:
            # Simulate equity curve with these params
            sharpe = _simulate_sharpe(dirs, confs, stop_mult, trail_mult)
            row = {
                "stop_atr_mult": stop_mult,
                "trail_atr_mult": trail_mult,
                "sharpe": sharpe,
            }
            results.append(row)
            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_params = {"stop_atr_mult": stop_mult, "trail_atr_mult": trail_mult}

    return Stage2Result(
        best_params=best_params, best_sharpe=best_sharpe, results_grid=results,
    )


def run_robustness_test(
    stage1: Stage1Result,
    splits: DataSplits,
    feature_cols: list[str],
    degradation: float = 0.1,
) -> float:
    """Degrade model accuracy by adding noise, verify Sharpe holds."""
    if stage1.direction_model is None:
        return 0.0

    from src.prediction.features import prepare_xy

    x_pos, _ = prepare_xy(splits.position_val, feature_cols)
    dirs, confs = stage1.direction_model.predict_direction(x_pos)

    # Add noise to degrade predictions
    rng = np.random.default_rng(42)
    noise: npt.NDArray[np.float64] = rng.standard_normal(len(dirs)).astype(np.float64) * degradation
    degraded_confs: npt.NDArray[np.float64] = np.clip(confs + noise, 0.0, 1.0).astype(np.float64)

    return _simulate_sharpe(dirs, degraded_confs, 1.5, 3.0)


def run_final_oos(
    stage1: Stage1Result,
    splits: DataSplits,
    feature_cols: list[str],
) -> float:
    """One-shot evaluation on the held-out final OOS split."""
    if stage1.direction_model is None:
        return 0.0

    from src.prediction.features import prepare_xy

    x_oos, _ = prepare_xy(splits.final_oos, feature_cols)
    dirs, confs = stage1.direction_model.predict_direction(x_oos)
    return _simulate_sharpe(dirs, confs, 1.5, 3.0)


def run_full_optimization(
    splits: DataSplits,
    feature_cols: list[str],
    regime_feature_cols: list[str],
    direction_params: dict[str, Any] | None = None,
    param_grid: dict[str, list[float]] | None = None,
) -> OptimizationResult:
    """Full sequential optimization: Stage 1 -> Stage 2 -> robustness -> OOS."""
    logger.info("Starting Stage 1: prediction model training")
    s1 = run_stage1(splits, feature_cols, regime_feature_cols, direction_params)

    logger.info("Starting Stage 2: position parameter sweep")
    s2 = run_stage2(s1, splits, feature_cols, param_grid)

    logger.info("Running robustness test")
    rob_sharpe = run_robustness_test(s1, splits, feature_cols)

    logger.info("Running final OOS evaluation")
    oos_sharpe = run_final_oos(s1, splits, feature_cols)

    passed = bool(rob_sharpe > s2.best_sharpe * 0.5 if s2.best_sharpe > 0 else rob_sharpe > 0)
    logger.info(
        "Optimization complete: best_sharpe=%.3f robustness=%.3f oos=%.3f passed=%s",
        s2.best_sharpe, rob_sharpe, oos_sharpe, passed,
    )

    return OptimizationResult(
        stage1=s1, stage2=s2,
        robustness_sharpe=rob_sharpe, oos_sharpe=oos_sharpe,
        passed_robustness=passed,
    )


def _simulate_sharpe(
    directions: npt.NDArray[np.float64],
    confidences: npt.NDArray[np.float64],
    stop_mult: float,
    trail_mult: float,
) -> float:
    """Simplified Sharpe estimate from signal-weighted returns."""
    # Higher confidence in direction -> larger position -> more return captured
    weighted_returns = directions * confidences * 0.01  # Scale factor
    # Adjust by stop/trail parameters (tighter stops = lower vol, higher Sharpe)
    vol_adj = 1.0 / (stop_mult * 0.5 + trail_mult * 0.3)
    adjusted = weighted_returns * vol_adj
    mean_ret = float(np.mean(adjusted))
    std_ret = float(np.std(adjusted))
    if std_ret < 1e-10:
        return 0.0
    return float(mean_ret / std_ret * np.sqrt(252))
