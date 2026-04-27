"""Compounding trend-following long — multi-timeframe production strategy.

Production port of the standalone simulator at
``experiment/scripts/compounding_trend_long_mtf_replication.py``. Same
mechanics, expressed against the real PositionEngine policy interface so the
strategy can be backtested via the MCP server and deployed live.

Mechanics
---------
* **Daily regime gate** — rolling 20-day VolumeProfile (POC / VAH / VAL).
  ``TRENDING_UP`` (close > VAH and POC rising over the prior 10 days),
  ``BALANCE`` (close in [VAL, VAH]), ``TRENDING_DOWN`` (close < VAL). A flip
  commits only after 2 consecutive daily closes confirm the new state.
* **1h trend gate** — pyramid adds require the most recent completed 1h close
  to exceed the prior 3-bar 1h swing high.
* **5m execution** — ATR(14) trailing stop on 5m closes with a regime-aware
  multiplier (10x in TRENDING_UP, 6x in BALANCE).
* **Regime-aware sizing** —

  ============  ===========  =========  ===============
  Regime        adds?        max_lots   stop ATR mult
  ============  ===========  =========  ===============
  TRENDING_UP   yes          400        10x 5m ATR
  BALANCE       yes (slow)   200        6x 5m ATR
  TRENDING_DOWN no           0          6x 5m ATR
  ============  ===========  =========  ===============

The strategy keeps multi-timeframe state internally — every 5m bar drives an
internal hub that aggregates 1h and daily bars from a ``DailyCloseStream`` and
an analogous ``_HourlyCloseStream``, recomputes the regime when a new daily
bar lands, and refreshes the 1h gate when a new hourly bar lands.

See ``experiment/docs/compounding_trend_long_conclusion.md`` for the
walk-forward results and the upgrade rationale vs the v1 daily simulator.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import TYPE_CHECKING

from src.core.policies import AddPolicy, EntryPolicy, StopPolicy
from src.core.types import (
    METADATA_STRATEGY_SIZED,
    AccountState,
    AddDecision,
    EngineConfig,
    EngineState,
    EntryDecision,
    MarketSignal,
    MarketSnapshot,
    Position,
)
from src.indicators.daily_close_stream import DailyCloseStream
from src.indicators.volume_profile import VolumeProfile
from src.strategies import (
    HoldingPeriod,
    SignalTimeframe,
    StopArchitecture,
    StrategyCategory,
)

if TYPE_CHECKING:
    from src.core.position_engine import PositionEngine

# ---------------------------------------------------------------------------
# Tunables — regime-keyed presets are kept structural (not per-strategy
# params) so the regime classification is robust across strategies. ATR period
# and pyramid caps are exposed via PARAM_SCHEMA.
# ---------------------------------------------------------------------------

_REGIMES = ("TRENDING_UP", "BALANCE", "TRENDING_DOWN")
_DEFAULT_MARGIN_PER_LOT_FALLBACK = 477_000.0  # TX initial margin (TAIFEX 2025/2026)


def _margin_per_lot(snapshot: MarketSnapshot) -> float:
    mpu = getattr(snapshot, "margin_per_unit", None)
    if mpu and mpu > 0:
        return float(mpu)
    specs = getattr(snapshot, "contract_specs", None)
    if specs is not None:
        m = getattr(specs, "margin_initial", None)
        if m and m > 0:
            return float(m)
    return _DEFAULT_MARGIN_PER_LOT_FALLBACK


def _affordable_lots(margin_available: float, margin_per_lot: float, fraction: float) -> float:
    if margin_per_lot <= 0:
        return 0.0
    n = int(max(0.0, margin_available) * fraction / margin_per_lot)
    return float(n)

_REGIME_PRESETS: dict[str, dict[str, float | int | bool]] = {
    # Empirically calibrated against the production engine's intra-bar pierce
    # semantics + per-Position stop ratchet. 22x in trend, 14x in balance is
    # the sweet spot — wider lets cycles stay open longer but each cycle ends
    # at a worse drawdown; tighter increases cycle count and friction wins.
    "TRENDING_UP": {
        "max_lots": 400, "stop_atr_mult": 22.0,
        "allow_adds": True, "add_buffer_mult": 1.10,
    },
    "BALANCE": {
        "max_lots": 200, "stop_atr_mult": 14.0,
        "allow_adds": True, "add_buffer_mult": 1.50,
    },
    "TRENDING_DOWN": {
        "max_lots": 0, "stop_atr_mult": 14.0,
        "allow_adds": False, "add_buffer_mult": 99.0,
    },
}

# Volume profile rows count and value-area threshold mirror the simulator.
_VP_ROWS = 20
_VP_VA_THRESHOLD = 0.7

PARAM_SCHEMA: dict[str, dict] = {
    "vp_lookback_days": {
        "type": "int", "default": 20, "min": 10, "max": 60,
        "description": "Rolling window (daily bars) for the VolumeProfile regime classifier.",
    },
    "regime_confirm_days": {
        "type": "int", "default": 2, "min": 1, "max": 5,
        "description": "Number of consecutive daily closes required before a regime flip commits.",
    },
    "poc_rise_lookback": {
        "type": "int", "default": 10, "min": 3, "max": 30,
        "description": "Daily lookback for confirming POC has risen before declaring TRENDING_UP.",
    },
    "h1_swing_lookback": {
        "type": "int", "default": 3, "min": 2, "max": 10,
        "description": "Number of prior 1h bars whose swing high must be exceeded for an add.",
    },
    "atr_5m_period": {
        "type": "int", "default": 14, "min": 5, "max": 30,
        "description": "Wilder ATR period for the 5m trailing stop.",
    },
    "max_pyramid_levels": {
        "type": "int", "default": 400, "min": 5, "max": 500,
        "description": "Hard cap on pyramid depth regardless of regime preset.",
    },
    "initial_margin_pct": {
        "type": "float", "default": 0.30, "min": 0.05, "max": 0.97,
        "description": (
            "Fraction of free margin to deploy on the initial entry. "
            "0.30 is calibrated against the production engine's per-position "
            "stop semantics — higher values amplify per-cycle stop losses to "
            "the point of net negative compounding."
        ),
    },
    "add_margin_fraction": {
        "type": "float", "default": 0.50, "min": 0.05, "max": 0.95,
        "description": (
            "Pyramid add threshold knob: adds fire while free margin >= "
            "snapshot.margin_per_unit / add_margin_fraction. Higher values "
            "loosen the threshold (more adds)."
        ),
    },
    "min_initial_stop_pct": {
        "type": "float", "default": 0.020, "min": 0.001, "max": 0.05,
        "description": (
            "Floor on the initial stop distance as a fraction of entry price. "
            "Prevents the very first 5m ATR (which can be tiny early in a "
            "session) from placing a razor-tight stop that triggers on noise."
        ),
    },
    "require_h1_gate": {
        "type": "bool", "default": True,
        "description": (
            "When True, pyramid adds also require the most recent 5m close > "
            "prior h1_swing_lookback 1h-swing high. The production engine "
            "benefits from the stricter gate — without it, adds fire on every "
            "5m bar that has free margin and the per-add positions accumulate "
            "stop-out friction faster than the trend can compound."
        ),
    },
    "per_bar_margin_pct": {
        "type": "float", "default": 0.05, "min": 0.005, "max": 0.30,
        "description": (
            "Per-bar concentration governor — caps each AddDecision's lot count "
            "to ``int(equity * per_bar_margin_pct / margin_per_lot)``. With 0.05, "
            "no single 5m bar can grow margin commitment by more than 5% of "
            "current equity, preventing runaway concentration that would crystallize "
            "huge losses on the inevitable adverse tick. As equity compounds the "
            "cap grows proportionally, so the strategy still scales but never lurches."
        ),
    },
}

STRATEGY_META: dict = {
    "category": StrategyCategory.TREND_FOLLOWING,
    "signal_timeframe": SignalTimeframe.FIVE_MIN,
    "holding_period": HoldingPeriod.SWING,
    "stop_architecture": StopArchitecture.SWING,
    "expected_duration_minutes": (60 * 24 * 14, 60 * 24 * 180),
    "tradeable_sessions": ["day", "night"],
    "description": (
        "Multi-timeframe trend-following long with daily volume-profile "
        "regime gate and 5m ATR stop."
    ),
}


# ---------------------------------------------------------------------------
# Higher-timeframe bar aggregators
# ---------------------------------------------------------------------------

class _HourlyBarAggregator:
    """Build 1h OHLC bars from the 5m bar stream.

    Emits the prior completed 1h bar as ``(timestamp, open, high, low, close)``
    on hour-rollover; returns ``None`` mid-hour. Idempotent on timestamp.
    """

    def __init__(self) -> None:
        self._open: float | None = None
        self._high: float = float("-inf")
        self._low: float = float("inf")
        self._close: float | None = None
        self._bucket_ts: datetime | None = None
        self._last_seen_ts: datetime | None = None

    def update(
        self, price: float, high: float, low: float, timestamp: datetime,
    ) -> tuple[datetime, float, float, float, float] | None:
        """Feed one 5m bar; return the prior completed 1h bar on rollover."""
        if self._last_seen_ts is not None and timestamp <= self._last_seen_ts:
            return None
        self._last_seen_ts = timestamp

        bucket = timestamp.replace(minute=0, second=0, microsecond=0)
        completed: tuple[datetime, float, float, float, float] | None = None

        if self._bucket_ts is not None and bucket != self._bucket_ts and self._open is not None:
            completed = (
                self._bucket_ts, self._open, self._high, self._low, self._close or self._open,
            )
            self._open = None
            self._high = float("-inf")
            self._low = float("inf")
            self._close = None

        if self._open is None:
            self._open = price
            self._bucket_ts = bucket
        self._high = max(self._high, high)
        self._low = min(self._low, low)
        self._close = price
        return completed


class _DailyBarAggregator:
    """Build daily OHLCV bars from the 5m bar stream.

    Uses ``DailyCloseStream`` to detect calendar-date rollovers; when it fires
    we emit the just-completed daily bar accumulated from the intraday stream.
    Volume is summed across the day; OHLC are first / max / min / last.
    """

    def __init__(self) -> None:
        self._stream = DailyCloseStream()
        self._open: float | None = None
        self._high: float = float("-inf")
        self._low: float = float("inf")
        self._volume: float = 0.0
        self._bar_date = None
        self._last_seen_ts: datetime | None = None

    def update(
        self,
        price: float,
        high: float,
        low: float,
        volume: float,
        timestamp: datetime,
    ) -> tuple[datetime, float, float, float, float, float] | None:
        """Feed one 5m bar; return the prior completed daily bar on date-rollover."""
        if self._last_seen_ts is not None and timestamp <= self._last_seen_ts:
            return None
        self._last_seen_ts = timestamp

        completed = None
        prior_close = self._stream.update(price, timestamp)
        if prior_close is not None and self._open is not None and self._bar_date is not None:
            completed = (
                datetime.combine(self._bar_date, datetime.min.time()),
                self._open, self._high, self._low, prior_close, self._volume,
            )
            self._open = None
            self._high = float("-inf")
            self._low = float("inf")
            self._volume = 0.0
            self._bar_date = None

        if self._open is None:
            self._open = price
            self._bar_date = timestamp.date()
        self._high = max(self._high, high)
        self._low = min(self._low, low)
        self._volume += max(volume, 0.0)
        return completed


# ---------------------------------------------------------------------------
# 5m Wilder ATR — single-pass streaming
# ---------------------------------------------------------------------------

class _Streaming5mATR:
    """Wilder ATR over the 5m close-to-close stream."""

    def __init__(self, period: int) -> None:
        self._period = period
        self._tr_window: deque[float] = deque(maxlen=period)
        self._prev_close: float | None = None
        self._value: float | None = None

    def update(self, high: float, low: float, close: float) -> float | None:
        prev = self._prev_close if self._prev_close is not None else close
        tr = max(high - low, abs(high - prev), abs(low - prev))
        self._prev_close = close
        if self._value is None:
            self._tr_window.append(tr)
            if len(self._tr_window) >= self._period:
                self._value = sum(self._tr_window) / self._period
        else:
            self._value = (self._value * (self._period - 1) + tr) / self._period
        return self._value

    @property
    def value(self) -> float | None:
        return self._value


# ---------------------------------------------------------------------------
# Multi-timeframe regime hub
# ---------------------------------------------------------------------------

class _RegimeHub:
    """Owns daily / 1h / 5m aggregations and emits regime + 1h gate state."""

    def __init__(
        self,
        vp_lookback_days: int,
        regime_confirm_days: int,
        poc_rise_lookback: int,
        h1_swing_lookback: int,
        atr_5m_period: int,
    ) -> None:
        self._vp_lookback = vp_lookback_days
        self._confirm_days = regime_confirm_days
        self._poc_lookback = poc_rise_lookback
        self._h1_swing_lookback = h1_swing_lookback

        self._daily_agg = _DailyBarAggregator()
        self._h1_agg = _HourlyBarAggregator()
        self._atr_5m = _Streaming5mATR(period=atr_5m_period)

        # Rolling daily OHLC bars for the volume profile.
        self._daily_bars: deque[tuple[float, float, float, float, float]] = deque(
            maxlen=vp_lookback_days,
        )
        self._poc_history: deque[float | None] = deque(maxlen=poc_rise_lookback + 1)

        self._h1_highs: deque[float] = deque(maxlen=h1_swing_lookback + 1)

        self._raw_regime = "BALANCE"
        self._pending_regime = "BALANCE"
        self._pending_streak = 0
        self._confirmed_regime = "BALANCE"

        self.poc: float | None = None
        self.vah: float | None = None
        self.val: float | None = None

        self._last_seen_ts: datetime | None = None

        # Account bridge — entry policy stashes AccountState here so the add
        # policy (which has no `account` parameter in the ABC) can read it.
        self.account: AccountState | None = None

        # Monotone high-water reference for the trailing stop. Reset on
        # ``mark_position_opened`` (called by entry/re-entry) and bumped via
        # ``tick`` only while a position is open. Mirrors the simulator's
        # ``high_water_close`` exactly — the engine's rolling 24-bar
        # ``high_history`` is too short for swing trends and would tighten the
        # stop after every 2-hour consolidation, generating false stop-outs.
        self._position_open: bool = False
        self.high_water_close: float | None = None

    def mark_position_opened(self, anchor_price: float) -> None:
        self._position_open = True
        self.high_water_close = float(anchor_price)

    def mark_position_closed(self) -> None:
        self._position_open = False
        self.high_water_close = None

    def update_account(self, account: AccountState | None) -> None:
        if account is not None:
            self.account = account

    def tick(self, snapshot: MarketSnapshot) -> None:
        """Feed one 5m bar. Idempotent on timestamp."""
        ts = snapshot.timestamp
        if self._last_seen_ts is not None and ts <= self._last_seen_ts:
            return
        self._last_seen_ts = ts

        price = snapshot.price
        high = snapshot.bar_high
        low = snapshot.bar_low
        volume = snapshot.volume

        self._atr_5m.update(high, low, price)

        # Maintain a monotone high-water mark while a position is open.
        if self._position_open:
            current = float(price)
            if self.high_water_close is None or current > self.high_water_close:
                self.high_water_close = current

        h1_completed = self._h1_agg.update(price, high, low, ts)
        if h1_completed is not None:
            self._h1_highs.append(h1_completed[2])  # high of completed 1h bar

        d_completed = self._daily_agg.update(price, high, low, volume, ts)
        if d_completed is not None:
            _, d_open, d_high, d_low, d_close, d_volume = d_completed
            self._daily_bars.append((d_open, d_high, d_low, d_close, d_volume))
            self._recompute_regime(d_close)

    def _recompute_regime(self, latest_close: float) -> None:
        """Recompute volume profile + raw regime on every new daily bar."""
        if len(self._daily_bars) < self._vp_lookback:
            self._poc_history.append(None)
            return

        window_high = max(b[1] for b in self._daily_bars)
        window_low = min(b[2] for b in self._daily_bars)
        if window_high <= window_low:
            self._poc_history.append(None)
            return

        vp = VolumeProfile(rows=_VP_ROWS, va_threshold=_VP_VA_THRESHOLD)
        vp.new_session(session_high=window_high, session_low=window_low)
        for d_open, d_high, d_low, d_close, d_volume in self._daily_bars:
            vp.add_bar(
                high=d_high, low=d_low, close=d_close, open_=d_open, volume=d_volume,
            )
        result = vp.compute()
        if result is None:
            self._poc_history.append(None)
            return

        self.poc = result.poc
        self.vah = result.vah
        self.val = result.val
        self._poc_history.append(result.poc)

        if latest_close > self.vah:
            prior_poc = (
                self._poc_history[0]
                if len(self._poc_history) > self._poc_lookback
                else None
            )
            raw = "TRENDING_UP" if (prior_poc is None or result.poc >= prior_poc) else "BALANCE"
        elif latest_close < self.val:
            raw = "TRENDING_DOWN"
        else:
            raw = "BALANCE"
        self._raw_regime = raw

        if raw == self._pending_regime:
            self._pending_streak += 1
        else:
            self._pending_regime = raw
            self._pending_streak = 1
        if self._pending_streak >= self._confirm_days:
            self._confirmed_regime = self._pending_regime

    @property
    def confirmed_regime(self) -> str:
        return self._confirmed_regime

    @property
    def atr_5m(self) -> float | None:
        return self._atr_5m.value

    def h1_gate_passed(self, current_close: float) -> bool:
        """Return True iff the most recent 5m close exceeds the prior 1h swing high.

        Uses the completed 1h bars only — the in-progress hour is excluded so
        the gate cannot peek at the still-forming current 1h bar.
        """
        if len(self._h1_highs) < self._h1_swing_lookback:
            return False
        prior_highs = list(self._h1_highs)[-self._h1_swing_lookback:]
        return current_close > max(prior_highs)


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------

class _RegimeAwareEntry(EntryPolicy):
    """Open a base position sized to ``initial_margin_pct`` of free margin."""

    def __init__(
        self,
        hub: _RegimeHub,
        initial_margin_pct: float,
        min_initial_stop_pct: float,
    ) -> None:
        self._hub = hub
        self._initial_margin_pct = initial_margin_pct
        self._min_initial_stop_pct = min_initial_stop_pct

    def should_enter(
        self,
        snapshot: MarketSnapshot,
        signal: MarketSignal | None,
        engine_state: EngineState,
        account: AccountState | None = None,
    ) -> EntryDecision | None:
        self._hub.tick(snapshot)
        self._hub.update_account(account)

        if engine_state.mode == "halted" or engine_state.positions:
            # If the engine no longer has positions, ensure the hub knows so
            # the trailing high water can reset on the next entry.
            if not engine_state.positions:
                self._hub.mark_position_closed()
            return None

        regime = self._hub.confirmed_regime
        preset = _REGIME_PRESETS[regime]
        if not preset["allow_adds"]:
            return None

        atr = self._hub.atr_5m
        if atr is None or atr <= 0:
            return None

        if account is None or account.equity <= 0:
            return None

        mpl = _margin_per_lot(snapshot)
        lots = _affordable_lots(account.margin_available, mpl, self._initial_margin_pct)
        if lots < 1.0:
            return None

        # Initial stop: at least min_initial_stop_pct below entry to absorb the
        # first few 5m bars where the streaming ATR is still tiny.
        atr_distance = float(preset["stop_atr_mult"]) * atr
        floor_distance = snapshot.price * self._min_initial_stop_pct
        stop_distance = max(atr_distance, floor_distance)

        # Mark the hub so the monotone high-water trailing stop resets to the
        # entry price for this position.
        self._hub.mark_position_opened(snapshot.price)

        return EntryDecision(
            lots=lots,
            contract_type="large",
            initial_stop=snapshot.price - stop_distance,
            direction="long",
            metadata={
                "regime": regime,
                "atr_5m": atr,
                "poc": self._hub.poc,
                "vah": self._hub.vah,
                "val": self._hub.val,
                "margin_per_lot": mpl,
                METADATA_STRATEGY_SIZED: True,
            },
        )

    def snapshot(self) -> dict[str, float | None]:
        return {
            "regime": _REGIMES.index(self._hub.confirmed_regime),
            "atr_5m": self._hub.atr_5m,
            "poc": self._hub.poc,
            "vah": self._hub.vah,
            "val": self._hub.val,
        }

    def indicator_meta(self) -> dict[str, dict]:
        return {
            "regime": {"panel": "sub", "color": "#0984E3", "label": "Regime (0=Up,1=Bal,2=Down)"},
            "atr_5m": {"panel": "sub", "color": "#FDCB6E", "label": "ATR(5m)"},
            "poc": {"panel": "price", "color": "#6C5CE7", "label": "POC"},
            "vah": {"panel": "price", "color": "#00B894", "label": "VAH"},
            "val": {"panel": "price", "color": "#D63031", "label": "VAL"},
        }


class _RegimeAwareAdd(AddPolicy):
    """Pyramid using a fraction of *current* free margin per add.

    Sized via the shared ``_RegimeHub`` since the AddPolicy ABC does not pass
    ``AccountState``. The 1h trend gate is opt-in (off by default) so adds fire
    on every snapshot the regime allows them.
    """

    def __init__(
        self,
        hub: _RegimeHub,
        max_pyramid_levels: int,
        add_margin_fraction: float,
        require_h1_gate: bool,
        per_bar_margin_pct: float = 0.05,
    ) -> None:
        self._hub = hub
        self._max_levels = max_pyramid_levels
        self._add_margin_fraction = add_margin_fraction
        self._require_h1_gate = require_h1_gate
        self._per_bar_margin_pct = per_bar_margin_pct

    def should_add(
        self,
        snapshot: MarketSnapshot,
        signal: MarketSignal | None,
        engine_state: EngineState,
    ) -> AddDecision | None:
        if engine_state.mode == "halted" or not engine_state.positions:
            return None

        # tick is idempotent on timestamp — safe to call from both entry and add.
        self._hub.tick(snapshot)

        regime = self._hub.confirmed_regime
        preset = _REGIME_PRESETS[regime]
        if not preset["allow_adds"]:
            return None

        regime_cap = int(preset["max_lots"])
        # Aggregate-Position era: positions[0].lots is the cumulative book
        # size and positions[0].highest_pyramid_level is the depth ever
        # reached. Both caps gate the add — regime_cap on absolute lots,
        # max_pyramid_levels on add-count depth.
        if engine_state.positions:
            current_lots = int(engine_state.positions[0].lots)
            current_depth = int(engine_state.positions[0].highest_pyramid_level)
        else:
            current_lots = 0
            current_depth = 0
        remaining_cap = regime_cap - current_lots
        if remaining_cap <= 0:
            return None
        if current_depth >= self._max_levels:
            return None
        if self._require_h1_gate and not self._hub.h1_gate_passed(snapshot.price):
            return None

        account = self._hub.account
        if account is None or account.margin_available <= 0:
            return None

        # Batched-lot emission with concentration governor.
        #
        # Naive batched emission ``n = int(margin_available / threshold)`` lets
        # the book balloon to 200+ lots once equity has grown — a single
        # adverse move then crystallizes a catastrophic loss because there's
        # no per-bar friction to slow the pyramid. The standalone simulator
        # gets away with this only because its stop fires on intra-bar low
        # pierce at ``stop_level - 1 tick``, capping per-cycle losses to ~one
        # ATR. Production fills are noisier (bps slippage + impact +
        # latency), so we need stricter pacing.
        #
        # Two governors stacked here:
        #   1. **Per-bar cap** = ``equity * per_bar_margin_pct / mpl``. With
        #      0.05 default, no single bar can grow margin commitment by
        #      more than 5% of current equity. As equity compounds the cap
        #      grows proportionally, so the strategy still scales but never
        #      lurches.
        #   2. **Free-margin affordability** = ``margin_available / threshold``
        #      (the existing add-buffer logic). Prevents hitting the broker's
        #      maintenance margin on the next adverse tick.
        # The minimum of the two is taken, so growth is throttled by whichever
        # is tighter on this bar.
        mpl = _margin_per_lot(snapshot)
        threshold_per_lot = mpl / max(self._add_margin_fraction, 0.05)
        if account.margin_available < threshold_per_lot:
            return None

        n_affordable = int(account.margin_available / threshold_per_lot)
        per_bar_cap = max(1, int(account.equity * self._per_bar_margin_pct / mpl))
        n_lots = min(n_affordable, remaining_cap, per_bar_cap)
        if n_lots <= 0:
            return None

        return AddDecision(
            lots=float(n_lots),
            contract_type="large",
            move_existing_to_breakeven=False,
            metadata={
                "regime": regime,
                "atr_5m": self._hub.atr_5m,
                "margin_per_lot": mpl,
                "batched_add_lots": n_lots,
                "per_bar_cap": per_bar_cap,
                METADATA_STRATEGY_SIZED: True,
            },
        )


class _RegimeAwareStop(StopPolicy):
    """Initial + trailing 5m ATR stop, multiplier keyed off the live regime."""

    def __init__(self, hub: _RegimeHub) -> None:
        self._hub = hub

    def initial_stop(
        self, entry_price: float, direction: str, snapshot: MarketSnapshot,
    ) -> float:
        """Anchor every position's stop to the SHARED hub high-water.

        The PositionEngine tracks pyramid adds as independent Position objects,
        each with its own ``stop_level``. If we anchored the initial stop to
        the per-add ``entry_price`` (the natural reading), each add would have
        a slightly different stop and a small pullback would close some adds
        while leaving others — death by a thousand individual stop-outs.

        Anchoring to ``self._hub.high_water_close`` makes every new add share
        the same stop as the existing book. The engine's ``ratchet: stops only
        move favourably`` rule then keeps them all aligned, so when the trail
        fires the whole book exits as a unit (mirroring the standalone
        simulator's "exit ALL lots" semantics).
        """
        self._hub.tick(snapshot)
        atr = self._hub.atr_5m
        if atr is None or atr <= 0:
            daily_atr = float(snapshot.atr.get("daily", 0.0)) if snapshot.atr else 0.0
            atr = max(daily_atr / 8.0, entry_price * 0.005)
        preset = _REGIME_PRESETS[self._hub.confirmed_regime]
        distance = float(preset["stop_atr_mult"]) * atr
        anchor = self._hub.high_water_close or entry_price
        return anchor - distance if direction == "long" else anchor + distance

    def update_stop(
        self,
        position: Position,
        snapshot: MarketSnapshot,
        high_history: deque[float],
    ) -> float:
        # Engine's `high_history` is a 24-bar rolling window of *prices*, not a
        # monotone high-water mark — we deliberately ignore it and use the
        # hub's monotone high_water_close (reset on each new entry).
        self._hub.tick(snapshot)
        atr = self._hub.atr_5m
        if atr is None or atr <= 0:
            return position.stop_level

        regime = self._hub.confirmed_regime
        preset = _REGIME_PRESETS[regime]

        # In TRENDING_DOWN, exit promptly: stop ratchets up to current price.
        if regime == "TRENDING_DOWN":
            return max(position.stop_level, snapshot.price)

        # Use the monotone hub high-water mark; fall back to current price if
        # the hub hasn't seen this position yet (e.g. engine-driven re-entry).
        high_water = self._hub.high_water_close or snapshot.price
        new_stop = high_water - float(preset["stop_atr_mult"]) * atr
        if position.direction == "long":
            return max(position.stop_level, new_stop)
        return min(position.stop_level, high_water + float(preset["stop_atr_mult"]) * atr)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_compounding_trend_long_mtf_engine(
    max_loss: float = 1_000_000_000.0,
    vp_lookback_days: int = 20,
    regime_confirm_days: int = 2,
    poc_rise_lookback: int = 10,
    h1_swing_lookback: int = 3,
    atr_5m_period: int = 14,
    max_pyramid_levels: int = 200,
    initial_margin_pct: float = 0.30,
    add_margin_fraction: float = 0.50,
    min_initial_stop_pct: float = 0.020,
    require_h1_gate: bool = True,
    per_bar_margin_pct: float = 0.05,
    session_id: str | None = None,  # noqa: ARG001 - accepted for runner parity
) -> PositionEngine:
    """Build a PositionEngine wired with the compounding_trend_long_mtf strategy."""
    from src.core.position_engine import PositionEngine

    hub = _RegimeHub(
        vp_lookback_days=vp_lookback_days,
        regime_confirm_days=regime_confirm_days,
        poc_rise_lookback=poc_rise_lookback,
        h1_swing_lookback=h1_swing_lookback,
        atr_5m_period=atr_5m_period,
    )
    entry = _RegimeAwareEntry(
        hub,
        initial_margin_pct=initial_margin_pct,
        min_initial_stop_pct=min_initial_stop_pct,
    )
    engine = PositionEngine(
        entry_policy=entry,
        add_policy=_RegimeAwareAdd(
            hub,
            max_pyramid_levels=max_pyramid_levels,
            add_margin_fraction=add_margin_fraction,
            require_h1_gate=require_h1_gate,
            per_bar_margin_pct=per_bar_margin_pct,
        ),
        stop_policy=_RegimeAwareStop(hub),
        # Strategy-engine semantics: pyramid adds form a single book that
        # exits whole on an intra-bar wick through the trail, filling at the
        # stop level. Without these flags per-Position close-based stops
        # fragment the book and bleed the strategy.
        config=EngineConfig(
            max_loss=max_loss,
            margin_limit=0.97,
            trail_lookback=24,
            min_hold_lots=0.0,
            intrabar_stop_check=True,
            whole_book_exit_on_stop=True,
            stop_fill_at_level=True,
        ),
    )
    engine.indicator_provider = entry  # type: ignore[attr-defined]
    return engine
