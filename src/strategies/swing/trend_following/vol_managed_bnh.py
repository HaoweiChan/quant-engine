"""Volatility-Managed Buy-and-Hold — Inverse-Vol Overlay + DD Circuit Breaker.

Architecture (Moreira & Muir 2017 + Faber TAA):
  - Base lot (pyramid_level=0) held permanently -> tracks B&H exactly.
  - Overlay sized by inverse realized vol: lots = vol_target / realized_vol.
  - DD circuit breaker exits overlay when price < SMA AND drawdown > threshold.

Alpha source: conditioning on second moment (vol) rather than first moment (trend).
Low-vol periods get more overlay; high-vol periods reduce.

Signal timeframe: 5m bars synthesized into daily closes internally for vol calc.
Warmup: ~70 min for SmoothedATR + 10 trading days for RealizedVol.

Indicators sourced from src.indicators: RealizedVol, DDCircuitBreaker,
DailyCloseStream, SMA, SmoothedATR.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import TYPE_CHECKING

import structlog

from src.core.policies import AddPolicy, EntryPolicy, StopPolicy
from src.core.types import (
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
from src.strategies import HoldingPeriod, SignalTimeframe, StopArchitecture, StrategyCategory

if TYPE_CHECKING:
    from src.core.position_engine import PositionEngine

logger = structlog.get_logger(__name__)

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
    "vol_overlay_max_lots": {
        "type": "float", "default": 2.0, "min": 0.5, "max": 5.0,
        "description": "Max overlay lots (cap on inverse-vol sizing).",
    },
    "boost_sma_fast_days": {
        "type": "int", "default": 0, "min": 0, "max": 100,
        "description": "Fast SMA for golden-cross boost (0 = disabled).",
    },
    "boost_lots": {
        "type": "float", "default": 0.0, "min": 0.0, "max": 3.0,
        "description": "Extra lots on golden cross (0 = disabled).",
    },
    "stop_atr_mult": {
        "type": "float", "default": 15.0, "min": 1.0, "max": 20.0,
        "description": "Nominal stop multiplier (base lot protected by min_hold_lots).",
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
    "description": (
        "B&H base lot + inverse-vol overlay (Moreira-Muir 2017). "
        "DD circuit breaker (Faber TAA)."
    ),
}


# ---------------------------------------------------------------------------
# _OverlayHub — centralized state for the inverse-vol overlay system
# ---------------------------------------------------------------------------

class _OverlayHub:
    """Centralized state for the inverse-vol overlay, fed one 5m bar per tick."""

    def __init__(
        self,
        vol_lookback_days: int,
        vol_target_annual: float,
        vol_overlay_max_lots: float,
        trend_sma_days: int,
        dd_breaker_pct: float,
        dd_reentry_pct: float,
        boost_sma_fast_days: int,
        boost_lots: float,
    ) -> None:
        self._vol_target = vol_target_annual
        self._max_overlay = vol_overlay_max_lots
        self._boost_lots = boost_lots

        self._daily_stream = DailyCloseStream()
        self._rv = RealizedVol(period=vol_lookback_days)
        self._trend_sma = SMA(period=trend_sma_days)
        self._dd_breaker = DDCircuitBreaker(
            breaker_pct=dd_breaker_pct, reentry_pct=dd_reentry_pct,
        )
        self.smoothed_atr = SmoothedATR(period=14)
        self._boost_sma_fast = SMA(period=boost_sma_fast_days) if boost_sma_fast_days > 0 else None

        self._prev_daily_close: float | None = None
        self._last_ts: datetime | None = None
        # Daily overlay decision persists between daily-close events.
        self._daily_overlay_lots: float = 0.0
        self._daily_golden_cross: bool = False

        # Public per-tick state; set by entry policy / tick().
        self.desired_overlay_lots: float = 0.0
        self.golden_cross_active: bool = False
        self.base_lots: float = 1.0

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

    @property
    def boost_sma_fast_value(self) -> float | None:
        return self._boost_sma_fast.value if self._boost_sma_fast is not None else None

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
            self.golden_cross_active = False
        else:
            self.desired_overlay_lots = self._daily_overlay_lots
            self.golden_cross_active = self._daily_golden_cross

    def _process_daily_close(self, close: float) -> None:
        if self._prev_daily_close is not None:
            self._rv.update(self._prev_daily_close, close)
        self._prev_daily_close = close

        self._trend_sma.update(close)
        if self._boost_sma_fast is not None:
            self._boost_sma_fast.update(close)

        self._recompute_daily_overlay(close)

    def _recompute_daily_overlay(self, daily_close: float) -> None:
        if not self._rv.ready or self._rv.value is None:
            self._daily_overlay_lots = 0.0
            self._daily_golden_cross = False
            return

        # Inverse-vol sizing capped at max, with rv floor to avoid blow-up.
        overlay_lots = min(self._vol_target / max(self._rv.value, 0.01), self._max_overlay)

        # Trend gate: no overlay when price closed below trend SMA.
        trend_val = self._trend_sma.value
        if trend_val is not None and daily_close < trend_val:
            overlay_lots = 0.0

        # Golden cross boost.
        fast = self._boost_sma_fast
        gc = (
            fast is not None and fast.value is not None
            and trend_val is not None and fast.value > trend_val
        )
        self._daily_golden_cross = gc
        if gc:
            overlay_lots += self._boost_lots

        self._daily_overlay_lots = min(overlay_lots, self._max_overlay + self._boost_lots)


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------

class InverseVolEntryPolicy(EntryPolicy):
    """Enter risk-sized base position on first bar (permanent B&H). Tick overlay hub."""

    def __init__(
        self, config: PyramidConfig, hub: _OverlayHub, initial_capital: float = 2_000_000.0,
    ) -> None:
        self._config = config
        self.hub = hub
        self._initial_capital = initial_capital

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

        # Margin-based sizing: base lot's nominal stop is protected by min_hold_lots,
        # so risk-per-trade sizing is not meaningful; margin fraction gates capital.
        from src.core.sizing import compute_margin_lots
        base_lots = compute_margin_lots(
            equity=account.equity if account is not None else self._initial_capital,
            margin_per_unit=snapshot.margin_per_unit,
            margin_fraction=self._config.margin_limit * 0.20,
            min_lot=snapshot.min_lot,
        )
        if base_lots <= 0:
            return None
        self.hub.base_lots = base_lots

        stop_distance = self._config.stop_atr_mult * atr
        return EntryDecision(
            lots=base_lots,
            contract_type="large",
            initial_stop=snapshot.price - stop_distance,
            direction="long",
            metadata={
                "rv": self.hub.rv_value,
                "desired_overlay": self.hub.desired_overlay_lots,
                "base_lots": base_lots,
            },
        )

    def snapshot(self) -> dict[str, float | None]:
        hub = self.hub
        return {
            "realized_vol": hub.rv_value,
            "trend_sma": hub.trend_sma_value,
            "boost_sma_fast": hub.boost_sma_fast_value,
            "desired_overlay": hub.desired_overlay_lots,
            "golden_cross": 1.0 if hub.golden_cross_active else 0.0,
            "dd_pct": hub.dd_breaker.current_dd * 100,
            "dd_tripped": 1.0 if hub.dd_breaker.tripped else 0.0,
        }

    def indicator_meta(self) -> dict[str, dict]:
        return {
            "realized_vol": {"panel": "sub", "color": "#FF6B6B", "label": "RV (ann.)"},
            "trend_sma": {"panel": "price", "color": "#4ECDC4", "label": "SMA(trend)"},
            "boost_sma_fast": {"panel": "price", "color": "#45B7D1", "label": "SMA(fast)"},
            "desired_overlay": {"panel": "sub", "color": "#FFEAA7", "label": "Overlay lots"},
            "golden_cross": {"panel": "sub", "color": "#96CEB4", "label": "GC active"},
            "dd_pct": {"panel": "sub", "color": "#E17055", "label": "DD%"},
            "dd_tripped": {"panel": "sub", "color": "#D63031", "label": "DD tripped"},
        }


class InverseVolAddPolicy(AddPolicy):
    """Add overlay lots based on inverse realized vol when hub says so."""

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
        if engine_state.pyramid_level >= 2:  # single overlay level
            return None

        self._hub.tick(snapshot.price, snapshot.atr.get("daily", 0.0), snapshot.timestamp)
        if self._hub.desired_overlay_lots <= 0:
            return None

        # Scale by base_lots so MTX (more base lots) gets proportionally more overlay.
        lots = max(1.0, round(self._hub.desired_overlay_lots * self._hub.base_lots))
        return AddDecision(lots=lots, contract_type="large", move_existing_to_breakeven=False)


class InverseVolStopPolicy(StopPolicy):
    """Stop policy: base lot never stops, overlay exits on DD breaker or trend break."""

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
    initial_capital: float = 2_000_000.0,
    vol_lookback_days: int = 10,
    vol_target_annual: float = 0.20,
    vol_overlay_max_lots: float = 2.0,
    trend_sma_days: int = 20,
    dd_breaker_pct: float = 0.15,
    dd_reentry_pct: float = 0.05,
    boost_sma_fast_days: int = 0,
    boost_lots: float = 0.0,
    stop_atr_mult: float = 15.0,
) -> PositionEngine:
    """Build a PositionEngine for vol-managed B&H (inverse-vol overlay).

    Pyramid is NOT tuned here — account-level pyramid_risk_level in EngineConfig
    governs all pyramid behavior (AGENTS.md invariant #4). The PyramidConfig
    below encodes this strategy's structural 2-level B&H design as internal
    constants. Defaults validated 2026-04-11 (TX Sharpe 1.67, MTX Sharpe 1.62).
    """
    from src.core.position_engine import PositionEngine

    config = PyramidConfig(
        max_loss=max_loss,
        max_levels=2,
        lot_schedule=[[1, 0], [1, 0]],
        add_trigger_atr=[999.0],  # sentinel — InverseVolAddPolicy controls adds
        stop_atr_mult=stop_atr_mult,
        trail_atr_mult=stop_atr_mult,  # unused; required by PyramidConfig
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
        vol_overlay_max_lots=vol_overlay_max_lots,
        trend_sma_days=trend_sma_days,
        dd_breaker_pct=dd_breaker_pct,
        dd_reentry_pct=dd_reentry_pct,
        boost_sma_fast_days=boost_sma_fast_days,
        boost_lots=boost_lots,
    )
    entry = InverseVolEntryPolicy(config, hub, initial_capital=initial_capital)
    engine = PositionEngine(
        entry_policy=entry,
        add_policy=InverseVolAddPolicy(hub),
        stop_policy=InverseVolStopPolicy(hub, config),
        config=engine_config,
    )
    engine.indicator_provider = entry  # type: ignore[attr-defined]
    return engine
