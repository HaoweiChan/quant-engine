"""Contract-agnostic position sizing utilities.

Three layers:
  - compute_risk_lots(): For strategies with meaningful stops (intraday, swing).
    Sizes by stop-distance risk, capped by max_loss and margin.
  - compute_margin_lots(): For buy-and-hold / permanent positions where stops
    are nominal. Sizes by margin deployment fraction of equity.
  - PortfolioSizer: Live-pipeline sizing layer that sits between strategy signals
    and order execution. Overrides strategy-level lots using the runner's current
    equity budget, stop distance from the strategy's EntryDecision, and
    per-session risk parameters. Strategies decide WHEN and WHERE (direction, stop);
    PortfolioSizer decides HOW MUCH.

Both compute_* functions are contract-agnostic: MTX naturally gets ~4x more lots
than TX for the same equity because margin_per_unit is ~4x smaller.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def compute_risk_lots(
    equity: float,
    stop_distance: float,
    point_value: float,
    margin_per_unit: float,
    max_equity_risk_pct: float = 0.02,
    max_loss: float | None = None,
    margin_limit: float = 0.50,
    min_lot: float = 1.0,
) -> float:
    """Compute lots from stop-distance risk budget. Contract-agnostic.

    For strategies with meaningful stops. Applies three independent caps:
      1. Equity risk cap: (equity * risk_pct) / (stop_distance * point_value)
      2. Max loss cap: max_loss / (stop_distance * point_value)
      3. Margin cap: (equity * margin_limit) / margin_per_unit

    Returns 0.0 if the result is below min_lot.
    """
    if equity <= 0 or point_value <= 0 or margin_per_unit <= 0:
        return 0.0

    risk_per_contract = stop_distance * point_value
    caps: list[float] = []

    # 1. Equity risk cap
    if risk_per_contract > 0:
        caps.append((equity * max_equity_risk_pct) / risk_per_contract)

    # 2. Max loss cap
    if max_loss is not None and risk_per_contract > 0:
        caps.append(max_loss / risk_per_contract)

    # 3. Margin cap
    caps.append((equity * margin_limit) / margin_per_unit)

    if not caps:
        return 0.0

    lots = math.floor(min(caps))
    return float(lots) if lots >= min_lot else 0.0


def compute_margin_lots(
    equity: float,
    margin_per_unit: float,
    margin_fraction: float = 0.10,
    min_lot: float = 1.0,
) -> float:
    """Compute lots from margin deployment. Contract-agnostic.

    For buy-and-hold / permanent positions where stop-based risk sizing
    is not meaningful. Deploys a fraction of equity as margin.

    Example with margin_fraction=0.10 (10% of equity):
      TX:  2M * 0.10 / 184,000 = 1 lot
      MTX: 2M * 0.10 / 46,000  = 4 lots  (equivalent notional)

    Returns 0.0 if the result is below min_lot.
    """
    if equity <= 0 or margin_per_unit <= 0:
        return 0.0

    lots = math.floor(equity * margin_fraction / margin_per_unit)
    return float(lots) if lots >= min_lot else 0.0


@dataclass
class SizingConfig:
    """Per-session sizing parameters set at the portfolio/account level.

    Strategies decide WHEN and WHERE; SizingConfig decides HOW MUCH.
    """
    risk_per_trade: float = 0.02
    margin_cap: float = 0.50
    max_lots: int = 10
    min_lots: int = 1
    use_kelly: bool = False
    kelly_fraction: float = 0.25


@dataclass
class SizingResult:
    """Output from PortfolioSizer.size()."""
    lots: float
    method: str
    caps_applied: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


class PortfolioSizer:
    """Centralised sizing layer for the live pipeline.

    Sits between strategy signal and order execution in LiveStrategyRunner.
    Intercepts Orders from the PositionEngine and adjusts lots based on the
    runner's real-time equity, margin, and per-session SizingConfig.

    Usage in LiveStrategyRunner.on_bar_complete():
        orders = self._engine.on_snapshot(snapshot, account=account)
        for order in orders:
            if order.reason == "entry":
                result = self._sizer.size_entry(...)
                order.lots = result.lots
    """

    def __init__(self, config: SizingConfig | None = None) -> None:
        self._config = config or SizingConfig()

    @property
    def config(self) -> SizingConfig:
        return self._config

    def size_entry(
        self,
        equity: float,
        stop_distance: float,
        point_value: float,
        margin_per_unit: float,
    ) -> SizingResult:
        """Compute lots for an entry order.

        Uses stop-distance risk sizing when stop_distance > 0,
        falls back to margin-based sizing otherwise.
        """
        cfg = self._config
        caps: list[str] = []
        raw_lots: list[float] = []

        # Risk-based sizing (primary method when stop exists)
        if stop_distance > 0 and point_value > 0:
            risk_per_contract = stop_distance * point_value
            risk_lots = (equity * cfg.risk_per_trade) / risk_per_contract
            raw_lots.append(risk_lots)
            caps.append("risk")
        else:
            # Margin-fraction fallback for strategies without meaningful stops
            if margin_per_unit > 0:
                margin_lots = (equity * cfg.margin_cap * 0.25) / margin_per_unit
                raw_lots.append(margin_lots)
                caps.append("margin_fraction")

        # Margin cap (always applied)
        if margin_per_unit > 0:
            max_by_margin = (equity * cfg.margin_cap) / margin_per_unit
            raw_lots.append(max_by_margin)
            if len(caps) == 0 or max_by_margin < min(raw_lots[:-1], default=float("inf")):
                caps.append("margin_cap")

        if not raw_lots:
            return SizingResult(lots=0, method="none", caps_applied=["no_data"])

        lots = math.floor(min(raw_lots))
        lots = min(lots, cfg.max_lots)
        if lots > cfg.max_lots:
            caps.append("max_lots")
        lots = max(lots, 0)
        if lots < cfg.min_lots:
            lots = 0
            caps.append("below_min")

        method = "risk" if stop_distance > 0 else "margin_fraction"
        details = {
            "equity": equity,
            "stop_distance": stop_distance,
            "point_value": point_value,
            "margin_per_unit": margin_per_unit,
            "risk_per_trade": cfg.risk_per_trade,
            "raw_lots": [round(x, 2) for x in raw_lots],
            "final_lots": lots,
        }
        logger.debug(
            "portfolio_sizer",
            method=method,
            lots=lots,
            equity=equity,
            stop_dist=round(stop_distance, 1),
        )
        return SizingResult(lots=float(lots), method=method, caps_applied=caps, details=details)

    def size_add(
        self,
        equity: float,
        existing_margin_used: float,
        margin_per_unit: float,
        requested_lots: float,
    ) -> SizingResult:
        """Compute lots for a pyramid add order.

        Caps at available margin headroom while respecting max_lots.
        """
        cfg = self._config
        available = equity * cfg.margin_cap - existing_margin_used
        caps: list[str] = []
        if margin_per_unit <= 0 or available <= 0:
            return SizingResult(lots=0, method="add", caps_applied=["no_margin"])
        max_add = math.floor(available / margin_per_unit)
        lots = min(requested_lots, max_add)
        if lots > requested_lots:
            caps.append("margin_headroom")
        lots = min(lots, cfg.max_lots)
        lots = max(lots, 0)
        if lots < cfg.min_lots:
            lots = 0
            caps.append("below_min")
        return SizingResult(
            lots=float(math.floor(lots)),
            method="add",
            caps_applied=caps,
            details={"available_margin": available, "max_add": max_add},
        )
