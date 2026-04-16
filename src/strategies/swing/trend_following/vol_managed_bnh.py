"""Vol-Managed B&H — Pure Signal Emitter.

Base lot (pyramid_level=0) held permanently -> tracks B&H exactly.
Overlay sized by inverse realized vol as a MULTIPLIER of base position.
PortfolioSizer translates multiplier x base_lots into contracts.

This strategy is a pure signal emitter: no equity inspection, no contract
math, no sizing. All contract-count logic lives in PortfolioSizer.

Alpha source: conditioning on second moment (vol) rather than first moment.
Low-vol periods get more overlay; high-vol periods reduce.

Indicators sourced from src.indicators: RealizedVol, DDCircuitBreaker,
DailyCloseStream, SMA, SmoothedATR.
"""
from __future__ import annotations

import warnings
from collections import deque
from datetime import datetime
from typing import TYPE_CHECKING

import structlog

from src.core.policies import AddPolicy, EntryPolicy, StopPolicy
from src.core.types import (
    METADATA_EXPOSURE_MULTIPLIER,
    AccountState,
    AddDecision,
    EngineConfig,
    EngineState,
    EntryDecision,
    MarketSignal,
    MarketSnapshot,
    Position,
    PyramidConfig,
)
from src.indicators import (
    SMA,
    DailyCloseStream,
    DDCircuitBreaker,
    RealizedVol,
    SmoothedATR,
    compose_param_schema,
)
from src.strategies import (
    HoldingPeriod,
    SignalTimeframe,
    StopArchitecture,
    StrategyCategory,
)

if TYPE_CHECKING:
    from src.core.position_engine import PositionEngine

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Structural constants — not tunable. If you ever need to tune these,
# promote back to PARAM_SCHEMA and justify with an ablation study.
# ---------------------------------------------------------------------------

_OVERLAY_MAX_MULTIPLIER = 2.0
_STOP_ATR_MULT = 15.0  # nominal; base lot protected by EngineConfig.min_hold_lots=1.0

# Deprecated kwargs accepted silently (with DeprecationWarning) from stale
# configs / registry entries for one release window.
_DEPRECATED_KWARGS = frozenset({
    "trail_atr_mult",
    "trail_lookback",
    "max_levels",
    "add_spacing_atr",
    "gamma",
    "margin_cap_pct",
    "reentry_cooldown",
    "initial_capital",
    "boost_sma_fast_days",
    "boost_lots",
    "vol_overlay_max_lots",
    "stop_atr_mult",
})

# ---------------------------------------------------------------------------
# Parameter schema — composed from centralized indicator PARAM_SPECs
# ---------------------------------------------------------------------------

_INDICATOR_PARAMS = compose_param_schema({
    "vol_lookback_days": (RealizedVol, "period"),
    "trend_sma_days": (SMA, "period"),
    "dd_breaker_pct": (DDCircuitBreaker, "breaker_pct"),
    "dd_reentry_pct": (DDCircuitBreaker, "reentry_pct"),
})

# Override defaults to match validated active params (vol_managed_bnh.toml)
_INDICATOR_PARAMS["vol_lookback_days"]["default"] = 10
_INDICATOR_PARAMS["trend_sma_days"]["default"] = 20
_INDICATOR_PARAMS["dd_breaker_pct"]["default"] = 0.15
_INDICATOR_PARAMS["dd_reentry_pct"]["default"] = 0.05

_STRATEGY_PARAMS: dict[str, dict] = {
    "vol_target_annual": {
        "type": "float", "default": 0.20, "min": 0.05, "max": 0.40,
        "description": "Target annualized vol for overlay sizing (0.20 = 20%).",
    },
}

PARAM_SCHEMA: dict[str, dict] = {**_INDICATOR_PARAMS, **_STRATEGY_PARAMS}

STRATEGY_META: dict = {
    "category": StrategyCategory.TREND_FOLLOWING,
    "signal_timeframe": SignalTimeframe.FIVE_MIN,
    "holding_period": HoldingPeriod.SWING,
    "stop_architecture": StopArchitecture.SWING,
    "expected_duration_minutes": (60 * 24 * 30, 60 * 24 * 180),
    "tradeable_sessions": ["day", "night"],
    "description": "B&H base + inverse-vol overlay (pure signal emitter).",
}


# ---------------------------------------------------------------------------
# _OverlayHub — centralized state for the inverse-vol overlay system
# ---------------------------------------------------------------------------

class _OverlayHub:
    """Centralized state for the inverse-vol overlay, fed one 5m bar per tick.

    Emits a RAW multiplier in [0, _OVERLAY_MAX_MULTIPLIER] via
    ``desired_overlay_lots``. PortfolioSizer translates it into contracts.
    """

    def __init__(
        self,
        vol_lookback_days: int,
        vol_target_annual: float,
        trend_sma_days: int,
        dd_breaker_pct: float,
        dd_reentry_pct: float,
    ) -> None:
        self._vol_target = vol_target_annual

        self._daily_stream = DailyCloseStream()
        self._rv = RealizedVol(period=vol_lookback_days)
        self._trend_sma = SMA(period=trend_sma_days)
        self._dd_breaker = DDCircuitBreaker(
            breaker_pct=dd_breaker_pct, reentry_pct=dd_reentry_pct,
        )
        self.smoothed_atr = SmoothedATR(period=14)

        self._prev_daily_close: float | None = None
        self._last_ts: datetime | None = None
        # Daily overlay multiplier persists between daily-close events.
        self._daily_overlay_lots: float = 0.0

        # Public per-tick state; set by entry policy / tick().
        # Raw multiplier; PortfolioSizer applies base_lots and margin caps.
        self.desired_overlay_lots: float = 0.0

    # Public passthroughs for indicator inspection.
    @property
    def dd_breaker(self) -> DDCircuitBreaker:
        return self._dd_breaker

    @property
    def rv_value(self) -> float | None:
        return self._rv.value

    @property
    def trend_sma_value(self) -> float | None:
        return self._trend_sma.value

    def tick(self, price: float, raw_atr: float, timestamp: datetime) -> None:
        """Update all state from one 5m bar (idempotent on timestamp)."""
        if timestamp == self._last_ts:
            return
        self._last_ts = timestamp

        if raw_atr > 0:
            self.smoothed_atr.update(raw_atr)

        below_sma = (
            self._trend_sma.value is not None and price < self._trend_sma.value
        )
        self._dd_breaker.update(price, below_sma)

        daily_close = self._daily_stream.update(price, timestamp)
        if daily_close is not None:
            self._process_daily_close(daily_close)

        if self._dd_breaker.tripped:
            self.desired_overlay_lots = 0.0
        else:
            self.desired_overlay_lots = self._daily_overlay_lots

    def _process_daily_close(self, close: float) -> None:
        if self._prev_daily_close is not None:
            self._rv.update(self._prev_daily_close, close)
        self._prev_daily_close = close

        self._trend_sma.update(close)
        self._recompute_daily_overlay(close)

    def _recompute_daily_overlay(self, daily_close: float) -> None:
        if not self._rv.ready or self._rv.value is None:
            self._daily_overlay_lots = 0.0
            return

        # Inverse-vol sizing capped at max multiplier, with rv floor to avoid blow-up.
        overlay_lots = min(
            self._vol_target / max(self._rv.value, 0.01),
            _OVERLAY_MAX_MULTIPLIER,
        )

        # Trend gate: no overlay when price closed below trend SMA.
        trend_val = self._trend_sma.value
        if trend_val is not None and daily_close < trend_val:
            overlay_lots = 0.0

        self._daily_overlay_lots = overlay_lots


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------

class InverseVolEntryPolicy(EntryPolicy):
    """Emit base entry on first valid bar. Tick overlay hub.

    Pure signal emitter: emits ``lots=1.0`` as a hint. PortfolioSizer resolves
    to absolute contract count via stop-distance risk sizing.
    """

    def __init__(self, hub: _OverlayHub) -> None:
        self.hub = hub

    def should_enter(
        self,
        snapshot: MarketSnapshot,
        signal: MarketSignal | None,
        engine_state: EngineState,
        account: AccountState | None = None,
    ) -> EntryDecision | None:
        self.hub.tick(snapshot.price, snapshot.atr.get("daily", 0.0), snapshot.timestamp)

        if engine_state.mode in ("halted", "rule_only") or engine_state.positions:
            return None

        atr = self.hub.smoothed_atr.value
        if atr is None or atr <= 0:
            return None

        stop_distance = _STOP_ATR_MULT * atr
        return EntryDecision(
            lots=1.0,
            contract_type="large",
            initial_stop=snapshot.price - stop_distance,
            direction="long",
            metadata={
                "rv": self.hub.rv_value,
                "desired_overlay": self.hub.desired_overlay_lots,
                "sizing_mode": "base",
            },
        )

    def snapshot(self) -> dict[str, float | None]:
        hub = self.hub
        return {
            "realized_vol": hub.rv_value,
            "trend_sma": hub.trend_sma_value,
            "desired_overlay": hub.desired_overlay_lots,
            "dd_pct": hub.dd_breaker.current_dd * 100,
            "dd_tripped": 1.0 if hub.dd_breaker.tripped else 0.0,
        }

    def indicator_meta(self) -> dict[str, dict]:
        return {
            "realized_vol": {"panel": "sub", "color": "#FF6B6B", "label": "RV (ann.)"},
            "trend_sma": {"panel": "price", "color": "#4ECDC4", "label": "SMA(trend)"},
            "desired_overlay": {"panel": "sub", "color": "#FFEAA7", "label": "Overlay mult"},
            "dd_pct": {"panel": "sub", "color": "#E17055", "label": "DD%"},
            "dd_tripped": {"panel": "sub", "color": "#D63031", "label": "DD tripped"},
        }


class InverseVolAddPolicy(AddPolicy):
    """Emit overlay multiplier as AddDecision when hub says so.

    ``AddDecision.lots`` is the raw multiplier in [0, _OVERLAY_MAX_MULTIPLIER],
    NOT a contract count. PortfolioSizer resolves it to absolute contracts via
    ``metadata[METADATA_EXPOSURE_MULTIPLIER]=True``.
    """

    def __init__(self, hub: _OverlayHub) -> None:
        self._hub = hub

    def should_add(
        self,
        snapshot: MarketSnapshot,
        signal: MarketSignal | None,
        engine_state: EngineState,
    ) -> AddDecision | None:
        if engine_state.mode == "halted" or not engine_state.positions:
            return None
        if engine_state.pyramid_level >= 2:  # single overlay level — prevent compounding
            return None

        self._hub.tick(snapshot.price, snapshot.atr.get("daily", 0.0), snapshot.timestamp)
        if self._hub.desired_overlay_lots <= 0:
            return None

        return AddDecision(
            lots=self._hub.desired_overlay_lots,
            contract_type="large",
            move_existing_to_breakeven=False,
            metadata={
                METADATA_EXPOSURE_MULTIPLIER: True,
                "rv": self._hub.rv_value,
            },
        )


class InverseVolStopPolicy(StopPolicy):
    """Base lot never stops; overlay exits on DD breaker or trend break."""

    def __init__(self, hub: _OverlayHub, config: PyramidConfig) -> None:
        self._hub = hub
        self._config = config

    def initial_stop(
        self, entry_price: float, direction: str, snapshot: MarketSnapshot,
    ) -> float:
        daily_atr = snapshot.atr["daily"]
        distance = self._config.stop_atr_mult * daily_atr
        return entry_price - distance if direction == "long" else entry_price + distance

    def update_stop(
        self,
        position: Position,
        snapshot: MarketSnapshot,
        high_history: deque[float],
    ) -> float:
        self._hub.tick(snapshot.price, snapshot.atr.get("daily", 0.0), snapshot.timestamp)

        # Base lot never moves stop. Overlay exits (ratchet stop to price) when
        # desired overlay drops to 0 (DD breaker tripped, trend gate failed, or vol spike).
        if position.pyramid_level == 0:
            return position.stop_level
        if self._hub.desired_overlay_lots <= 0:
            return snapshot.price
        return position.stop_level


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_vol_managed_bnh_engine(
    max_loss: float = 500_000.0,
    vol_lookback_days: int = 10,
    trend_sma_days: int = 20,
    dd_breaker_pct: float = 0.15,
    dd_reentry_pct: float = 0.05,
    vol_target_annual: float = 0.20,
    **kwargs,
) -> PositionEngine:
    """Build a PositionEngine for vol-managed B&H (inverse-vol overlay).

    Pure signal emitter: no contract-count math lives here. PortfolioSizer
    (attached by BacktestRunner / LiveStrategyRunner) owns sizing.

    Unknown kwargs raise TypeError. Deprecated kwargs from the pre-refactor
    schema are accepted silently (with DeprecationWarning) for one release
    window so stale registry entries do not crash the factory.
    """
    unknown = set(kwargs) - _DEPRECATED_KWARGS
    if unknown:
        raise TypeError(
            f"create_vol_managed_bnh_engine: unknown kwargs: {sorted(unknown)}"
        )
    if kwargs:
        deprecated_used = set(kwargs) & _DEPRECATED_KWARGS
        warnings.warn(
            f"vol_managed_bnh deprecated kwargs ignored: {sorted(deprecated_used)}",
            DeprecationWarning,
            stacklevel=2,
        )

    from src.core.position_engine import PositionEngine

    # Structural pyramid config (not tuned — encodes 2-level B&H design).
    config = PyramidConfig(
        max_loss=max_loss,
        max_levels=2,
        lot_schedule=[[1, 0], [1, 0]],
        add_trigger_atr=[999.0],  # sentinel — InverseVolAddPolicy controls adds
        stop_atr_mult=_STOP_ATR_MULT,
        trail_atr_mult=_STOP_ATR_MULT,  # unused; required by PyramidConfig
        trail_lookback=22,
        margin_limit=0.60,
        long_only_compat_mode=True,
    )
    engine_config = EngineConfig(
        max_loss=config.max_loss,
        margin_limit=config.margin_limit,
        trail_lookback=config.trail_lookback,
        min_hold_lots=1.0,
    )

    hub = _OverlayHub(
        vol_lookback_days=vol_lookback_days,
        vol_target_annual=vol_target_annual,
        trend_sma_days=trend_sma_days,
        dd_breaker_pct=dd_breaker_pct,
        dd_reentry_pct=dd_reentry_pct,
    )
    entry = InverseVolEntryPolicy(hub)
    engine = PositionEngine(
        entry_policy=entry,
        add_policy=InverseVolAddPolicy(hub),
        stop_policy=InverseVolStopPolicy(hub, config),
        config=engine_config,
    )
    engine.indicator_provider = entry  # type: ignore[attr-defined]
    return engine
