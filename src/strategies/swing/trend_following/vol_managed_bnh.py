"""Volatility-Managed Buy-and-Hold — Inverse-Vol Overlay + DD Circuit Breaker.

Architecture (Moreira & Muir 2017 + Faber TAA):
  - Base position (1 lot, pyramid_level=0) is NEVER stopped -> tracks B&H exactly
  - Overlay sized by inverse realized volatility: target_lots = vol_target / realized_vol
  - DD circuit breaker: exit overlay when price < SMA AND drawdown > threshold

Alpha source: conditioning on second moment (vol) rather than first moment (trend
direction). Low-vol periods get more overlay exposure; high-vol periods reduce.

Signal timeframe: 5m bars (converted internally to daily closes for vol calc).
"""
from __future__ import annotations

import math
from collections import deque
from datetime import datetime
from typing import TYPE_CHECKING

import structlog

from src.core.policies import AddPolicy, EntryPolicy, NoAddPolicy, StopPolicy
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
from src.indicators import SMA, SmoothedATR
from src.strategies import HoldingPeriod, SignalTimeframe, StopArchitecture, StrategyCategory

if TYPE_CHECKING:
    from src.core.position_engine import PositionEngine

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Parameter schema — ~8 meaningful params, each with economic motivation
# ---------------------------------------------------------------------------

PARAM_SCHEMA: dict[str, dict] = {
    # Realized volatility estimation
    "vol_lookback_days": {
        "type": "int", "default": 20, "min": 5, "max": 60,
        "description": "Days of close-to-close returns for realized vol (20 = 1 month).",
    },
    "vol_target_annual": {
        "type": "float", "default": 0.15, "min": 0.05, "max": 0.40,
        "description": "Target annualized vol for overlay sizing (0.15 = 15%).",
    },
    "vol_overlay_max_lots": {
        "type": "float", "default": 2.0, "min": 0.5, "max": 5.0,
        "description": "Max overlay lots (cap on inverse-vol sizing).",
    },
    # Trend filter (SMA gate for DD breaker)
    "trend_sma_days": {
        "type": "int", "default": 200, "min": 20, "max": 400,
        "description": "SMA period in days for trend gate / DD breaker.",
    },
    # Drawdown circuit breaker (Faber TAA)
    "dd_breaker_pct": {
        "type": "float", "default": 0.10, "min": 0.03, "max": 0.25,
        "description": "Price drawdown % to exit overlay (0.10 = 10%).",
    },
    "dd_reentry_pct": {
        "type": "float", "default": 0.05, "min": 0.01, "max": 0.15,
        "description": "Drawdown must recover to this level before re-entry.",
    },
    # Golden cross boost
    "boost_sma_fast_days": {
        "type": "int", "default": 50, "min": 0, "max": 100,
        "description": "Fast SMA for golden-cross boost (0 = disabled).",
    },
    "boost_lots": {
        "type": "float", "default": 1.0, "min": 0.0, "max": 3.0,
        "description": "Extra lots on golden cross (0 = disabled).",
    },
    # Nominal stop (wide, base never triggers due to min_hold_lots)
    "stop_atr_mult": {
        "type": "float", "default": 15.0, "min": 1.0, "max": 20.0,
        "description": "Nominal stop multiplier (base lot protected by min_hold_lots).",
    },
}

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
# Internal helpers
# ---------------------------------------------------------------------------

# TAIFEX: day session ~60 5m bars, night ~168, total ~228 bars/day
_TRADING_DAYS_PER_YEAR = 252
_DEFAULT_BARS_PER_DAY = 228  # conservative for TAIFEX day+night


class _DailyCloseStream:
    """Converts 5m bar stream into daily close prices via date rollover.

    Each time the calendar date changes (based on timestamp), the previous
    day's last price is emitted as a daily close.
    """

    __slots__ = ("_last_date", "_last_price", "_daily_closes")

    def __init__(self) -> None:
        self._last_date: str | None = None
        self._last_price: float = 0.0
        self._daily_closes: list[float] = []

    def update(self, price: float, timestamp: datetime) -> float | None:
        """Feed one 5m bar close. Returns a daily close when date rolls over."""
        current_date = timestamp.strftime("%Y-%m-%d")

        if self._last_date is None:
            self._last_date = current_date
            self._last_price = price
            return None

        if current_date != self._last_date:
            # Date changed -> emit previous day's close
            daily_close = self._last_price
            self._daily_closes.append(daily_close)
            self._last_date = current_date
            self._last_price = price
            return daily_close

        self._last_price = price
        return None

    @property
    def closes(self) -> list[float]:
        return self._daily_closes


class _RealizedVol:
    """Close-to-close realized volatility, annualized.

    vol = std(daily_returns) * sqrt(252)
    """

    __slots__ = ("_lookback", "_returns", "_value")

    def __init__(self, lookback_days: int) -> None:
        self._lookback = lookback_days
        self._returns: deque[float] = deque(maxlen=lookback_days)
        self._value: float | None = None

    def update(self, prev_close: float, curr_close: float) -> float | None:
        """Feed one daily return, return annualized vol (None during warmup)."""
        if prev_close <= 0:
            return self._value
        ret = math.log(curr_close / prev_close)
        self._returns.append(ret)
        if len(self._returns) < self._lookback:
            return None
        mean_ret = sum(self._returns) / len(self._returns)
        var = sum((r - mean_ret) ** 2 for r in self._returns) / len(self._returns)
        self._value = math.sqrt(var * _TRADING_DAYS_PER_YEAR)
        return self._value

    @property
    def value(self) -> float | None:
        return self._value

    @property
    def ready(self) -> bool:
        return self._value is not None


class _DDCircuitBreaker:
    """Faber TAA-style drawdown circuit breaker with hysteresis.

    State machine:
      ACTIVE -> TRIPPED when dd >= dd_breaker_pct AND price < sma
      TRIPPED -> ACTIVE when dd <= dd_reentry_pct OR price > sma
    """

    __slots__ = ("_dd_breaker_pct", "_dd_reentry_pct", "_peak_price",
                 "_current_dd", "_tripped")

    def __init__(self, dd_breaker_pct: float, dd_reentry_pct: float) -> None:
        self._dd_breaker_pct = dd_breaker_pct
        self._dd_reentry_pct = dd_reentry_pct
        self._peak_price = 0.0
        self._current_dd = 0.0
        self._tripped = False

    def update(self, price: float, below_sma: bool) -> None:
        """Update drawdown state and circuit breaker."""
        if price > self._peak_price:
            self._peak_price = price
        self._current_dd = (
            1.0 - price / self._peak_price if self._peak_price > 0 else 0.0
        )

        if not self._tripped:
            # Trip when drawdown exceeds threshold AND price below trend SMA
            if (self._dd_breaker_pct > 0
                    and self._current_dd >= self._dd_breaker_pct
                    and below_sma):
                self._tripped = True
        else:
            # Re-enter when drawdown recovers OR price back above SMA
            if (self._current_dd <= self._dd_reentry_pct
                    or not below_sma):
                self._tripped = False

    @property
    def tripped(self) -> bool:
        return self._tripped

    @property
    def current_dd(self) -> float:
        return self._current_dd


class _OverlayHub:
    """Centralized state for the inverse-vol overlay system.

    Ticked once per 5m bar (idempotent via timestamp guard).
    Internally synthesizes daily closes for vol calculation.
    """

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

        # Daily close synthesis
        self._daily_stream = _DailyCloseStream()
        self._prev_daily_close: float | None = None

        # Realized vol
        self._rv = _RealizedVol(vol_lookback_days)

        # Trend SMA (on daily closes)
        self._trend_sma = SMA(trend_sma_days)

        # Golden-cross boost SMAs (on daily closes)
        self._boost_sma_fast = SMA(boost_sma_fast_days) if boost_sma_fast_days > 0 else None
        # Slow SMA is shared with trend_sma

        # DD circuit breaker
        self._dd_breaker = _DDCircuitBreaker(dd_breaker_pct, dd_reentry_pct)

        # Smoothed ATR for initial stop
        self._smoothed_atr = SmoothedATR(14)

        # Idempotency
        self._last_ts: datetime | None = None

        # Public state (updated each tick)
        self.desired_overlay_lots: float = 0.0
        self.golden_cross_active: bool = False
        self.base_lots: float = 1.0  # set by entry policy after risk-based sizing
        self.rv_value: float | None = None
        self.trend_sma_value: float | None = None
        self.boost_sma_fast_value: float | None = None
        # Daily-level overlay decision (sticky until next daily close)
        self._daily_overlay_lots: float = 0.0
        self._daily_golden_cross: bool = False

    def tick(self, price: float, raw_atr: float, timestamp: datetime) -> None:
        """Update all state from one 5m bar."""
        if timestamp == self._last_ts:
            return
        self._last_ts = timestamp

        # Update smoothed ATR
        if raw_atr > 0:
            self._smoothed_atr.update(raw_atr)

        # Update DD breaker with current price (runs on every 5m bar for responsiveness)
        below_sma = False
        if self._trend_sma.ready and self._trend_sma.value is not None:
            below_sma = price < self._trend_sma.value
        self._dd_breaker.update(price, below_sma)

        # Synthesize daily close
        daily_close = self._daily_stream.update(price, timestamp)
        if daily_close is not None:
            self._process_daily_close(daily_close)

        # Overlay decision: use daily-sticky value, only override for DD breaker
        if self._dd_breaker.tripped:
            self.desired_overlay_lots = 0.0
            self.golden_cross_active = False
        else:
            self.desired_overlay_lots = self._daily_overlay_lots
            self.golden_cross_active = self._daily_golden_cross

    def _process_daily_close(self, close: float) -> None:
        """Process a new daily close: update vol, SMA, golden cross, overlay decision."""
        # Realized vol
        if self._prev_daily_close is not None:
            self._rv.update(self._prev_daily_close, close)
        self._prev_daily_close = close

        # Trend SMA
        self._trend_sma.update(close)
        self.trend_sma_value = self._trend_sma.value

        # Boost SMA
        if self._boost_sma_fast is not None:
            self._boost_sma_fast.update(close)
            self.boost_sma_fast_value = self._boost_sma_fast.value

        self.rv_value = self._rv.value

        # Recompute daily overlay decision (sticky until next daily close)
        self._compute_daily_overlay(close)

    def _compute_daily_overlay(self, daily_close: float) -> None:
        """Compute desired overlay lots — called once per daily close, not per 5m bar."""
        # If vol not ready -> no overlay yet (warmup)
        if not self._rv.ready or self._rv.value is None:
            self._daily_overlay_lots = 0.0
            self._daily_golden_cross = False
            return

        # Inverse-vol sizing: target_lots = vol_target / realized_vol
        rv = max(self._rv.value, 0.01)  # floor to prevent division explosion
        raw_lots = self._vol_target / rv

        # Cap at max
        overlay_lots = min(raw_lots, self._max_overlay)

        # Trend gate: only add overlay when daily close > SMA
        if self._trend_sma.ready and self._trend_sma.value is not None:
            if daily_close < self._trend_sma.value:
                overlay_lots = 0.0

        # Golden cross boost
        self._daily_golden_cross = False
        if (self._boost_sma_fast is not None
                and self._boost_sma_fast.ready
                and self._trend_sma.ready
                and self._boost_sma_fast.value is not None
                and self._trend_sma.value is not None):
            if self._boost_sma_fast.value > self._trend_sma.value:
                self._daily_golden_cross = True
                overlay_lots += self._boost_lots

        # Final cap
        self._daily_overlay_lots = min(overlay_lots, self._max_overlay + self._boost_lots)

    @property
    def dd_breaker(self) -> _DDCircuitBreaker:
        return self._dd_breaker

    @property
    def smoothed_atr(self) -> SmoothedATR:
        return self._smoothed_atr


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------

class InverseVolEntryPolicy(EntryPolicy):
    """Enter risk-sized base position on first bar (permanent B&H). Tick overlay hub."""

    def __init__(self, config: PyramidConfig, hub: _OverlayHub, initial_capital: float = 2_000_000.0) -> None:
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
        raw_atr = snapshot.atr.get("daily", 0.0)
        self.hub.tick(snapshot.price, raw_atr, snapshot.timestamp)

        if engine_state.mode in ("halted", "rule_only"):
            return None
        if len(engine_state.positions) > 0:
            return None

        atr = self.hub.smoothed_atr.value
        if atr is None or atr <= 0:
            return None

        stop_distance = self._config.stop_atr_mult * atr
        equity = account.equity if account is not None else self._initial_capital

        # Use margin-based sizing: B&H base lot has a nominal stop that never
        # triggers (protected by min_hold_lots), so stop-distance risk sizing
        # is not meaningful. margin_fraction controls capital deployment.
        from src.core.sizing import compute_margin_lots
        base_lots = compute_margin_lots(
            equity=equity,
            margin_per_unit=snapshot.margin_per_unit,
            margin_fraction=self._config.margin_limit * 0.20,  # 20% of margin budget for base
            min_lot=snapshot.min_lot,
        )
        if base_lots <= 0:
            return None
        # Store on hub so add policy can scale overlay proportionally
        self.hub.base_lots = base_lots

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
        if engine_state.mode == "halted":
            return None
        if not engine_state.positions:
            return None
        # Only 1 overlay level (level 1)
        if engine_state.pyramid_level >= 2:
            return None

        # Tick hub (idempotent)
        raw_atr = snapshot.atr.get("daily", 0.0)
        self._hub.tick(snapshot.price, raw_atr, snapshot.timestamp)

        desired = self._hub.desired_overlay_lots
        if desired <= 0:
            return None

        # Scale overlay by base position size for contract-agnostic sizing.
        # Hub computes desired lots as "units of exposure"; multiply by
        # base_lots so MTX (4x base) gets proportionally more overlay lots.
        lots = desired * self._hub.base_lots
        # Round to nearest whole lot
        lots = max(1.0, round(lots))

        return AddDecision(
            lots=lots,
            contract_type="large",
            move_existing_to_breakeven=False,
        )


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
        # Tick hub (main update path for base lot)
        raw_atr = snapshot.atr.get("daily", 0.0)
        self._hub.tick(snapshot.price, raw_atr, snapshot.timestamp)

        # Base lot: never move stop
        if position.pyramid_level == 0:
            return position.stop_level

        # Overlay: exit when desired overlay drops to 0
        # (DD breaker tripped, trend gate failed, or vol spike)
        if self._hub.desired_overlay_lots <= 0:
            return snapshot.price  # ratchet stop up -> triggers exit

        return position.stop_level


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_vol_managed_bnh_engine(
    max_loss: float = 500_000.0,
    initial_capital: float = 2_000_000.0,
    # Vol overlay
    vol_lookback_days: int = 20,
    vol_target_annual: float = 0.15,
    vol_overlay_max_lots: float = 2.0,
    # Trend filter
    trend_sma_days: int = 200,
    # DD circuit breaker
    dd_breaker_pct: float = 0.10,
    dd_reentry_pct: float = 0.05,
    # Golden cross boost
    boost_sma_fast_days: int = 50,
    boost_lots: float = 1.0,
    # Nominal stop
    stop_atr_mult: float = 15.0,
    # Legacy compat (accepted, unused)
    trail_atr_mult: float = 15.0,
    trail_lookback: int = 22,
    max_levels: int = 2,
    add_spacing_atr: float = 4.0,
    gamma: float = 0.80,
    margin_cap_pct: float = 0.60,
    reentry_cooldown: int = 0,
) -> "PositionEngine":
    """Build a PositionEngine for vol-managed B&H (inverse-vol overlay).

    Base lot (1 TX) held permanently = B&H floor.
    Overlay sized by inverse realized vol with DD circuit breaker.
    """
    from src.core.position_engine import PositionEngine

    config = PyramidConfig(
        max_loss=max_loss,
        max_levels=2,
        lot_schedule=[[1, 0], [1, 0]],
        add_trigger_atr=[999.0],  # unused — InverseVolAddPolicy controls adds
        stop_atr_mult=stop_atr_mult,
        trail_atr_mult=trail_atr_mult,
        trail_lookback=trail_lookback,
        margin_limit=margin_cap_pct,
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
    add_policy: AddPolicy = InverseVolAddPolicy(hub)
    engine = PositionEngine(
        entry_policy=entry,
        add_policy=add_policy,
        stop_policy=InverseVolStopPolicy(hub, config),
        config=engine_config,
    )
    engine.indicator_provider = entry  # type: ignore[attr-defined]
    return engine
