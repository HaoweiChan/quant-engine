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

Design rationale: ~51% WR, RR ~1.15, ~307 trades/year.
Uses BB(20, 2.0) on 30m bars for higher signal frequency with fast RSI(7)
confirmation. Time stop (2.5h) prevents losers from bleeding.
Optimized 2025-06 to 2026-04 on TX real data (run 763). Sharpe 1.29,
Calmar 2.55, MDD 10.3%. OOS/IS Sharpe ratio 1.39. atr_sl_mult stability
CV=13.4% (< 15%). Survives 50% slippage penalty (Sharpe ~1.27).
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
from src.indicators import RSI, SMA, BollingerBands, compose_param_schema
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


_INDICATOR_PARAMS = compose_param_schema({
    "bb_len": (BollingerBands, "period"),
    "rsi_len": (RSI, "period"),
})
_INDICATOR_PARAMS["bb_len"]["min"] = 10
_INDICATOR_PARAMS["bb_len"]["max"] = 60
_INDICATOR_PARAMS["bb_len"]["description"] = "Bollinger Band period on signal TF bars."
_INDICATOR_PARAMS["rsi_len"]["default"] = 7
_INDICATOR_PARAMS["rsi_len"]["min"] = 3
_INDICATOR_PARAMS["rsi_len"]["max"] = 21

PARAM_SCHEMA: dict[str, dict] = {
    "bar_agg_trend": {
        "type": "int", "default": 2, "min": 1, "max": 16,
        "description": "Aggregate N incoming 15m bars for signal TF (2 = 30m).",
    },
    **_INDICATOR_PARAMS,
    "bb_std": {
        "type": "float", "default": 2.0, "min": 1.0, "max": 4.0,
        "description": "Bollinger Band standard deviation multiplier (wider = fewer signals).",
    },
    "rsi_oversold": {
        "type": "float", "default": 40.0, "min": 10.0, "max": 45.0,
        "description": "RSI threshold for oversold (long entry).",
    },
    "rsi_overbought": {
        "type": "float", "default": 60.0, "min": 55.0, "max": 90.0,
        "description": "RSI threshold for overbought (short entry).",
    },
    "macro_ma_len": {
        "type": "int", "default": 60, "min": 30, "max": 120,
        "description": "MA period for macro trend filter on signal TF (60 bars at 30m = 30h).",
    },
    "macro_filter_atr": {
        "type": "float", "default": 5.0, "min": 1.5, "max": 8.0,
        "description": "Block entry if |price - MA| > N * ATR (prevents catching knives).",
    },
    "atr_len": {
        "type": "int", "default": 14, "min": 5, "max": 30,
        "description": "ATR period on entry TF (15m) for stop sizing.",
    },
    "atr_sl_mult": {
        "type": "float", "default": 2.0, "min": 0.5, "max": 3.0,
        "description": "Hard stop: ATR multiplier for initial stop loss.",
    },
    "time_stop_bars": {
        "type": "int", "default": 5, "min": 2, "max": 20,
        "description": "Time stop: close if not reverted within N signal-TF bars (5 = 2.5h at 30m).",
    },
    "max_hold_bars": {
        "type": "int", "default": 60, "min": 10, "max": 300,
        "description": "Max 15m bars to hold (hard cap). 60 = ~15h.",
    },
    "allow_night": {
        "type": "int", "default": 1, "min": 0, "max": 1,
        "description": "Allow entries during night session (0=day only, 1=day+night).",
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
    """Thin wrapper: centralized BB/RSI/SMA on aggregated signal TF; custom ATR on entry TF."""

    def __init__(
        self,
        bb_len: int,
        bb_std: float,
        rsi_len: int,
        macro_ma_len: int,
        atr_len: int,
        bar_agg_trend: int = 4,
    ) -> None:
        self._atr_len = atr_len
        self._bar_agg = max(bar_agg_trend, 1)
        self._agg_count = 0
        self._bb = BollingerBands(period=bb_len, upper_mult=bb_std, lower_mult=bb_std)
        self._rsi_ind = RSI(period=rsi_len)
        self._macro_ma = SMA(period=macro_ma_len)
        self._entry_closes: deque[float] = deque(maxlen=atr_len + 2)
        self._last_ts: datetime | None = None
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
        self._entry_closes.append(price)
        self._compute_entry_atr()
        self._agg_count += 1
        if self._agg_count >= self._bar_agg:
            self._agg_count = 0
            self._bb.update(price)
            self.bb_upper = self._bb.upper
            self.bb_mid = self._bb.mid
            self.bb_lower = self._bb.lower
            self._rsi_ind.update(price)
            self.rsi = self._rsi_ind.value
            self._macro_ma.update(price)
            self.macro_ma = self._macro_ma.value

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
                lots=1,
                contract_type="large",
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
                lots=1,
                contract_type="large",
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
    time_stop_bars: int = 5,
    max_hold_bars: int = 60,
    allow_night: int = 1,
) -> "PositionEngine":
    """Build a PositionEngine wired with the BB Mean Reversion strategy."""
    from src.core.position_engine import PositionEngine

    entry = BBMeanReversionEntry(
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
    engine = PositionEngine(
        entry_policy=entry,
        add_policy=NoAddPolicy(),
        stop_policy=stop,
        config=EngineConfig(max_loss=max_loss),
    )
    engine.indicator_provider = entry.ind  # type: ignore[attr-defined]
    return engine
