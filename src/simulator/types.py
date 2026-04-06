"""Simulator result types and configuration dataclasses."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import polars as pl


@dataclass
class Fill:
    order_type: str
    side: str
    symbol: str
    lots: float
    fill_price: float
    slippage: float
    timestamp: datetime
    reason: str
    market_impact: float = 0.0
    spread_cost: float = 0.0
    commission_cost: float = 0.0
    latency_ms: float = 0.0
    fill_qty: float = 0.0
    remaining_qty: float = 0.0
    is_partial: bool = False


@dataclass
class ImpactReport:
    """Naive vs realistic PnL comparison from market impact simulation."""
    naive_pnl: float
    realistic_pnl: float
    pnl_ratio: float
    total_market_impact: float
    total_spread_cost: float
    total_commission_cost: float
    avg_latency_ms: float
    partial_fill_count: int
    per_trade_impact_breakdown: list[dict[str, float]]


@dataclass
class BacktestResult:
    equity_curve: list[float]
    drawdown_series: list[float]
    trade_log: list[Fill]
    metrics: dict[str, float]
    monthly_returns: dict[str, float]
    yearly_returns: dict[str, float]
    impact_report: ImpactReport | None = None
    indicator_series: dict[str, list[float | None]] = field(default_factory=dict)
    indicator_meta: dict[str, dict] = field(default_factory=dict)


@dataclass
class OptimizerResult:
    """Result of a strategy parameter optimization run (grid or random search)."""
    trials: pl.DataFrame
    best_params: dict[str, Any]
    best_is_result: BacktestResult
    best_oos_result: BacktestResult | None
    warnings: list[str] = field(default_factory=list)
    objective_name: str = "sharpe"
    objective_direction: str = "maximize"
    disqualified_trials: int = 0
    gate_results: dict[str, bool] = field(default_factory=dict)
    gate_details: dict[str, float | str] = field(default_factory=dict)
    promotable: bool = False
    mode: str = "research"


@dataclass
class WindowResult:
    """Per-window result from a walk-forward run."""
    window_idx: int
    is_bars: int
    oos_bars: int
    best_params: dict[str, Any]
    is_result: BacktestResult
    oos_result: BacktestResult
    low_trade_count: bool = False


@dataclass
class WalkForwardResult:
    """Aggregated result of a walk-forward optimization run."""
    windows: list[WindowResult]
    efficiency: float
    combined_oos_metrics: dict[str, float]


@dataclass
class MonteCarloResult:
    terminal_pnl_distribution: list[float]
    percentiles: dict[str, float]
    win_rate: float
    max_drawdown_distribution: list[float]
    sharpe_distribution: list[float]
    ruin_probability: float


@dataclass
class StressScenario:
    name: str
    magnitude: float = 0.10
    duration: int = 20
    recovery: int = 10


@dataclass
class StressResult:
    scenario_name: str
    final_pnl: float
    max_drawdown: float
    circuit_breaker_triggered: bool
    stops_triggered: list[str]
    equity_curve: list[float]


@dataclass
class PathConfig:
    drift: float = 0.0
    volatility: float = 0.02
    garch_omega: float = 0.0
    garch_alpha: float = 0.0
    garch_beta: float = 0.0
    student_t_df: float = 0.0
    jump_intensity: float = 0.0
    jump_mean: float = 0.0
    jump_std: float = 0.0
    ou_theta: float = 0.0
    ou_mu: float = 0.0
    ou_sigma: float = 0.0
    n_bars: int = 252
    start_price: float = 20000.0
    seed: int | None = None


PRESETS: dict[str, PathConfig] = {
    "strong_bull": PathConfig(drift=0.001, volatility=0.015),
    "gradual_bull": PathConfig(drift=0.0003, volatility=0.01),
    "bull_with_correction": PathConfig(
        drift=0.0005, volatility=0.02,
        jump_intensity=0.01, jump_mean=-0.05, jump_std=0.02,
    ),
    "sideways": PathConfig(
        drift=0.0, volatility=0.01,
        ou_theta=0.1, ou_mu=0.0, ou_sigma=0.005,
    ),
    "bear": PathConfig(drift=-0.0005, volatility=0.02),
    "volatile_bull": PathConfig(
        drift=0.0005, volatility=0.03,
        garch_omega=0.00001, garch_alpha=0.08, garch_beta=0.89,
    ),
    "flash_crash": PathConfig(
        drift=0.0002, volatility=0.015,
        jump_intensity=0.005, jump_mean=-0.10, jump_std=0.03,
    ),
}
