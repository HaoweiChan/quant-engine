"""Sequential optimization: Stage 1 prediction -> Stage 2 position params -> robustness -> OOS."""
from __future__ import annotations

import structlog
import numpy as np
import numpy.typing as npt

from typing import Any
from dataclasses import dataclass, field
from src.prediction.features import DataSplits
from src.prediction.regime import RegimeClassifier
from src.prediction.direction import DirectionClassifier
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
    forward_returns = _extract_forward_returns(splits.position_val)
    eval_len = min(len(dirs), len(confs), len(forward_returns))
    if eval_len <= 1:
        return Stage2Result()
    dirs_eval = dirs[:eval_len]
    confs_eval = confs[:eval_len]
    returns_eval = forward_returns[:eval_len]

    results: list[dict[str, Any]] = []
    best_sharpe = -float("inf")
    best_params: dict[str, Any] = {}

    stop_values = grid.get("stop_atr_mult", [1.5])
    trail_values = grid.get("trail_atr_mult", [3.0])

    for stop_mult in stop_values:
        for trail_mult in trail_values:
            score = _score_params_on_split(
                directions=dirs_eval,
                confidences=confs_eval,
                forward_returns=returns_eval,
                stop_mult=float(stop_mult),
                trail_mult=float(trail_mult),
            )
            row = {
                "stop_atr_mult": stop_mult,
                "trail_atr_mult": trail_mult,
                "sharpe": score["sharpe"],
                "trade_count": score["trade_count"],
                "expectancy": score["expectancy"],
                "net_return": score["net_return"],
            }
            results.append(row)
            if score["sharpe"] > best_sharpe:
                best_sharpe = score["sharpe"]
                best_params = {"stop_atr_mult": stop_mult, "trail_atr_mult": trail_mult}

    return Stage2Result(
        best_params=best_params, best_sharpe=best_sharpe, results_grid=results,
    )


def run_robustness_test(
    stage1: Stage1Result,
    splits: DataSplits,
    feature_cols: list[str],
    stage2_params: dict[str, Any] | None = None,
    degradation: float = 0.1,
) -> float:
    """Degrade model confidence by noise and re-score using frozen stage-2 params."""
    if stage1.direction_model is None:
        return 0.0

    from src.prediction.features import prepare_xy

    x_pos, _ = prepare_xy(splits.position_val, feature_cols)
    dirs, confs = stage1.direction_model.predict_direction(x_pos)
    forward_returns = _extract_forward_returns(splits.position_val)
    eval_len = min(len(dirs), len(confs), len(forward_returns))
    if eval_len <= 1:
        return 0.0
    dirs_eval = dirs[:eval_len]
    confs_eval = confs[:eval_len]
    returns_eval = forward_returns[:eval_len]
    params = stage2_params or {"stop_atr_mult": 1.5, "trail_atr_mult": 3.0}

    # Add noise to degrade predictions
    rng = np.random.default_rng(42)
    noise: npt.NDArray[np.float64] = rng.standard_normal(eval_len).astype(np.float64) * degradation
    degraded_confs: npt.NDArray[np.float64] = np.clip(confs_eval + noise, 0.0, 1.0).astype(np.float64)
    score = _score_params_on_split(
        directions=dirs_eval,
        confidences=degraded_confs,
        forward_returns=returns_eval,
        stop_mult=float(params.get("stop_atr_mult", 1.5)),
        trail_mult=float(params.get("trail_atr_mult", 3.0)),
    )
    return score["sharpe"]


def run_final_oos(
    stage1: Stage1Result,
    splits: DataSplits,
    feature_cols: list[str],
    stage2_params: dict[str, Any] | None = None,
) -> float:
    """One-shot evaluation on held-out final OOS using frozen stage-2 params."""
    if stage1.direction_model is None:
        return 0.0

    from src.prediction.features import prepare_xy

    x_oos, _ = prepare_xy(splits.final_oos, feature_cols)
    dirs, confs = stage1.direction_model.predict_direction(x_oos)
    forward_returns = _extract_forward_returns(splits.final_oos)
    eval_len = min(len(dirs), len(confs), len(forward_returns))
    if eval_len <= 1:
        return 0.0
    params = stage2_params or {"stop_atr_mult": 1.5, "trail_atr_mult": 3.0}
    score = _score_params_on_split(
        directions=dirs[:eval_len],
        confidences=confs[:eval_len],
        forward_returns=forward_returns[:eval_len],
        stop_mult=float(params.get("stop_atr_mult", 1.5)),
        trail_mult=float(params.get("trail_atr_mult", 3.0)),
    )
    return score["sharpe"]


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
    rob_sharpe = run_robustness_test(s1, splits, feature_cols, s2.best_params)

    logger.info("Running final OOS evaluation")
    oos_sharpe = run_final_oos(s1, splits, feature_cols, s2.best_params)

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


def _extract_forward_returns(frame: Any) -> npt.NDArray[np.float64]:
    if "forward_return" in frame.columns:
        return frame["forward_return"].to_numpy().astype(np.float64)
    closes = frame["close"].to_numpy().astype(np.float64)
    if len(closes) <= 1:
        return np.array([], dtype=np.float64)
    return np.diff(closes) / closes[:-1]


def _score_params_on_split(
    directions: npt.NDArray[np.float64],
    confidences: npt.NDArray[np.float64],
    forward_returns: npt.NDArray[np.float64],
    stop_mult: float,
    trail_mult: float,
) -> dict[str, float]:
    exposures = np.clip(directions * confidences, -1.0, 1.0).astype(np.float64)
    gross_returns = exposures * forward_returns
    vol_scale = max(float(np.std(forward_returns)), 1e-6)
    stop_cap = vol_scale * max(stop_mult, 0.1)
    trail_cap = vol_scale * max(trail_mult, 0.1)
    capped_returns = np.clip(gross_returns, -stop_cap, trail_cap)
    turnover = np.abs(np.diff(np.concatenate((np.array([0.0]), exposures))))
    net_returns = capped_returns - (turnover * 0.0002)
    sharpe = _annualized_sharpe(net_returns)
    trade_mask = np.abs(exposures) > 1e-6
    trade_count = float(np.count_nonzero(trade_mask))
    expectancy = float(np.mean(net_returns[trade_mask])) if np.any(trade_mask) else 0.0
    net_return = float(np.sum(net_returns))
    return {
        "sharpe": sharpe,
        "trade_count": trade_count,
        "expectancy": expectancy,
        "net_return": net_return,
    }


def _annualized_sharpe(returns: npt.NDArray[np.float64]) -> float:
    if len(returns) == 0:
        return 0.0
    mean_ret = float(np.mean(returns))
    std_ret = float(np.std(returns))
    if std_ret < 1e-10:
        return 0.0
    return float(mean_ret / std_ret * np.sqrt(252.0))
