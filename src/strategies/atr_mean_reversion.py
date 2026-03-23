"""ATR Adaptive Volatility + Mean Reversion Strategy (1-min).

Ported from XQ (MultiCharts EasyLanguage).

Entry:
- Long  when Close < BB lower band AND RSI < rsi_oversold  (mean reversion, oversold)
- Short when Close > BB upper band AND RSI > rsi_overbought (mean reversion, overbought)

Filters:
- Only during day session (09:00–13:15) or night session (15:15–23:59 / 00:00–04:30)
- Block entry if |Close - 60-MA| > 3 × ATR  (extreme one-sided trend)

Exit:
- ATR stop loss locked at entry  (2.5 × ATR)
- ATR take profit locked at entry (2.0 × ATR)
- Mean reversion: exit when price returns to BB midline
- Force close: day 13:25–13:45, night 04:50–05:00

ATR is approximated as SMA(|ΔClose|, n) because MarketSnapshot only exposes
the close price, not high/low.  The daily ATR from the snapshot is used as a
fallback when the 1-min buffer hasn't warmed up yet.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, time
from statistics import mean, stdev
from typing import TYPE_CHECKING

from src.core.policies import EntryPolicy, NoAddPolicy, StopPolicy
from src.core.types import (
    EngineConfig,
    EngineState,
    EntryDecision,
    MarketSignal,
    MarketSnapshot,
    Position,
)

if TYPE_CHECKING:
    from src.core.position_engine import PositionEngine


# ---------------------------------------------------------------------------
# Parameter schema — single source of truth for defaults, types, and ranges
# ---------------------------------------------------------------------------

PARAM_SCHEMA: dict[str, dict] = {
    "bb_len":         {"type": "int",   "default": 40,   "min": 5,    "max": 60,
                       "description": "Bollinger Bands lookback length.",
                       "grid": [15, 20, 25]},
    "bb_upper_mult":  {"type": "float", "default": 3.0,  "min": 1.0,  "max": 4.0,
                       "description": "BB upper band std multiplier."},
    "bb_lower_mult":  {"type": "float", "default": 1.0,  "min": 0.5,  "max": 4.0,
                       "description": "BB lower band std multiplier."},
    "rsi_len":        {"type": "int",   "default": 5,    "min": 3,    "max": 30,
                       "description": "RSI lookback period."},
    "atr_len":        {"type": "int",   "default": 14,   "min": 5,    "max": 30,
                       "description": "ATR calculation length."},
    "atr_sl_multi":   {"type": "float", "default": 3.5,  "min": 1.0,  "max": 5.0,
                       "description": "ATR multiplier for stop loss.",
                       "grid": [2.0, 2.5, 3.0]},
    "atr_tp_multi":   {"type": "float", "default": 1.5,  "min": 0.5,  "max": 5.0,
                       "description": "ATR multiplier for take profit.",
                       "grid": [1.5, 2.0, 2.5]},
    "trend_ma_len":   {"type": "int",   "default": 60,   "min": 20,   "max": 200,
                       "description": "Trend MA lookback for extreme-trend filter."},
    "rsi_oversold":   {"type": "float", "default": 45.0, "min": 10.0, "max": 50.0,
                       "description": "RSI threshold for oversold (long entry).",
                       "grid": [25, 30]},
    "rsi_overbought": {"type": "float", "default": 60.0, "min": 55.0, "max": 90.0,
                       "description": "RSI threshold for overbought (short entry).",
                       "grid": [70, 75]},
}

STRATEGY_META: dict = {
    "recommended_timeframe": "intraday",
    "bars_per_day": 1050,
    "presets": {
        "quick": {"n_bars": 21000, "note": "~1 month (20 trading days)"},
        "standard": {"n_bars": 63000, "note": "~3 months (60 trading days)"},
        "full_year": {"n_bars": 264600, "note": "~1 year (252 trading days)"},
    },
    "note": (
        "ATR Mean Reversion is a 1-min intraday strategy. "
        "TAIFEX has ~1050 1-min bars/day (day 09:00-13:15 + night 15:15-04:30). "
        "Use timeframe='intraday'. For Monte Carlo, use 'quick' preset "
        "for iteration and 'standard' for validation."
    ),
}


# ---------------------------------------------------------------------------
# Shared indicator state
# ---------------------------------------------------------------------------

class _Indicators:
    """Rolling 1-min indicator state computed from close prices only."""

    def __init__(
        self,
        bb_len: int,
        bb_upper_mult: float,
        bb_lower_mult: float,
        rsi_len: int,
        atr_len: int,
        trend_ma_len: int,
    ) -> None:
        self._bb_len = bb_len
        self._bb_upper_mult = bb_upper_mult
        self._bb_lower_mult = bb_lower_mult
        self._rsi_len = rsi_len
        self._atr_len = atr_len
        self._trend_ma_len = trend_ma_len

        max_buf = max(bb_len, rsi_len + 1, atr_len + 1, trend_ma_len)
        self._closes: deque[float] = deque(maxlen=max_buf + 1)
        self._last_ts: datetime | None = None

        self.bb_mid: float | None = None
        self.bb_upper: float | None = None
        self.bb_lower: float | None = None
        self.rsi: float | None = None
        self.atr_1min: float | None = None
        self.trend_ma: float | None = None

    def update(self, price: float, timestamp: datetime) -> None:
        if timestamp == self._last_ts:
            return
        self._last_ts = timestamp
        self._closes.append(price)
        self._compute()

    def _compute(self) -> None:
        closes = list(self._closes)
        n = len(closes)

        # Bollinger Bands
        if n >= self._bb_len:
            window = closes[-self._bb_len:]
            mid = mean(window)
            sd = stdev(window) if len(window) > 1 else 0.0
            self.bb_mid = mid
            self.bb_upper = mid + self._bb_upper_mult * sd
            self.bb_lower = mid - self._bb_lower_mult * sd

        # RSI (simple, non-smoothed Wilder variant)
        if n >= self._rsi_len + 1:
            changes = [closes[i] - closes[i - 1] for i in range(n - self._rsi_len, n)]
            gains = [c for c in changes if c > 0]
            losses = [-c for c in changes if c < 0]
            avg_gain = mean(gains) if gains else 0.0
            avg_loss = mean(losses) if losses else 0.0
            if avg_loss == 0:
                self.rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                self.rsi = 100.0 - (100.0 / (1.0 + rs))

        # ATR approximation: SMA of |ΔClose|  (no H/L available from snapshot)
        if n >= self._atr_len + 1:
            tr_vals = [abs(closes[i] - closes[i - 1]) for i in range(n - self._atr_len, n)]
            self.atr_1min = mean(tr_vals)

        # Trend MA
        if n >= self._trend_ma_len:
            self.trend_ma = mean(closes[-self._trend_ma_len:])


# ---------------------------------------------------------------------------
# Time-session helpers
# ---------------------------------------------------------------------------

def _in_day_session(t: time) -> bool:
    return time(9, 0) <= t <= time(13, 15)


def _in_night_session(t: time) -> bool:
    # spans midnight: 15:15 → next-day 04:30
    return t >= time(15, 15) or t <= time(4, 30)


def _in_force_close(t: time) -> bool:
    return time(13, 25) <= t < time(13, 45) or time(4, 50) <= t <= time(5, 0)


# ---------------------------------------------------------------------------
# Entry policy
# ---------------------------------------------------------------------------

class ATRMeanReversionEntryPolicy(EntryPolicy):
    """Enter long/short on BB extremes + RSI confirmation (mean reversion)."""

    def __init__(
        self,
        indicators: _Indicators,
        lots: float = 1.0,
        contract_type: str = "large",
        atr_sl_multi: float = 2.5,
        atr_tp_multi: float = 2.0,
        rsi_oversold: float = 25.0,
        rsi_overbought: float = 75.0,
    ) -> None:
        self._ind = indicators
        self._lots = lots
        self._contract_type = contract_type
        self._atr_sl_multi = atr_sl_multi
        self._atr_tp_multi = atr_tp_multi
        self._rsi_oversold = rsi_oversold
        self._rsi_overbought = rsi_overbought

    def should_enter(
        self,
        snapshot: MarketSnapshot,
        signal: MarketSignal | None,
        engine_state: EngineState,
    ) -> EntryDecision | None:
        if engine_state.mode == "halted":
            return None

        t = snapshot.timestamp.time()
        if _in_force_close(t):
            return None
        if not (_in_day_session(t) or _in_night_session(t)):
            return None

        self._ind.update(snapshot.price, snapshot.timestamp)
        ind = self._ind

        if any(v is None for v in (ind.bb_lower, ind.bb_upper, ind.rsi, ind.atr_1min, ind.trend_ma)):
            return None

        atr = ind.atr_1min  # type: ignore[assignment]
        assert atr is not None

        # Extreme trend filter: no entries when trend is too strong
        if abs(snapshot.price - ind.trend_ma) > 3.0 * atr:  # type: ignore[operator]
            return None

        price = snapshot.price
        sl_pts = atr * self._atr_sl_multi

        # Long entry: oversold, price below lower BB
        if price < ind.bb_lower and ind.rsi < self._rsi_oversold:  # type: ignore[operator]
            return EntryDecision(
                lots=self._lots,
                contract_type=self._contract_type,
                initial_stop=price - sl_pts,
                direction="long",
                metadata={"atr_1min": atr, "atr_tp_multi": self._atr_tp_multi},
            )

        # Short entry: overbought, price above upper BB
        if price > ind.bb_upper and ind.rsi > self._rsi_overbought:  # type: ignore[operator]
            return EntryDecision(
                lots=self._lots,
                contract_type=self._contract_type,
                initial_stop=price + sl_pts,
                direction="short",
                metadata={"atr_1min": atr, "atr_tp_multi": self._atr_tp_multi},
            )

        return None


# ---------------------------------------------------------------------------
# Stop policy
# ---------------------------------------------------------------------------

class ATRMeanReversionStopPolicy(StopPolicy):
    """Fixed ATR stop + midline mean-reversion exit + force close.

    Take-profit and midline exits are encoded as stop-level ratchets:
    when the condition is met, `stop_level` is set to current price.
    The engine's stop check then closes the position within 1 bar.
    This 1-bar lag is acceptable for a 1-min strategy.
    """

    def __init__(
        self,
        indicators: _Indicators,
        atr_sl_multi: float = 2.5,
        atr_tp_multi: float = 2.0,
    ) -> None:
        self._ind = indicators
        self._atr_sl_multi = atr_sl_multi
        self._atr_tp_multi = atr_tp_multi
        self._locked_tp_pts: float = 0.0

    def initial_stop(
        self, entry_price: float, direction: str, snapshot: MarketSnapshot,
    ) -> float:
        # Use 1-min ATR if warm, fall back to daily ATR from snapshot
        atr = self._ind.atr_1min if self._ind.atr_1min is not None else snapshot.atr["daily"]
        self._locked_tp_pts = atr * self._atr_tp_multi
        sl_pts = atr * self._atr_sl_multi
        if direction == "short":
            return entry_price + sl_pts
        return entry_price - sl_pts

    def update_stop(
        self,
        position: Position,
        snapshot: MarketSnapshot,
        high_history: deque[float],
    ) -> float:
        self._ind.update(snapshot.price, snapshot.timestamp)
        price = snapshot.price
        t = snapshot.timestamp.time()

        # Force close: set stop to current price so the ratchet locks it in
        # and the engine closes the position on the very next stop check
        if _in_force_close(t):
            return price

        entry = position.entry_price
        tp_pts = self._locked_tp_pts

        if position.direction == "long":
            if price >= entry + tp_pts:
                return price  # take profit hit
            if self._ind.bb_mid is not None and price >= self._ind.bb_mid:
                return price  # mean reversion to midline
        else:
            if price <= entry - tp_pts:
                return price  # take profit hit
            if self._ind.bb_mid is not None and price <= self._ind.bb_mid:
                return price  # mean reversion to midline

        return position.stop_level


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_atr_mean_reversion_engine(
    max_loss: float = 100_000.0,
    lots: float = 1.0,
    contract_type: str = "large",
    bb_len: int = 40,
    bb_upper_mult: float = 3.0,
    bb_lower_mult: float = 1.0,
    rsi_len: int = 5,
    atr_len: int = 14,
    atr_sl_multi: float = 3.5,
    atr_tp_multi: float = 1.5,
    trend_ma_len: int = 60,
    rsi_oversold: float = 45.0,
    rsi_overbought: float = 60.0,
) -> "PositionEngine":
    """Build a PositionEngine wired with the ATR mean-reversion strategy."""
    from src.core.position_engine import PositionEngine

    indicators = _Indicators(
        bb_len=bb_len,
        bb_upper_mult=bb_upper_mult,
        bb_lower_mult=bb_lower_mult,
        rsi_len=rsi_len,
        atr_len=atr_len,
        trend_ma_len=trend_ma_len,
    )
    engine_config = EngineConfig(max_loss=max_loss)
    return PositionEngine(
        entry_policy=ATRMeanReversionEntryPolicy(
            indicators=indicators,
            lots=lots,
            contract_type=contract_type,
            atr_sl_multi=atr_sl_multi,
            atr_tp_multi=atr_tp_multi,
            rsi_oversold=rsi_oversold,
            rsi_overbought=rsi_overbought,
        ),
        add_policy=NoAddPolicy(),
        stop_policy=ATRMeanReversionStopPolicy(
            indicators=indicators,
            atr_sl_multi=atr_sl_multi,
            atr_tp_multi=atr_tp_multi,
        ),
        config=engine_config,
    )
