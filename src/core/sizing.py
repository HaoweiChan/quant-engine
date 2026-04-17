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

Portfolio-level extensions
--------------------------
PortfolioSizer supports two optional portfolio-level modes on top of the
baseline per-strategy risk sizing:

  - ``SizingMode.KELLY_PORTFOLIO``  — per-strategy size multiplied by a
    Kelly weight (``SizingConfig.kelly_weights[slug]``). Falls back to
    RISK_STOP when the weight is missing/non-positive.
  - Shared margin pool (via ``set_open_exposure``) — enforces a global
    ``portfolio_margin_cap`` so the combined margin used across all
    strategies never exceeds ``equity × portfolio_margin_cap``. Backward
    compatible: when ``set_open_exposure`` is never called, behaviour
    matches the legacy per-strategy margin cap.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class SizingMode(StrEnum):
    """Portfolio-level sizing mode for PortfolioSizer.

    ``RISK_STOP`` is the legacy default — sizes by stop-distance risk budget.
    ``KELLY_PORTFOLIO`` scales the risk-based size by a per-strategy Kelly
    weight supplied in ``SizingConfig.kelly_weights``.
    ``MARGIN_FRACTION`` is reserved for future extension.
    """

    RISK_STOP = "risk_stop"
    MARGIN_FRACTION = "margin_fraction"
    KELLY_PORTFOLIO = "kelly_portfolio"


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

    Portfolio-level fields:
      mode: Sizing mode (RISK_STOP default).
      portfolio_margin_cap: Global margin ceiling across all strategies
          sharing the pool (enforced when ``set_open_exposure`` is called).
      kelly_weights: Optional per-strategy-slug Kelly weight, used only
          when ``mode == KELLY_PORTFOLIO``.
    """
    risk_per_trade: float = 0.02
    margin_cap: float = 0.50
    max_lots: int = 10
    min_lots: int = 1
    use_kelly: bool = False
    kelly_fraction: float = 0.25
    # Portfolio-level extensions
    mode: SizingMode = SizingMode.RISK_STOP
    portfolio_margin_cap: float = 0.65
    kelly_weights: dict[str, float] | None = None


@dataclass
class SizingResult:
    """Output from PortfolioSizer.size()."""
    lots: float
    method: str
    caps_applied: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


def _base_position_lots(positions: list) -> float:
    """Return positions[0].lots (the base position) or 0.0 if empty.

    Use this when resolving AddDecision multipliers — NEVER use positions[-1]
    because after an overlay add, positions[-1] is the overlay itself.
    """
    return positions[0].lots if positions else 0.0


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

    Shared margin pool:
        When a LivePipelineManager drives multiple runners against a single
        account, call ``set_open_exposure({slug: margin_used})`` before each
        sizing request. The sizer will scale new orders down so the combined
        book never exceeds ``equity × portfolio_margin_cap``.
    """

    def __init__(self, config: SizingConfig | None = None) -> None:
        self._config = config or SizingConfig()
        # Per-strategy open margin (NTD); populated via set_open_exposure.
        self._open_exposure: dict[str, float] = {}

    @property
    def config(self) -> SizingConfig:
        return self._config

    # ---------------------------------------------- shared-pool exposure API
    def set_open_exposure(
        self,
        exposure_by_strategy: dict[str, float],
    ) -> None:
        """Record per-strategy margin-used for shared-pool enforcement.

        Values are in NTD (margin consumed by each strategy). The
        LivePipelineManager should aggregate across all active runners and
        call this before invoking ``size_entry`` / ``size_add``.
        """
        self._open_exposure = dict(exposure_by_strategy)

    @property
    def open_exposure(self) -> dict[str, float]:
        return dict(self._open_exposure)

    # ----------------------------------------------------------- size_entry
    def size_entry(
        self,
        equity: float,
        stop_distance: float,
        point_value: float,
        margin_per_unit: float,
        strategy_slug: str | None = None,
    ) -> SizingResult:
        """Compute lots for an entry order.

        Uses stop-distance risk sizing when stop_distance > 0,
        falls back to margin-based sizing otherwise.

        When ``config.mode == KELLY_PORTFOLIO`` and ``config.kelly_weights``
        has an entry for ``strategy_slug``, the risk-sized lots are
        multiplied by that Kelly weight (falls back to RISK_STOP if missing
        or non-positive).

        When ``set_open_exposure`` has been called, the shared-pool cap
        scales the order down so total margin does not breach
        ``equity × config.portfolio_margin_cap``.
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

        # Per-strategy margin cap (always applied — unchanged legacy behaviour)
        if margin_per_unit > 0:
            max_by_margin = (equity * cfg.margin_cap) / margin_per_unit
            raw_lots.append(max_by_margin)
            if len(caps) == 0 or max_by_margin < min(raw_lots[:-1], default=float("inf")):
                caps.append("margin_cap")

        if not raw_lots:
            return SizingResult(lots=0, method="none", caps_applied=["no_data"])

        base_lots = min(raw_lots)

        # --------------------------- Kelly scaling (portfolio-level mode)
        kelly_info: dict[str, Any] | None = None
        if cfg.mode == SizingMode.KELLY_PORTFOLIO:
            base_lots, kelly_cap, kelly_info = self._apply_kelly_scale(
                base_lots, strategy_slug,
            )
            if kelly_cap is not None:
                caps.append(kelly_cap)

        # ---------------------------------------- shared-pool enforcement
        portfolio_cap: str | None = None
        if self._open_exposure and margin_per_unit > 0:
            base_lots, portfolio_cap = self._apply_portfolio_cap(
                base_lots, margin_per_unit, equity, strategy_slug,
            )
            if portfolio_cap is not None:
                caps.append(portfolio_cap)

        # ----------------------------------------------- floor + max_lots
        lots = math.floor(base_lots)
        if lots > cfg.max_lots:
            lots = cfg.max_lots
            caps.append("max_lots")
        lots = max(lots, 0)
        if lots < cfg.min_lots:
            lots = 0
            caps.append("below_min")

        method = (
            "kelly_portfolio"
            if cfg.mode == SizingMode.KELLY_PORTFOLIO
            else ("risk" if stop_distance > 0 else "margin_fraction")
        )
        details: dict[str, Any] = {
            "equity": equity,
            "stop_distance": stop_distance,
            "point_value": point_value,
            "margin_per_unit": margin_per_unit,
            "risk_per_trade": cfg.risk_per_trade,
            "raw_lots": [round(x, 2) for x in raw_lots],
            "final_lots": lots,
        }
        if kelly_info is not None:
            details["kelly"] = kelly_info
        if self._open_exposure:
            details["open_exposure"] = dict(self._open_exposure)
            details["portfolio_margin_cap"] = cfg.portfolio_margin_cap
        logger.debug(
            "portfolio_sizer",
            method=method,
            lots=lots,
            equity=equity,
            stop_dist=round(stop_distance, 1),
            strategy_slug=strategy_slug,
        )
        return SizingResult(
            lots=float(lots),
            method=method,
            caps_applied=caps,
            details=details,
        )

    # ------------------------------------------------------------- size_add
    def size_add(
        self,
        equity: float,
        existing_margin_used: float,
        margin_per_unit: float,
        requested_lots: float,
        base_lots: float = 0.0,
        is_multiplier: bool = False,
        strategy_slug: str | None = None,
    ) -> SizingResult:
        """Compute lots for a pyramid add order.

        Caps at available margin headroom while respecting max_lots.

        If ``is_multiplier`` is True and ``base_lots > 0``, ``requested_lots``
        is interpreted as a ratio of the base position's lots rather than an
        absolute contract count.

        When ``set_open_exposure`` has been called, the shared-pool cap is
        applied on top of the per-strategy margin headroom.
        """
        cfg = self._config
        resolved_requested = requested_lots
        if is_multiplier and base_lots > 0:
            resolved_requested = requested_lots * base_lots
        available = equity * cfg.margin_cap - existing_margin_used
        caps: list[str] = []
        if margin_per_unit <= 0 or available <= 0:
            return SizingResult(lots=0, method="add", caps_applied=["no_margin"])
        max_add = math.floor(available / margin_per_unit)
        lots = min(resolved_requested, max_add)
        if lots < resolved_requested:
            caps.append("margin_headroom")

        # Shared-pool cap: subtract all other strategies' exposure too.
        portfolio_cap: str | None = None
        if self._open_exposure and margin_per_unit > 0:
            lots, portfolio_cap = self._apply_portfolio_cap(
                lots, margin_per_unit, equity, strategy_slug,
            )
            if portfolio_cap is not None:
                caps.append(portfolio_cap)

        lots = min(lots, cfg.max_lots)
        lots = max(lots, 0)
        if lots < cfg.min_lots:
            lots = 0
            caps.append("below_min")
        return SizingResult(
            lots=float(math.floor(lots)),
            method="add",
            caps_applied=caps,
            details={
                "available_margin": available,
                "max_add": max_add,
                "is_multiplier": is_multiplier,
                "base_lots": base_lots,
                "resolved_requested": resolved_requested,
                "strategy_slug": strategy_slug,
                "portfolio_cap_applied": portfolio_cap,
            },
        )

    # ---------------------------------------------------------- internals
    def _apply_kelly_scale(
        self,
        base_lots: float,
        strategy_slug: str | None,
    ) -> tuple[float, str | None, dict[str, Any]]:
        """Scale ``base_lots`` by the per-strategy Kelly weight.

        Returns (scaled_lots, cap_label, info_dict). Falls back silently to
        the input lots when kelly_weights is missing an entry.
        """
        cfg = self._config
        info: dict[str, Any] = {
            "mode": cfg.mode.value,
            "strategy_slug": strategy_slug,
        }
        weights = cfg.kelly_weights or {}
        if strategy_slug is None or strategy_slug not in weights:
            info["reason"] = "kelly_fallback_no_weight"
            return base_lots, "kelly_fallback", info
        weight = float(weights[strategy_slug])
        info["weight"] = weight
        if weight <= 0:
            info["reason"] = "kelly_zero_weight"
            return 0.0, "kelly_zero_weight", info
        scaled = base_lots * weight
        info["scaled_lots"] = scaled
        return scaled, "kelly_scaled", info

    def _apply_portfolio_cap(
        self,
        lots: float,
        margin_per_unit: float,
        equity: float,
        strategy_slug: str | None,
    ) -> tuple[float, str | None]:
        """Enforce the shared-pool ``portfolio_margin_cap``.

        Scales ``lots`` down so ``other_strategies_margin + lots*margin_per_unit``
        never exceeds ``equity × portfolio_margin_cap``. Any margin currently
        attributed to ``strategy_slug`` is excluded (we're pricing a NEW order
        for that strategy).
        """
        cfg = self._config
        if margin_per_unit <= 0 or not self._open_exposure:
            return lots, None
        existing = sum(
            m for s, m in self._open_exposure.items()
            if strategy_slug is None or s != strategy_slug
        )
        cap_total = equity * cfg.portfolio_margin_cap
        new_order_margin = lots * margin_per_unit
        if existing + new_order_margin <= cap_total + 1e-6:
            return lots, None
        available = cap_total - existing
        if available <= 0:
            return 0.0, "portfolio_cap_exhausted"
        new_lots = math.floor(available / margin_per_unit)
        return float(max(new_lots, 0)), "portfolio_cap"
