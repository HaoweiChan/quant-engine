"""Medium-Term BB Mean Reversion Strategy.

Strategy class: Mean reversion / liquidity provision
Entry TF      : 15m bars (received from facade via signal_timeframe metadata)
Signal TF     : 30m bars (internally aggregated: 2 x 15m via bar_agg_trend)

Entry logic (on 30m aggregated bars)
-----------
Long  : 30m close < BB_lower(20, 2.0) AND RSI(7) < rsi_oversold (40)
Short : 30m close > BB_upper(20, 2.0) AND RSI(7) > rsi_overbought (60)

Macro filter (anti-knife-catching):
  Block entry if |close - MA(60)| > 5 * ATR
  Permissive filter — only blocks extreme dislocations.

Exit logic (StopPolicy)
-----------------------
  Hard stop    : entry ± 2.0 x ATR (wider to allow reversion room)
  Take profit  : price returns to BB_mid (target is mean reversion to 20-MA)
  Time stop    : if not reverted within 4 signal-TF bars (2h), close at market
  Max hold     : 60 x 15m bars (~15h hard cap)
  No forced session close — medium-term, holds overnight.

Design rationale: ~50% WR, RR ~1.2, ~312 trades/year.
Uses BB(20, 2.0) on 30m bars for higher signal frequency with fast RSI(7)
confirmation. Tight time stop (2h) prevents losers from bleeding.
Optimized 2025-06 to 2026-04 on TX real data. Survives 1.5-tick slippage
per side (Sharpe 0.69). OOS/IS Sharpe ratio 1.65.
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
        "type": "int", "default": 2, "min": 1, "max": 16,
        "description": "Aggregate N incoming 15m bars for signal TF (2 = 30m).",
        "grid": [2, 4, 8],
    },
    "bb_len": {
        "type": "int", "default": 20, "min": 10, "max": 60,
        "description": "Bollinger Band period on signal TF bars. 20 bars at 30m = 10h.",
        "grid": [10, 15, 20, 25, 30, 40],
    },
    "bb_std": {
        "type": "float", "default": 2.0, "min": 1.0, "max": 4.0,
        "description": "Bollinger Band standard deviation multiplier (wider = fewer signals).",
        "grid": [1.5, 2.0, 2.5, 3.0],
    },
    "rsi_len": {
        "type": "int", "default": 7, "min": 3, "max": 21,
        "description": "RSI period on signal TF bars. Shorter = more reactive.",
        "grid": [5, 7, 10, 14],
    },
    "rsi_oversold": {
        "type": "float", "default": 40.0, "min": 10.0, "max": 45.0,
        "description": "RSI threshold for oversold (long entry).",
        "grid": [30.0, 35.0, 40.0],
    },
    "rsi_overbought": {
        "type": "float", "default": 60.0, "min": 55.0, "max": 90.0,
        "description": "RSI threshold for overbought (short entry).",
        "grid": [60.0, 65.0, 70.0],
    },
    "macro_ma_len": {
        "type": "int", "default": 60, "min": 30, "max": 120,
        "description": "MA period for macro trend filter on signal TF (60 bars at 30m = 30h).",
        "grid": [40, 60, 80],
    },
    "macro_filter_atr": {
        "type": "float", "default": 5.0, "min": 1.5, "max": 8.0,
        "description": "Block entry if |price - MA| > N * ATR (prevents catching knives).",
        "grid": [3.0, 4.0, 5.0, 6.0],
    },
    "atr_len": {
        "type": "int", "default": 14, "min": 5, "max": 30,
        "description": "ATR period on entry TF (15m) for stop sizing.",
    },
    "atr_sl_mult": {
        "type": "float", "default": 2.0, "min": 0.5, "max": 3.0,
        "description": "Hard stop: ATR multiplier for initial stop loss.",
        "grid": [1.5, 2.0, 2.5, 3.0],
    },
    "time_stop_bars": {
        "type": "int", "default": 4, "min": 2, "max": 20,
        "description": "Time stop: close if not reverted within N signal-TF bars (4 = 2h at 30m).",
        "grid": [3, 4, 6, 8],
    },
    "max_hold_bars": {
        "type": "int", "default": 60, "min": 10, "max": 300,
        "description": "Max 15m bars to hold (hard cap). 60 = ~15h.",
        "grid": [30, 45, 60, 90],
    },
    "allow_night": {
        "type": "int", "default": 1, "min": 0, "max": 1,
        "description": "Allow entries during night session (0=day only, 1=day+night).",
    },
    "max_pyramid_levels": {
        "type": "int", "default": 1, "min": 1, "max": 4,
        "description": "Max pyramid levels (default 1=no adds for MR strategy).",
        "grid": [1, 2],
    },
    "pyramid_gamma": {
        "type": "float", "default": 0.7, "min": 0.3, "max": 1.0,
        "description": "Anti-martingale decay.",
        "grid": [0.5, 0.7],
    },
    "pyramid_trigger_atr": {
        "type": "float", "default": 1.5, "min": 0.5, "max": 5.0,
        "description": "ATR multiple for first add trigger.",
        "grid": [1.0, 1.5],
    },
}

STRATEGY_META: dict = {
    "category": StrategyCategory.MEAN_REVERSION,
    "signal_timeframe": SignalTimeframe.FIFTEEN_MIN,
    "holding_period": HoldingPeriod.MEDIUM_TERM,
    "stop_architecture": StopArchitecture.SWING,
    "expected_duration_minutes": (60, 360),
    "tradeable_sessions": ["day", "night"],
    "bars_per_day": 70,
    "presets": {
        "quick": {"n_bars": 1400, "note": "~1 month (20 trading days x 70 bars)"},
        "standard": {"n_bars": 4200, "note": "~3 months (60 trading days x 70 bars)"},
        "full_year": {"n_bars": 17640, "note": "~1 year (252 trading days x 70 bars)"},
    },
    "description": (
        "BB Mean Reversion (30m): enters on BB(20,2) deviation with RSI(7) "
        "confirmation. Macro filter blocks knife-catching (|price-60MA| > 5*ATR). "
        "TP at BB midline, hard 2xATR stop, time stop at 2h. ~50% WR, ~312 "
        "trades/year. Survives 1.5-tick slippage. Holds overnight."
    ),
}

_ATR_SCALE = 1.6


# ---------------------------------------------------------------------------
# Indicators — dual-timeframe: 15m entry, 1h signal
# ---------------------------------------------------------------------------

class _Indicators:
    """Rolling indicators: BB, RSI, macro MA on 1h; ATR on 15m."""

    def __init__(
        self,
        bb_len: int,
        bb_std: float,
        rsi_len: int,
        macro_ma_len: int,
        atr_len: int,
        bar_agg_trend: int = 4,
    ) -> None:
        self._bb_len = bb_len
        self._bb_std = bb_std
        self._rsi_len = rsi_len
        self._macro_ma_len = macro_ma_len
        self._atr_len = atr_len
        self._bar_agg = max(bar_agg_trend, 1)
        self._agg_count = 0

        # Signal TF buffers
        max_sig = max(bb_len, macro_ma_len, rsi_len + 1) + 2
        self._sig_closes: deque[float] = deque(maxlen=max_sig + 1)

        # Entry TF buffers
        self._entry_closes: deque[float] = deque(maxlen=atr_len + 2)

        self._last_ts: datetime | None = None

        # Public state
        self.bb_upper: float | None = None
        self.bb_mid: float | None = None
        self.bb_lower: float | None = None
        self.rsi: float | None = None
        self.macro_ma: float | None = None
        self.atr: float | None = None
        self.atr_avg: float | None = None
        self._atr_history: deque[float] = deque(maxlen=50)

    def update(self, price: float, ts: datetime, volume: float = 0.0) -> None:
        if ts == self._last_ts:
            return
        self._last_ts = ts

        # Entry TF: every 15m bar
        self._entry_closes.append(price)
        self._compute_entry_atr()

        # Signal TF: aggregated to 1h
        self._agg_count += 1
        if self._agg_count >= self._bar_agg:
            self._agg_count = 0
            self._sig_closes.append(price)
            self._compute_signal()

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

    def _compute_signal(self) -> None:
        closes = list(self._sig_closes)
        n = len(closes)

        # Bollinger Bands
        if n >= self._bb_len:
            bb_slice = closes[-self._bb_len:]
            self.bb_mid = _mean(bb_slice)
            std = _stdev(bb_slice, self.bb_mid)
            self.bb_upper = self.bb_mid + self._bb_std * std
            self.bb_lower = self.bb_mid - self._bb_std * std

        # RSI
        if n >= self._rsi_len + 1:
            changes = [closes[i] - closes[i - 1]
                       for i in range(n - self._rsi_len, n)]
            gains = [c for c in changes if c > 0]
            losses = [-c for c in changes if c < 0]
            avg_gain = _mean(gains) if gains else 0.0
            avg_loss = _mean(losses) if losses else 0.0
            if avg_loss == 0:
                self.rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                self.rsi = 100.0 - (100.0 / (1.0 + rs))

        # Macro MA
        if n >= self._macro_ma_len:
            self.macro_ma = _mean(closes[-self._macro_ma_len:])

    def snapshot(self) -> dict[str, float | None]:
        return {
            "bb_upper": self.bb_upper,
            "bb_mid": self.bb_mid,
            "bb_lower": self.bb_lower,
            "macro_ma": self.macro_ma,
            "rsi": self.rsi,
        }

    def indicator_meta(self) -> dict[str, dict]:
        return {
            "bb_upper":  {"panel": "price", "color": "#FF6B6B", "label": "BB Upper (3σ)"},
            "bb_mid":    {"panel": "price", "color": "#FFE66D", "label": "BB Mid (40MA)"},
            "bb_lower":  {"panel": "price", "color": "#FF6B6B", "label": "BB Lower (3σ)"},
            "macro_ma":  {"panel": "price", "color": "#95E1D3", "label": "Macro MA (60)"},
            "rsi":       {"panel": "sub",   "color": "#A8D8EA", "label": "RSI (14)"},
        }


# ---------------------------------------------------------------------------
# Entry policy
# ---------------------------------------------------------------------------

class BBMeanReversionEntry(EntryPolicy):
    """Enter on extreme BB deviation with RSI confirmation and macro filter."""

    def __init__(
        self,
        lots: float = 1.0,
        contract_type: str = "large",
        bar_agg_trend: int = 4,
        bb_len: int = 40,
        bb_std: float = 3.0,
        rsi_len: int = 14,
        rsi_oversold: float = 25.0,
        rsi_overbought: float = 75.0,
        macro_ma_len: int = 60,
        macro_filter_atr: float = 3.0,
        atr_len: int = 14,
        atr_sl_mult: float = 1.5,
        allow_night: int = 1,
    ) -> None:
        self._lots = lots
        self._contract_type = contract_type
        self._rsi_oversold = rsi_oversold
        self._rsi_overbought = rsi_overbought
        self._macro_filter_atr = macro_filter_atr
        self._atr_sl_mult = atr_sl_mult
        self._allow_night = bool(allow_night)
        self.ind = _Indicators(
            bb_len=bb_len, bb_std=bb_std,
            rsi_len=rsi_len,
            macro_ma_len=macro_ma_len,
            atr_len=atr_len,
            bar_agg_trend=bar_agg_trend,
        )

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
        self.ind.update(price, snapshot.timestamp, snapshot.volume)
        ind = self.ind

        if any(v is None for v in (ind.bb_upper, ind.bb_lower, ind.bb_mid, ind.rsi)):
            return None
        atr = ind.atr
        if atr is None or atr <= 0:
            return None

        # Macro filter: block entry if price is too far from macro MA
        # (prevents catching knives in extreme trending markets)
        if ind.macro_ma is not None:
            if abs(price - ind.macro_ma) > self._macro_filter_atr * atr:
                return None

        sl_pts = atr * self._atr_sl_mult

        # Long: extreme oversold
        if price < ind.bb_lower and ind.rsi < self._rsi_oversold:
            return EntryDecision(
                lots=self._lots,
                contract_type=self._contract_type,
                initial_stop=price - sl_pts,
                direction="long",
                metadata={
                    "atr": atr, "rsi": round(ind.rsi, 1),
                    "bb_lower": ind.bb_lower, "bb_mid": ind.bb_mid,
                    "strategy": "mt_bb_mean_reversion",
                },
            )

        # Short: extreme overbought
        if price > ind.bb_upper and ind.rsi > self._rsi_overbought:
            return EntryDecision(
                lots=self._lots,
                contract_type=self._contract_type,
                initial_stop=price + sl_pts,
                direction="short",
                metadata={
                    "atr": atr, "rsi": round(ind.rsi, 1),
                    "bb_upper": ind.bb_upper, "bb_mid": ind.bb_mid,
                    "strategy": "mt_bb_mean_reversion",
                },
            )
        return None


# ---------------------------------------------------------------------------
# Stop policy — hard stop + BB mid TP + time stop
# ---------------------------------------------------------------------------

class BBMeanReversionStop(StopPolicy):
    """Hard ATR stop, BB midline take-profit, and time stop."""

    def __init__(
        self,
        indicators: _Indicators,
        atr_sl_mult: float = 1.5,
        time_stop_bars: int = 6,
        max_hold_bars: int = 100,
        bar_agg: int = 4,
    ) -> None:
        self._ind = indicators
        self._atr_sl_mult = atr_sl_mult
        self._time_stop_bars = time_stop_bars
        self._max_hold = max_hold_bars
        self._bar_agg = bar_agg
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

        # Bar counting
        self._bar_counts[pid] = self._bar_counts.get(pid, 0) + 1
        bar_count = self._bar_counts[pid]

        # Hard max hold (on 15m bars)
        if bar_count >= self._max_hold:
            self._bar_counts.pop(pid, None)
            return price

        # Time stop: convert signal TF bars to entry TF bars
        time_stop_entry_bars = self._time_stop_bars * self._bar_agg
        if bar_count >= time_stop_entry_bars:
            self._bar_counts.pop(pid, None)
            return price

        # Take profit: price returned to BB midline
        bb_mid = self._ind.bb_mid
        if bb_mid is not None:
            if position.direction == "long" and price >= bb_mid:
                self._bar_counts.pop(pid, None)
                return price
            if position.direction == "short" and price <= bb_mid:
                self._bar_counts.pop(pid, None)
                return price

        return stop


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_bb_mean_reversion_engine(
    max_loss: float = 500_000,
    lots: float = 1.0,
    contract_type: str = "large",
    bar_agg_trend: int = 2,
    bb_len: int = 20,
    bb_std: float = 2.0,
    rsi_len: int = 7,
    rsi_oversold: float = 40.0,
    rsi_overbought: float = 60.0,
    macro_ma_len: int = 60,
    macro_filter_atr: float = 5.0,
    atr_len: int = 14,
    atr_sl_mult: float = 2.0,
    time_stop_bars: int = 4,
    max_hold_bars: int = 60,
    allow_night: int = 1,
    max_pyramid_levels: int = 1,
    pyramid_gamma: float = 0.7,
    pyramid_trigger_atr: float = 1.5,
) -> "PositionEngine":
    """Build a PositionEngine wired with the BB Mean Reversion strategy."""
    from src.core.position_engine import PositionEngine

    entry = BBMeanReversionEntry(
        lots=lots,
        contract_type=contract_type,
        bar_agg_trend=bar_agg_trend,
        bb_len=bb_len, bb_std=bb_std,
        rsi_len=rsi_len,
        rsi_oversold=rsi_oversold,
        rsi_overbought=rsi_overbought,
        macro_ma_len=macro_ma_len,
        macro_filter_atr=macro_filter_atr,
        atr_len=atr_len,
        atr_sl_mult=atr_sl_mult,
        allow_night=allow_night,
    )
    stop = BBMeanReversionStop(
        indicators=entry.ind,
        atr_sl_mult=atr_sl_mult,
        time_stop_bars=time_stop_bars,
        max_hold_bars=max_hold_bars,
        bar_agg=bar_agg_trend,
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
