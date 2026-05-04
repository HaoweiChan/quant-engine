"""Volatility-Dislocation Reversal (VDR) — mean-reversion on overreaction.

Inspired by the cross-sectional alpha factor:
    (-1) * RANK( STD(ABS(CLOSE-OPEN)) + (CLOSE-OPEN) + CORR(CLOSE, OPEN, N) )

For single-instrument TAIFEX futures, cross-sectional RANK is replaced with
a rolling z-score of the composite signal. The factor captures moments when
"high body volatility + strong directional body + structural instability"
co-occur — indicating short-term emotional overreaction ripe for mean
reversion.

Optimized for 15-minute bars (bar_agg=15) on TX. The factor components are
too noisy on 1m bars; 15m aggregation provides meaningful body statistics.

Walk-forward validation (2024-2025, TX, 15m):
  Aggregate OOS Sharpe: 2.14 | Overfit ratio: 1.09 | All 3 folds positive

Entry:
- Composite = rolling_std(abs(body)) + body + rolling_corr(close, open)
- Z-score the composite over a longer window (120 bars default)
- Signal = signal_flip * z-score  (-1 = reversal, +1 = momentum)
- Long  when signal >  entry_threshold
- Short when signal < -entry_threshold
- Session filter: day/night sessions only, block force-close windows

Exit:
- ATR-based stop loss and take profit (daily ATR)
- Max hold bars: time-exit to prevent bleed
- Force close at session boundaries (intraday strategy)
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, time
from math import sqrt
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
from src.strategies._session_utils import in_day_session, in_force_close, in_night_session

if TYPE_CHECKING:
    from src.core.position_engine import PositionEngine


PARAM_SCHEMA: dict[str, dict] = {
    "std_window": {
        "type": "int", "default": 40, "min": 5, "max": 100,
        "description": "Window for STD(ABS(body)) — body volatility lookback.",
    },
    "corr_window": {
        "type": "int", "default": 20, "min": 5, "max": 50,
        "description": "Window for rolling correlation between close and open proxy.",
    },
    "zscore_window": {
        "type": "int", "default": 120, "min": 20, "max": 200,
        "description": "Window for z-score normalization of composite signal.",
    },
    "entry_threshold": {
        "type": "float", "default": 2.2, "min": 1.0, "max": 4.0, "step": 0.1,
        "description": "Z-score threshold for entry (both long and short).",
    },
    "atr_sl_multi": {
        "type": "float", "default": 0.7, "min": 0.3, "max": 3.0,
        "description": "Stop loss as multiple of daily ATR.",
    },
    "atr_tp_multi": {
        "type": "float", "default": 2.0, "min": 0.5, "max": 6.0,
        "description": "Take profit as multiple of daily ATR.",
    },
    "max_hold_bars": {
        "type": "int", "default": 50, "min": 5, "max": 56,
        "description": "Max bars to hold before time-exit (capped by session length: 56 night, 20 day on 15m).",
    },
    "signal_flip": {
        "type": "int", "default": -1, "min": -1, "max": 1, "step": 2,
        "description": "-1 = mean-reversion (original), +1 = momentum/continuation.",
    },
}

STRATEGY_META: dict = {
    "category": StrategyCategory.MEAN_REVERSION,
    "signal_timeframe": SignalTimeframe.FIFTEEN_MIN,
    "holding_period": HoldingPeriod.SHORT_TERM,
    "stop_architecture": StopArchitecture.INTRADAY,
    "expected_duration_minutes": (15, 90),
    "tradeable_sessions": ["day", "night"],
    "bars_per_day": 70,
    "presets": {
        "quick": {"n_bars": 1400, "note": "~1 month (20 trading days × 70 bars)"},
        "standard": {"n_bars": 4200, "note": "~3 months (60 trading days)"},
        "full_year": {"n_bars": 17640, "note": "~1 year (252 trading days)"},
    },
    "description": (
        "Volatility-Dislocation Reversal: mean-reversion on body-volatility "
        "overreaction on 15m bars. Composite = STD(|body|) + body + "
        "CORR(close,open). Z-score normalized, inverted for reversal."
    ),
}


class _VDRIndicators:
    """Rolling body-volatility, correlation, and z-scored composite signal."""

    def __init__(
        self,
        std_window: int = 20,
        corr_window: int = 10,
        zscore_window: int = 60,
        signal_flip: int = -1,
    ) -> None:
        self._std_win = std_window
        self._corr_win = corr_window
        self._zscore_win = zscore_window
        self._signal_flip = signal_flip
        # Rolling buffers
        self._closes: deque[float] = deque(maxlen=max(corr_window, std_window) + 2)
        self._abs_bodies: deque[float] = deque(maxlen=std_window)
        self._composites: deque[float] = deque(maxlen=zscore_window)
        self._last_ts: datetime | None = None
        self._prev_close: float | None = None
        # Outputs
        self.signal: float | None = None
        self.composite_raw: float | None = None
        self.body_std: float | None = None
        self.corr_co: float | None = None

    def update(self, price: float, timestamp: datetime) -> None:
        if timestamp == self._last_ts:
            return
        self._last_ts = timestamp
        close = price
        # Approximate open as previous close (accurate for 1-min bars)
        open_proxy = self._prev_close if self._prev_close is not None else close
        self._closes.append(close)
        self._prev_close = close
        body = close - open_proxy
        abs_body = abs(body)
        self._abs_bodies.append(abs_body)
        # Component 1: STD(ABS(body)) over std_window
        if len(self._abs_bodies) < self._std_win:
            self.signal = None
            return
        ab_list = list(self._abs_bodies)
        ab_mean = sum(ab_list) / len(ab_list)
        ab_var = sum((x - ab_mean) ** 2 for x in ab_list) / len(ab_list)
        self.body_std = sqrt(ab_var)
        # Component 2: CORR(close, open_proxy) over corr_window
        # We need paired (close, open) series; open[t] ≈ close[t-1]
        closes_list = list(self._closes)
        n_avail = len(closes_list)
        if n_avail < self._corr_win + 1:
            self.signal = None
            return
        c_series = closes_list[-(self._corr_win):]
        o_series = closes_list[-(self._corr_win + 1):-1]
        self.corr_co = _pearson(c_series, o_series)
        if self.corr_co is None:
            self.signal = None
            return
        # Composite
        composite = self.body_std + body + self.corr_co
        self.composite_raw = composite
        self._composites.append(composite)
        # Z-score the composite
        if len(self._composites) < self._zscore_win:
            self.signal = None
            return
        comp_list = list(self._composites)
        c_mean = sum(comp_list) / len(comp_list)
        c_var = sum((x - c_mean) ** 2 for x in comp_list) / len(comp_list)
        c_std = sqrt(c_var)
        if c_std < 1e-9:
            self.signal = None
            return
        zscore = (composite - c_mean) / c_std
        self.signal = float(self._signal_flip) * zscore

    def reset(self) -> None:
        self._closes.clear()
        self._abs_bodies.clear()
        self._composites.clear()
        self._prev_close = None
        self._last_ts = None
        self.signal = None
        self.composite_raw = None
        self.body_std = None
        self.corr_co = None


def _pearson(x: list[float], y: list[float]) -> float | None:
    """Pearson correlation. Returns None if degenerate."""
    n = len(x)
    if n < 3:
        return None
    mx = sum(x) / n
    my = sum(y) / n
    cov = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y)) / n
    sx = sqrt(sum((xi - mx) ** 2 for xi in x) / n)
    sy = sqrt(sum((yi - my) ** 2 for yi in y) / n)
    if sx < 1e-12 or sy < 1e-12:
        return None
    return cov / (sx * sy)


class VDREntryPolicy(EntryPolicy):
    """Enter long/short when the VDR z-score signal exceeds threshold."""

    def __init__(
        self,
        indicators: _VDRIndicators,
        entry_threshold: float = 2.0,
        atr_sl_multi: float = 1.5,
        atr_tp_multi: float = 3.0,
        lots: float = 1.0,
        contract_type: str = "large",
    ) -> None:
        self._ind = indicators
        self._threshold = entry_threshold
        self._atr_sl_multi = atr_sl_multi
        self._atr_tp_multi = atr_tp_multi
        self._lots = lots
        self._contract_type = contract_type

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
        if in_force_close(t):
            return None
        if not (in_day_session(t) or in_night_session(t)):
            return None
        daily_atr = snapshot.atr["daily"]
        if daily_atr <= 0:
            return None
        self._ind.update(snapshot.price, snapshot.timestamp)
        sig = self._ind.signal
        if sig is None:
            return None
        sl_pts = daily_atr * self._atr_sl_multi
        # Long: signal > threshold (bearish overreaction → expect rebound)
        if sig > self._threshold:
            return EntryDecision(
                lots=self._lots,
                contract_type=self._contract_type,
                initial_stop=snapshot.price - sl_pts,
                direction="long",
                metadata={
                    "vdr_signal": round(sig, 3),
                    "body_std": round(self._ind.body_std or 0, 2),
                    "corr_co": round(self._ind.corr_co or 0, 3),
                    "daily_atr": daily_atr,
                    "atr_tp_multi": self._atr_tp_multi,
                },
            )
        # Short: signal < -threshold (bullish overreaction → expect pullback)
        if sig < -self._threshold:
            return EntryDecision(
                lots=self._lots,
                contract_type=self._contract_type,
                initial_stop=snapshot.price + sl_pts,
                direction="short",
                metadata={
                    "vdr_signal": round(sig, 3),
                    "body_std": round(self._ind.body_std or 0, 2),
                    "corr_co": round(self._ind.corr_co or 0, 3),
                    "daily_atr": daily_atr,
                    "atr_tp_multi": self._atr_tp_multi,
                },
            )
        return None


class VDRStopPolicy(StopPolicy):
    """ATR stop/TP + max hold + force close."""

    def __init__(
        self,
        indicators: _VDRIndicators,
        atr_sl_multi: float = 1.5,
        atr_tp_multi: float = 3.0,
        max_hold_bars: int = 120,
    ) -> None:
        self._ind = indicators
        self._atr_sl_multi = atr_sl_multi
        self._atr_tp_multi = atr_tp_multi
        self._max_hold = max_hold_bars
        self._locked_tp_pts: float = 0.0
        self._bar_counts: dict[str, int] = {}

    def initial_stop(
        self,
        entry_price: float,
        direction: str,
        snapshot: MarketSnapshot,
    ) -> float:
        daily_atr = max(snapshot.atr["daily"], 1e-6)
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
        self._ind.update(snapshot.price, snapshot.timestamp)
        price = snapshot.price
        t = snapshot.timestamp.time()
        pid = position.position_id
        self._bar_counts[pid] = self._bar_counts.get(pid, 0) + 1
        # Force close: session end or max hold
        if in_force_close(t) or self._bar_counts[pid] >= self._max_hold:
            self._bar_counts.pop(pid, None)
            return price
        entry = position.entry_price
        tp_pts = self._locked_tp_pts
        if position.direction == "long":
            if price >= entry + tp_pts:
                return price
        else:
            if price <= entry - tp_pts:
                return price
        return position.stop_level


def create_vol_dislocation_reversal_engine(
    max_loss: float = 500_000.0,
    lots: float = 1.0,
    contract_type: str = "large",
    std_window: int = 40,
    corr_window: int = 20,
    zscore_window: int = 120,
    entry_threshold: float = 2.2,
    atr_sl_multi: float = 0.7,
    atr_tp_multi: float = 2.0,
    max_hold_bars: int = 50,
    signal_flip: int = -1,
) -> "PositionEngine":
    """Build a PositionEngine wired with the VDR mean-reversion strategy."""
    from src.core.position_engine import PositionEngine

    indicators = _VDRIndicators(
        std_window=std_window,
        corr_window=corr_window,
        zscore_window=zscore_window,
        signal_flip=signal_flip,
    )
    engine_config = EngineConfig(max_loss=max_loss)
    return PositionEngine(
        entry_policy=VDREntryPolicy(
            indicators=indicators,
            entry_threshold=entry_threshold,
            atr_sl_multi=atr_sl_multi,
            atr_tp_multi=atr_tp_multi,
            lots=lots,
            contract_type=contract_type,
        ),
        add_policy=NoAddPolicy(),
        stop_policy=VDRStopPolicy(
            indicators=indicators,
            atr_sl_multi=atr_sl_multi,
            atr_tp_multi=atr_tp_multi,
            max_hold_bars=max_hold_bars,
        ),
        config=engine_config,
    )
