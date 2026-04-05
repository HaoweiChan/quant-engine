"""Medium-Term Hourly Volatility Squeeze Breakout Strategy.

Strategy class: Breakout / volatility expansion
Entry TF      : 15m bars (received from facade via signal_timeframe metadata)
Signal TF     : 1h bars (internally aggregated: 4 x 15m via bar_agg_trend)

Entry logic
-----------
Squeeze detection on 1h bars:
  BB(20, 2.0) inside KC(20, 1.5) = volatility compressed.
  When squeeze releases AND:
    Long  : 1h close > BB_upper + volume > vol_mult * SMA(vol, 20)
    Short : 1h close < BB_lower + volume > vol_mult * SMA(vol, 20)

Exit logic (StopPolicy)
-----------------------
  Initial stop  : entry ± atr_sl_mult x ATR
  Chandelier trail: peak - chandelier_atr_mult x ATR (no fixed TP, let trend run)
  Max hold bars : time-exit after N 15m bars to prevent bleed
  No forced session close — medium-term, holds overnight.

Design rationale: Markets cycle between volatility contraction and expansion.
The squeeze (BB inside KC) marks extreme contraction. The breakout from squeeze
catches the expansion move early, which on hourly timeframes tends to produce
strong directional moves with positive skewness (~40-45% WR, high payoff ratio).
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, time
from typing import TYPE_CHECKING

from src.core.policies import EntryPolicy, NoAddPolicy, StopPolicy
from src.core.types import (
    AccountState,
    EngineConfig,
    EngineState,
    EntryDecision,
    MarketSignal,
    MarketSnapshot,
    Position,
)
from src.strategies import HoldingPeriod, SignalTimeframe, StopArchitecture, StrategyCategory
from src.strategies._session_utils import in_day_session, in_night_session

if TYPE_CHECKING:
    from src.core.position_engine import PositionEngine


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals)


def _stdev(vals: list[float], avg: float) -> float:
    if len(vals) < 2:
        return 0.0
    return (sum((v - avg) ** 2 for v in vals) / (len(vals) - 1)) ** 0.5


PARAM_SCHEMA: dict[str, dict] = {
    "bar_agg_trend": {
        "type": "int", "default": 4, "min": 1, "max": 16,
        "description": "Aggregate N incoming 15m bars for squeeze detection (4 = 1h).",
        "grid": [2, 4, 8],
    },
    "bb_len": {
        "type": "int", "default": 20, "min": 10, "max": 40,
        "description": "Bollinger Band period on signal TF (1h) bars.",
        "grid": [14, 20, 26],
    },
    "bb_std": {
        "type": "float", "default": 2.0, "min": 1.0, "max": 3.0,
        "description": "Bollinger Band standard deviation multiplier.",
        "grid": [1.5, 2.0, 2.5],
    },
    "kc_len": {
        "type": "int", "default": 20, "min": 10, "max": 40,
        "description": "Keltner Channel EMA period on signal TF (1h) bars.",
        "grid": [14, 20, 26],
    },
    "kc_mult": {
        "type": "float", "default": 1.5, "min": 0.5, "max": 3.0,
        "description": "Keltner Channel ATR multiplier.",
        "grid": [1.0, 1.5, 2.0],
    },
    "vol_len": {
        "type": "int", "default": 20, "min": 5, "max": 60,
        "description": "Rolling window for volume average (on signal TF).",
        "grid": [10, 20],
    },
    "vol_mult": {
        "type": "float", "default": 1.5, "min": 0.5, "max": 3.0,
        "description": "Min volume spike vs rolling average for entry confirmation.",
        "grid": [1.0, 1.2, 1.5, 2.0],
    },
    "atr_len": {
        "type": "int", "default": 14, "min": 5, "max": 30,
        "description": "ATR period on entry TF (15m) for stop sizing.",
    },
    "atr_sl_mult": {
        "type": "float", "default": 2.0, "min": 0.5, "max": 4.0,
        "description": "ATR multiplier for initial stop loss.",
        "grid": [1.5, 2.0, 2.5, 3.0],
    },
    "chandelier_atr_mult": {
        "type": "float", "default": 2.5, "min": 1.0, "max": 5.0,
        "description": "Chandelier trailing stop: peak - N * ATR. No fixed TP.",
        "grid": [2.0, 2.5, 3.0, 3.5],
    },
    "min_squeeze_bars": {
        "type": "int", "default": 3, "min": 1, "max": 10,
        "description": "Minimum consecutive 1h bars in squeeze before entry allowed.",
        "grid": [2, 3, 5],
    },
    "max_hold_bars": {
        "type": "int", "default": 200, "min": 20, "max": 400,
        "description": "Max 15m bars to hold before time-exit (200 bars = ~50h).",
        "grid": [96, 144, 200, 300],
    },
    "allow_night": {
        "type": "int", "default": 1, "min": 0, "max": 1,
        "description": "Allow entries during night session (0=day only, 1=day+night).",
    },
    "max_pyramid_levels": {
        "type": "int", "default": 4, "min": 1, "max": 4,
        "description": "Max pyramid levels (1=no adds).",
        "grid": [1, 2, 3, 4],
    },
    "pyramid_gamma": {
        "type": "float", "default": 0.7, "min": 0.3, "max": 1.0,
        "description": "Anti-martingale decay: Size_k = base_lots * gamma^k.",
        "grid": [0.5, 0.7, 0.85],
    },
    "pyramid_trigger_atr": {
        "type": "float", "default": 1.5, "min": 0.5, "max": 5.0,
        "description": "ATR multiple for first add trigger.",
        "grid": [1.0, 1.5, 2.0, 3.0],
    },
}

STRATEGY_META: dict = {
    "category": StrategyCategory.BREAKOUT,
    "signal_timeframe": SignalTimeframe.FIFTEEN_MIN,
    "holding_period": HoldingPeriod.MEDIUM_TERM,
    "stop_architecture": StopArchitecture.SWING,
    "expected_duration_minutes": (120, 720),
    "tradeable_sessions": ["day", "night"],
    "bars_per_day": 70,
    "presets": {
        "quick": {"n_bars": 1400, "note": "~1 month (20 trading days x 70 bars)"},
        "standard": {"n_bars": 4200, "note": "~3 months (60 trading days x 70 bars)"},
        "full_year": {"n_bars": 17640, "note": "~1 year (252 trading days x 70 bars)"},
    },
    "description": (
        "Hourly Volatility Squeeze: detects BB inside KC compression on 1h bars "
        "(aggregated from 15m), enters on squeeze release with volume confirmation. "
        "Chandelier trailing stop, no fixed TP — lets trend run. Holds overnight. "
        "Positive skewness profile (~40-45% WR, high payoff ratio)."
    ),
}

_ATR_SCALE = 1.6


# ---------------------------------------------------------------------------
# Indicators — dual-timeframe: 15m entry, 1h signal (squeeze detection)
# ---------------------------------------------------------------------------

class _Indicators:
    """Rolling indicators with 15m entry TF and 1h signal TF (aggregated)."""

    def __init__(
        self,
        bb_len: int,
        bb_std: float,
        kc_len: int,
        kc_mult: float,
        vol_len: int,
        atr_len: int,
        bar_agg_trend: int = 4,
    ) -> None:
        self._bb_len = bb_len
        self._bb_std = bb_std
        self._kc_len = kc_len
        self._kc_mult = kc_mult
        self._vol_len = vol_len
        self._atr_len = atr_len
        self._bar_agg = max(bar_agg_trend, 1)
        self._agg_count = 0

        # Signal TF (1h aggregated) buffers
        max_sig = max(bb_len, kc_len) + 2
        self._sig_closes: deque[float] = deque(maxlen=max_sig + 1)
        self._sig_volumes: deque[float] = deque(maxlen=max(vol_len, 1) + 1)

        # Entry TF (15m) buffers
        max_entry = atr_len + 2
        self._entry_closes: deque[float] = deque(maxlen=max_entry + 1)

        self._last_ts: datetime | None = None
        self._kc_ema: float | None = None
        self._kc_alpha = 2.0 / (kc_len + 1)

        # Public state
        self.bb_upper: float | None = None
        self.bb_mid: float | None = None
        self.bb_lower: float | None = None
        self.kc_upper: float | None = None
        self.kc_mid: float | None = None
        self.kc_lower: float | None = None
        self.squeeze_on: bool = False
        self.squeeze_count: int = 0
        self._prev_squeeze: bool = False
        self.squeeze_released: bool = False
        self.vol_ratio: float | None = None
        self.atr: float | None = None
        self.atr_avg: float | None = None
        self._atr_history: deque[float] = deque(maxlen=50)

    def update(self, price: float, ts: datetime, volume: float = 0.0) -> None:
        if ts == self._last_ts:
            return
        self._last_ts = ts

        # Entry TF: every bar
        self._entry_closes.append(price)
        self._compute_entry_atr()

        # Signal TF: aggregated
        self._agg_count += 1
        if self._agg_count >= self._bar_agg:
            self._agg_count = 0
            self._sig_closes.append(price)
            self._sig_volumes.append(volume)
            self._compute_signal(price, volume)

    def _compute_entry_atr(self) -> None:
        closes = list(self._entry_closes)
        n = len(closes)
        if n >= self._atr_len + 1:
            diffs = [abs(closes[i] - closes[i - 1])
                     for i in range(n - self._atr_len, n)]
            self.atr = _mean(diffs) * _ATR_SCALE
            self._atr_history.append(self.atr)
            if len(self._atr_history) >= 10:
                self.atr_avg = _mean(list(self._atr_history))

    def _compute_signal(self, price: float, volume: float) -> None:
        closes = list(self._sig_closes)
        n = len(closes)

        # Bollinger Bands
        if n >= self._bb_len:
            bb_slice = closes[-self._bb_len:]
            self.bb_mid = _mean(bb_slice)
            std = _stdev(bb_slice, self.bb_mid)
            self.bb_upper = self.bb_mid + self._bb_std * std
            self.bb_lower = self.bb_mid - self._bb_std * std

        # Keltner Channel
        if self._kc_ema is None:
            if n >= self._kc_len:
                self._kc_ema = _mean(closes[-self._kc_len:])
        else:
            self._kc_ema = self._kc_alpha * price + (1 - self._kc_alpha) * self._kc_ema
        self.kc_mid = self._kc_ema

        if self.kc_mid is not None and n >= self._kc_len + 1:
            # KC ATR: SMA of abs(delta) on signal TF
            kc_diffs = [abs(closes[i] - closes[i - 1])
                        for i in range(max(1, n - self._kc_len), n)]
            kc_atr = _mean(kc_diffs) * _ATR_SCALE if kc_diffs else 0.0
            width = self._kc_mult * kc_atr
            self.kc_upper = self.kc_mid + width
            self.kc_lower = self.kc_mid - width

        # Squeeze detection
        self._prev_squeeze = self.squeeze_on
        if (self.bb_upper is not None and self.kc_upper is not None
                and self.bb_lower is not None and self.kc_lower is not None):
            self.squeeze_on = (self.bb_upper < self.kc_upper
                               and self.bb_lower > self.kc_lower)
            if self.squeeze_on:
                self.squeeze_count += 1
            else:
                # Squeeze just released?
                self.squeeze_released = self._prev_squeeze and not self.squeeze_on
                if not self._prev_squeeze:
                    self.squeeze_released = False
                self.squeeze_count = 0

        # Volume ratio
        vols = list(self._sig_volumes)
        nv = len(vols)
        if nv >= self._vol_len and self._vol_len > 0:
            avg_vol = _mean(vols[-self._vol_len:])
            self.vol_ratio = vols[-1] / avg_vol if avg_vol > 0 else 0.0
        elif nv > 0 and vols[-1] > 0:
            self.vol_ratio = 1.0
        else:
            self.vol_ratio = None

    def snapshot(self) -> dict[str, float | None]:
        return {
            "bb_upper": self.bb_upper,
            "bb_mid": self.bb_mid,
            "bb_lower": self.bb_lower,
            "kc_upper": self.kc_upper,
            "kc_mid": self.kc_mid,
            "kc_lower": self.kc_lower,
        }

    def indicator_meta(self) -> dict[str, dict]:
        return {
            "bb_upper":  {"panel": "price", "color": "#FF6B6B", "label": "BB Upper"},
            "bb_mid":    {"panel": "price", "color": "#FFE66D", "label": "BB Mid"},
            "bb_lower":  {"panel": "price", "color": "#FF6B6B", "label": "BB Lower"},
            "kc_upper":  {"panel": "price", "color": "#4ECDC4", "label": "KC Upper"},
            "kc_mid":    {"panel": "price", "color": "#95E1D3", "label": "KC Mid"},
            "kc_lower":  {"panel": "price", "color": "#4ECDC4", "label": "KC Lower"},
        }


# ---------------------------------------------------------------------------
# Entry policy
# ---------------------------------------------------------------------------

class VolatilitySqueezeEntry(EntryPolicy):
    """Enter on squeeze release with volume confirmation."""

    def __init__(
        self,
        lots: float = 1.0,
        contract_type: str = "large",
        bar_agg_trend: int = 4,
        bb_len: int = 20,
        bb_std: float = 2.0,
        kc_len: int = 20,
        kc_mult: float = 1.5,
        vol_len: int = 20,
        vol_mult: float = 1.5,
        atr_len: int = 14,
        atr_sl_mult: float = 2.0,
        min_squeeze_bars: int = 3,
        allow_night: int = 1,
    ) -> None:
        self._lots = lots
        self._contract_type = contract_type
        self._vol_mult = vol_mult
        self._atr_sl_mult = atr_sl_mult
        self._min_squeeze_bars = min_squeeze_bars
        self._allow_night = bool(allow_night)
        self.ind = _Indicators(
            bb_len=bb_len, bb_std=bb_std,
            kc_len=kc_len, kc_mult=kc_mult,
            vol_len=vol_len, atr_len=atr_len,
            bar_agg_trend=bar_agg_trend,
        )
        # Track squeeze duration (how many 1h bars were in squeeze before release)
        self._last_squeeze_duration: int = 0

    def should_enter(
        self,
        snapshot: MarketSnapshot,
        signal: MarketSignal | None,
        engine_state: EngineState,
        account: AccountState | None = None,
    ) -> EntryDecision | None:
        if engine_state.mode == "halted":
            return None
        t = snapshot.timestamp.time()
        day_ok = in_day_session(t)
        night_ok = self._allow_night and in_night_session(t)
        if not (day_ok or night_ok):
            return None

        price = snapshot.price
        # Track squeeze count before update (for min_squeeze_bars check)
        prev_count = self.ind.squeeze_count
        self.ind.update(price, snapshot.timestamp, snapshot.volume)
        ind = self.ind

        if not ind.squeeze_released:
            return None
        # Reset squeeze_released flag after reading it
        ind.squeeze_released = False

        # Must have been in squeeze for minimum duration
        if prev_count < self._min_squeeze_bars:
            return None
        self._last_squeeze_duration = prev_count

        atr = ind.atr
        if atr is None or atr <= 0:
            return None
        if ind.bb_upper is None or ind.bb_lower is None:
            return None

        # Volume confirmation
        if ind.vol_ratio is not None and ind.vol_ratio < self._vol_mult:
            return None

        sl_pts = atr * self._atr_sl_mult

        # Direction: which side of BB did price break?
        if price > ind.bb_upper:
            return EntryDecision(
                lots=self._lots,
                contract_type=self._contract_type,
                initial_stop=price - sl_pts,
                direction="long",
                metadata={
                    "atr": atr, "squeeze_bars": self._last_squeeze_duration,
                    "bb_upper": ind.bb_upper, "vol_ratio": ind.vol_ratio,
                    "strategy": "mt_volatility_squeeze",
                },
            )
        if price < ind.bb_lower:
            return EntryDecision(
                lots=self._lots,
                contract_type=self._contract_type,
                initial_stop=price + sl_pts,
                direction="short",
                metadata={
                    "atr": atr, "squeeze_bars": self._last_squeeze_duration,
                    "bb_lower": ind.bb_lower, "vol_ratio": ind.vol_ratio,
                    "strategy": "mt_volatility_squeeze",
                },
            )
        return None


# ---------------------------------------------------------------------------
# Stop policy — Chandelier exit (no fixed TP, let trend run)
# ---------------------------------------------------------------------------

class VolatilitySqueezeStop(StopPolicy):
    """Chandelier trailing stop: peak - N * ATR. No fixed TP."""

    def __init__(
        self,
        indicators: _Indicators,
        atr_sl_mult: float = 2.0,
        chandelier_atr_mult: float = 2.5,
        max_hold_bars: int = 200,
    ) -> None:
        self._ind = indicators
        self._atr_sl_mult = atr_sl_mult
        self._chandelier_mult = chandelier_atr_mult
        self._max_hold = max_hold_bars
        self._peak: dict[str, float] = {}
        self._bar_counts: dict[str, int] = {}

    def initial_stop(
        self, entry_price: float, direction: str, snapshot: MarketSnapshot,
    ) -> float:
        atr = self._ind.atr if self._ind.atr is not None else snapshot.atr.get("daily", 200.0)
        sl_pts = atr * self._atr_sl_mult
        if direction == "long":
            return entry_price - sl_pts
        return entry_price + sl_pts

    def update_stop(
        self,
        position: Position,
        snapshot: MarketSnapshot,
        high_history: deque[float],
    ) -> float:
        self._ind.update(snapshot.price, snapshot.timestamp, snapshot.volume)
        price = snapshot.price
        stop = position.stop_level
        pid = position.position_id

        # Time exit
        self._bar_counts[pid] = self._bar_counts.get(pid, 0) + 1
        if self._bar_counts[pid] >= self._max_hold:
            self._bar_counts.pop(pid, None)
            self._peak.pop(pid, None)
            return price

        atr = self._ind.atr
        if atr is None or atr <= 0:
            return stop

        if position.direction == "long":
            self._peak[pid] = max(self._peak.get(pid, price), price)
            chandelier = self._peak[pid] - self._chandelier_mult * atr
            return max(stop, chandelier)
        else:
            self._peak[pid] = min(self._peak.get(pid, price), price)
            chandelier = self._peak[pid] + self._chandelier_mult * atr
            return min(stop, chandelier)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_volatility_squeeze_engine(
    max_loss: float = 500_000,
    lots: float = 1.0,
    contract_type: str = "large",
    bar_agg_trend: int = 4,
    bb_len: int = 20,
    bb_std: float = 2.0,
    kc_len: int = 20,
    kc_mult: float = 1.5,
    vol_len: int = 20,
    vol_mult: float = 1.5,
    atr_len: int = 14,
    atr_sl_mult: float = 2.0,
    chandelier_atr_mult: float = 2.5,
    min_squeeze_bars: int = 3,
    max_hold_bars: int = 200,
    allow_night: int = 1,
    max_pyramid_levels: int = 4,
    pyramid_gamma: float = 0.7,
    pyramid_trigger_atr: float = 1.5,
) -> "PositionEngine":
    """Build a PositionEngine wired with the Volatility Squeeze strategy."""
    from src.core.position_engine import PositionEngine

    entry = VolatilitySqueezeEntry(
        lots=lots,
        contract_type=contract_type,
        bar_agg_trend=bar_agg_trend,
        bb_len=bb_len, bb_std=bb_std,
        kc_len=kc_len, kc_mult=kc_mult,
        vol_len=vol_len, vol_mult=vol_mult,
        atr_len=atr_len, atr_sl_mult=atr_sl_mult,
        min_squeeze_bars=min_squeeze_bars,
        allow_night=allow_night,
    )
    stop = VolatilitySqueezeStop(
        indicators=entry.ind,
        atr_sl_mult=atr_sl_mult,
        chandelier_atr_mult=chandelier_atr_mult,
        max_hold_bars=max_hold_bars,
    )
    if max_pyramid_levels > 1:
        from src.core.policies import PyramidAddPolicy
        from src.core.types import PyramidConfig

        triggers = [pyramid_trigger_atr * (i + 1) for i in range(max_pyramid_levels - 1)]
        pyramid_config = PyramidConfig(
            max_loss=max_loss,
            max_levels=max_pyramid_levels,
            add_trigger_atr=triggers,
            atr_key="entry_tf",
            gamma=pyramid_gamma,
            base_lots=lots,
            internal_atr_len=14,
        )
        add_policy = PyramidAddPolicy(pyramid_config)
    else:
        add_policy = NoAddPolicy()
    engine = PositionEngine(
        entry_policy=entry,
        add_policy=add_policy,
        stop_policy=stop,
        config=EngineConfig(max_loss=max_loss),
    )
    engine.indicator_provider = entry.ind  # type: ignore[attr-defined]
    return engine
