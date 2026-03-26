"""ATR Adaptive Keltner-Channel Mean Reversion Strategy (1-min).

Uses Keltner Channels (EMA ± K × daily_atr) instead of Bollinger Bands.
Daily ATR from the snapshot is the TRUE range from OHLCV data — far more
stable than the close-close approximation used in the original BB variant.

Entry:
- Long  when Close < KC lower AND RSI < rsi_oversold
- Short when Close > KC upper AND RSI > rsi_overbought
- Volume confirmation: entry bar volume > vol_mult × rolling average
- Time-of-day gate: blocks low-edge TAIFEX windows

Filters:
- Day session (09:00–13:15) or night session (15:15–23:59 / 00:00–04:30)
- Block entry if |Close - trend_ema| > trend_filter_atr × daily_atr

Exit:
- ATR stop loss at entry  (atr_sl_multi × daily_atr)
- ATR take profit at entry (atr_tp_multi × daily_atr)
- Midline exit when price returns to KC midline (toggleable)
- Force close: day 13:25–13:45, night 04:50–05:00
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, time
from statistics import mean
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
from src.strategies import StrategyCategory, StrategyTimeframe
from src.strategies._session_utils import in_day_session, in_force_close, in_night_session

if TYPE_CHECKING:
    from src.core.position_engine import PositionEngine


# ---------------------------------------------------------------------------
# Parameter schema — single source of truth for defaults, types, and ranges
# ---------------------------------------------------------------------------

PARAM_SCHEMA: dict[str, dict] = {
    "kc_len": {
        "type": "int",
        "default": 90,
        "min": 10,
        "max": 300,
        "description": "Keltner Channel EMA lookback (1-min bars).",
        "grid": [60, 90, 120],
    },
    "kc_mult": {
        "type": "float",
        "default": 0.12,
        "min": 0.02,
        "max": 0.5,
        "description": "KC width as fraction of daily ATR.",
        "grid": [0.08, 0.12, 0.15],
    },
    "rsi_len": {
        "type": "int",
        "default": 5,
        "min": 3,
        "max": 30,
        "description": "RSI lookback period.",
        "grid": [3, 5, 10],
    },
    "atr_sl_multi": {
        "type": "float",
        "default": 0.5,
        "min": 0.1,
        "max": 2.0,
        "description": "Stop loss as fraction of daily ATR.",
        "grid": [0.3, 0.5, 0.8],
    },
    "atr_tp_multi": {
        "type": "float",
        "default": 0.8,
        "min": 0.1,
        "max": 3.0,
        "description": "Take profit as fraction of daily ATR.",
        "grid": [0.5, 0.8, 1.2],
    },
    "trend_ma_len": {
        "type": "int",
        "default": 200,
        "min": 20,
        "max": 500,
        "description": "Trend EMA lookback for extreme-trend filter.",
        "grid": [100, 200, 300],
    },
    "trend_filter_atr": {
        "type": "float",
        "default": 2.0,
        "min": 0.5,
        "max": 5.0,
        "description": "Block entries when |price - trend_ema| > N × daily_atr.",
        "grid": [1.0, 2.0, 3.0],
    },
    "rsi_oversold": {
        "type": "float",
        "default": 25.0,
        "min": 10.0,
        "max": 45.0,
        "description": "RSI threshold for oversold (long entry).",
        "grid": [15, 25, 35],
    },
    "rsi_overbought": {
        "type": "float",
        "default": 75.0,
        "min": 55.0,
        "max": 90.0,
        "description": "RSI threshold for overbought (short entry).",
        "grid": [65, 75, 85],
    },
    "midline_exit": {
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 1,
        "description": "Exit when price returns to KC midline (1=enabled, 0=disabled).",
        "grid": [0, 1],
    },
    "vol_len": {
        "type": "int",
        "default": 20,
        "min": 5,
        "max": 100,
        "description": "Rolling window for average volume calculation.",
        "grid": [10, 20, 50],
    },
    "vol_mult": {
        "type": "float",
        "default": 1.2,
        "min": 0.5,
        "max": 5.0,
        "description": "Min volume spike multiplier vs rolling average to confirm entry.",
        "grid": [0.8, 1.2, 1.5],
    },
    "time_gate": {
        "type": "int",
        "default": 1,
        "min": 0,
        "max": 1,
        "description": "Block entries during low-edge windows (1=enabled, 0=disabled).",
        "grid": [0, 1],
    },
}

STRATEGY_META: dict = {
    "category": StrategyCategory.MEAN_REVERSION,
    "timeframe": StrategyTimeframe.INTRADAY,
    "session": "both",
    "bars_per_day": 1050,
    "presets": {
        "quick": {"n_bars": 21000, "note": "~1 month (20 trading days)"},
        "standard": {"n_bars": 63000, "note": "~3 months (60 trading days)"},
        "full_year": {"n_bars": 264600, "note": "~1 year (252 trading days)"},
    },
    "description": (
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
    """Rolling 1-min indicator state: Keltner Channel (EMA ± K*daily_atr), RSI, volume."""

    def __init__(
        self,
        kc_len: int,
        kc_mult: float,
        rsi_len: int,
        trend_ma_len: int,
        vol_len: int = 20,
    ) -> None:
        self._kc_len = kc_len
        self._kc_mult = kc_mult
        self._rsi_len = rsi_len
        self._trend_ma_len = trend_ma_len
        self._vol_len = vol_len
        self._ema_alpha = 2.0 / (kc_len + 1)
        self._trend_alpha = 2.0 / (trend_ma_len + 1)

        max_buf = max(rsi_len + 1, kc_len, trend_ma_len)
        self._closes: deque[float] = deque(maxlen=max_buf + 1)
        self._volumes: deque[float] = deque(maxlen=max(vol_len, 1) + 1)
        self._last_ts: datetime | None = None

        # EMA state (running, not recomputed from buffer)
        self._ema: float | None = None
        self._trend_ema: float | None = None
        self._bar_count: int = 0

        # Public indicator values
        self.kc_mid: float | None = None
        self.kc_upper: float | None = None
        self.kc_lower: float | None = None
        self.rsi: float | None = None
        self.daily_atr: float = 0.0
        self.trend_ema: float | None = None
        self.vol_ratio: float | None = None

    def update(
        self, price: float, timestamp: datetime, volume: float = 0.0, daily_atr: float = 0.0,
    ) -> None:
        if timestamp == self._last_ts:
            return
        self._last_ts = timestamp
        self._closes.append(price)
        self._volumes.append(volume)
        self.daily_atr = daily_atr
        self._bar_count += 1
        self._compute(price)

    def _compute(self, price: float) -> None:
        closes = list(self._closes)
        n = len(closes)

        # EMA for Keltner midline
        if self._ema is None:
            if n >= self._kc_len:
                self._ema = mean(closes[-self._kc_len :])
            else:
                return
        else:
            self._ema = self._ema_alpha * price + (1 - self._ema_alpha) * self._ema

        # Keltner Channel = EMA ± kc_mult × daily_atr
        self.kc_mid = self._ema
        if self.daily_atr > 0:
            width = self._kc_mult * self.daily_atr
            self.kc_upper = self._ema + width
            self.kc_lower = self._ema - width

        # Trend EMA (long-term)
        if self._trend_ema is None:
            if n >= self._trend_ma_len:
                self._trend_ema = mean(closes[-self._trend_ma_len :])
        else:
            self._trend_ema = self._trend_alpha * price + (1 - self._trend_alpha) * self._trend_ema
        self.trend_ema = self._trend_ema

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

        # Volume ratio: current bar volume / rolling average
        vols = list(self._volumes)
        nv = len(vols)
        if nv >= self._vol_len and self._vol_len > 0:
            avg_vol = mean(vols[-self._vol_len :])
            self.vol_ratio = vols[-1] / avg_vol if avg_vol > 0 else 0.0
        elif nv > 0 and vols[-1] > 0:
            self.vol_ratio = 1.0
        else:
            self.vol_ratio = None


# ---------------------------------------------------------------------------
# Entry policy
# ---------------------------------------------------------------------------


def _in_low_edge_window(t: time) -> bool:
    """Block entries during historically low-edge TAIFEX windows.

    Day session: 10:30-12:00 (lunch lull, low volume/directional edge)
    Night session: 20:00-01:00 (overlap gap, erratic price action)
    """
    if time(10, 30) <= t < time(12, 0):
        return True
    if t >= time(20, 0) or t < time(1, 0):
        return True
    return False


class ATRMeanReversionEntryPolicy(EntryPolicy):
    """Enter long/short on Keltner Channel extremes + RSI + volume confirmation."""

    def __init__(
        self,
        indicators: _Indicators,
        lots: float = 1.0,
        contract_type: str = "large",
        atr_sl_multi: float = 0.5,
        atr_tp_multi: float = 0.8,
        trend_filter_atr: float = 2.0,
        rsi_oversold: float = 25.0,
        rsi_overbought: float = 75.0,
        vol_mult: float = 1.2,
        time_gate: bool = True,
    ) -> None:
        self._ind = indicators
        self._lots = lots
        self._contract_type = contract_type
        self._atr_sl_multi = atr_sl_multi
        self._atr_tp_multi = atr_tp_multi
        self._trend_filter_atr = trend_filter_atr
        self._rsi_oversold = rsi_oversold
        self._rsi_overbought = rsi_overbought
        self._vol_mult = vol_mult
        self._time_gate = time_gate

    def should_enter(
        self,
        snapshot: MarketSnapshot,
        signal: MarketSignal | None,
        engine_state: EngineState,
    ) -> EntryDecision | None:
        if engine_state.mode == "halted":
            return None

        t = snapshot.timestamp.time()
        if in_force_close(t):
            return None
        if not (in_day_session(t) or in_night_session(t)):
            return None
        if self._time_gate and _in_low_edge_window(t):
            return None

        daily_atr = snapshot.atr["daily"]
        self._ind.update(snapshot.price, snapshot.timestamp, snapshot.volume, daily_atr)
        ind = self._ind

        if any(v is None for v in (ind.kc_lower, ind.kc_upper, ind.rsi, ind.trend_ema)):
            return None
        if daily_atr <= 0:
            return None

        # Extreme trend filter: block when price deviates too far from trend
        if abs(snapshot.price - ind.trend_ema) > self._trend_filter_atr * daily_atr:  # type: ignore[operator]
            return None

        # Volume confirmation
        if ind.vol_ratio is not None and ind.vol_ratio < self._vol_mult:
            return None

        price = snapshot.price
        sl_pts = daily_atr * self._atr_sl_multi

        # Long: price below KC lower + RSI oversold
        if price < ind.kc_lower and ind.rsi < self._rsi_oversold:  # type: ignore[operator]
            return EntryDecision(
                lots=self._lots,
                contract_type=self._contract_type,
                initial_stop=price - sl_pts,
                direction="long",
                metadata={"daily_atr": daily_atr, "atr_tp_multi": self._atr_tp_multi},
            )

        # Short: price above KC upper + RSI overbought
        if price > ind.kc_upper and ind.rsi > self._rsi_overbought:  # type: ignore[operator]
            return EntryDecision(
                lots=self._lots,
                contract_type=self._contract_type,
                initial_stop=price + sl_pts,
                direction="short",
                metadata={"daily_atr": daily_atr, "atr_tp_multi": self._atr_tp_multi},
            )

        return None


# ---------------------------------------------------------------------------
# Stop policy
# ---------------------------------------------------------------------------


class ATRMeanReversionStopPolicy(StopPolicy):
    """Fixed daily-ATR stop + KC midline exit + force close.

    Take-profit and midline exits are encoded as stop-level ratchets:
    when the condition is met, `stop_level` is set to current price.
    The engine's stop check then closes the position within 1 bar.
    """

    def __init__(
        self,
        indicators: _Indicators,
        atr_sl_multi: float = 0.5,
        atr_tp_multi: float = 0.8,
        midline_exit: bool = False,
    ) -> None:
        self._ind = indicators
        self._atr_sl_multi = atr_sl_multi
        self._atr_tp_multi = atr_tp_multi
        self._midline_exit = midline_exit
        self._locked_tp_pts: float = 0.0

    def initial_stop(
        self,
        entry_price: float,
        direction: str,
        snapshot: MarketSnapshot,
    ) -> float:
        daily_atr = snapshot.atr["daily"]
        self._locked_tp_pts = daily_atr * self._atr_tp_multi
        sl_pts = daily_atr * self._atr_sl_multi
        if direction == "short":
            return entry_price + sl_pts
        return entry_price - sl_pts

    def update_stop(
        self,
        position: Position,
        snapshot: MarketSnapshot,
        high_history: deque[float],
    ) -> float:
        daily_atr = snapshot.atr["daily"]
        self._ind.update(snapshot.price, snapshot.timestamp, snapshot.volume, daily_atr)
        price = snapshot.price
        t = snapshot.timestamp.time()

        if in_force_close(t):
            return price

        entry = position.entry_price
        tp_pts = self._locked_tp_pts

        if position.direction == "long":
            if price >= entry + tp_pts:
                return price
            if self._midline_exit and self._ind.kc_mid is not None and price >= self._ind.kc_mid:
                return price
        else:
            if price <= entry - tp_pts:
                return price
            if self._midline_exit and self._ind.kc_mid is not None and price <= self._ind.kc_mid:
                return price

        return position.stop_level


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_atr_mean_reversion_engine(
    max_loss: float = 500_000.0,
    lots: float = 1.0,
    contract_type: str = "large",
    kc_len: int = 90,
    kc_mult: float = 0.12,
    rsi_len: int = 5,
    atr_sl_multi: float = 0.5,
    atr_tp_multi: float = 0.8,
    trend_ma_len: int = 200,
    trend_filter_atr: float = 2.0,
    rsi_oversold: float = 25.0,
    rsi_overbought: float = 75.0,
    midline_exit: int = 0,
    vol_len: int = 20,
    vol_mult: float = 1.2,
    time_gate: int = 1,
) -> "PositionEngine":
    """Build a PositionEngine wired with the ATR mean-reversion strategy."""
    from src.core.position_engine import PositionEngine

    indicators = _Indicators(
        kc_len=kc_len,
        kc_mult=kc_mult,
        rsi_len=rsi_len,
        trend_ma_len=trend_ma_len,
        vol_len=vol_len,
    )
    engine_config = EngineConfig(max_loss=max_loss)
    return PositionEngine(
        entry_policy=ATRMeanReversionEntryPolicy(
            indicators=indicators,
            lots=lots,
            contract_type=contract_type,
            atr_sl_multi=atr_sl_multi,
            atr_tp_multi=atr_tp_multi,
            trend_filter_atr=trend_filter_atr,
            rsi_oversold=rsi_oversold,
            rsi_overbought=rsi_overbought,
            vol_mult=vol_mult,
            time_gate=bool(time_gate),
        ),
        add_policy=NoAddPolicy(),
        stop_policy=ATRMeanReversionStopPolicy(
            indicators=indicators,
            atr_sl_multi=atr_sl_multi,
            atr_tp_multi=atr_tp_multi,
            midline_exit=bool(midline_exit),
        ),
        config=engine_config,
    )
