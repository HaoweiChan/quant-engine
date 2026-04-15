"""R1/R2 Calendar Spread Mean Reversion Strategy (1-min).

Trades the intraday spread between TX (near-month, R1) and TX_R2
(next-month, R2).  The spread = R1.close - R2.close exhibits strong
mean-reversion (ADF p<0.001, half-life ~11 bars).

When the spread's z-score deviates beyond entry_z, the strategy enters
a mean-reversion trade (short spread when z > entry_z, long spread when
z < -entry_z).  Exits when z reverts to exit_z, or stops out at stop_z.

Physical execution: 2-leg spread (buy+sell R1/R2 simultaneously).
For backtest: feed synthetic "spread bars" where price = R1 - R2.
The facade auto-constructs these when it detects spread_legs in META.

Cost model:  4 legs per round-trip → commission_fixed accounts for
R1 slippage (1 tick/leg) + R2 slippage (2 tick/leg) + commissions.
"""
from __future__ import annotations

from collections import deque
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
from src.strategies._session_utils import in_force_close

if TYPE_CHECKING:
    from src.core.position_engine import PositionEngine


PARAM_SCHEMA: dict[str, dict] = {
    "lookback": {
        "type": "int", "default": 60, "min": 20, "max": 200,
        "description": "Rolling window for spread mean/std (1-min bars).",
        "grid": [30, 60, 100, 150],
    },
    "entry_z": {
        "type": "float", "default": 2.0, "min": 1.0, "max": 4.0,
        "description": "Z-score threshold to enter mean-reversion trade.",
        "grid": [1.5, 2.0, 2.5],
    },
    "exit_z": {
        "type": "float", "default": 0.3, "min": 0.0, "max": 1.5,
        "description": "Z-score threshold to take profit (near mean).",
        "grid": [0.0, 0.3, 0.5],
    },
    "stop_extra": {
        "type": "float", "default": 1.5, "min": 0.5, "max": 3.0,
        "description": "Additional z beyond entry_z for stop-loss (stop_z = entry_z + stop_extra).",
        "grid": [1.0, 1.5, 2.0],
    },
    "max_hold_bars": {
        "type": "int", "default": 180, "min": 30, "max": 600,
        "description": "Max bars to hold before time-exit (3h default).",
        "grid": [90, 120, 180],
    },
    "min_std": {
        "type": "float", "default": 1.0, "min": 0.1, "max": 5.0,
        "description": "Minimum spread std to consider the spread active.",
        "grid": [0.5, 1.0, 2.0],
    },
    "lots": {
        "type": "int", "default": 5, "min": 1, "max": 20,
        "description": "Spread pairs per trade (1 lot = 1 R1 + 1 R2 contract).",
        "grid": [1, 3, 5, 10],
    },
}

STRATEGY_META: dict = {
    "category": StrategyCategory.MEAN_REVERSION,
    "signal_timeframe": SignalTimeframe.ONE_MIN,
    "holding_period": HoldingPeriod.SHORT_TERM,
    "stop_architecture": StopArchitecture.INTRADAY,
    "expected_duration_minutes": (3, 30),
    "tradeable_sessions": ["day", "night"],
    "bars_per_day": 1050,
    "spread_legs": ["TX", "TX_R2"],
    "spread_cost_per_fill": 700.0,
    "presets": {
        "quick": {"n_bars": 21000, "note": "~1 month (20 trading days)"},
        "standard": {"n_bars": 63000, "note": "~3 months (60 trading days)"},
        "full_year": {"n_bars": 264600, "note": "~1 year (252 trading days)"},
    },
    "description": (
        "Intraday R1/R2 calendar spread mean-reversion on 1-min bars. "
        "Enters when spread z-score deviates beyond threshold, exits on "
        "reversion to mean. 2-leg execution (TX + TX_R2). "
        "TAIFEX has ~1050 1-min bars/day (day+night sessions)."
    ),
}


class _SpreadState:
    """Rolling z-score tracker with auto-reset on rollover jumps.

    Contract rolls cause abrupt spread jumps (200+ pts).  When detected,
    the buffer is cleared to prevent stale mean/std from generating
    false signals.  A timestamp guard avoids double-updates when both
    entry and stop policies process the same bar.
    """

    JUMP_THRESHOLD = 40.0  # reset buffer if spread jumps > this in 1 bar

    def __init__(self, lookback: int, min_std: float = 1.0) -> None:
        self._lookback = lookback
        self._min_std = min_std
        self._prices: deque[float] = deque(maxlen=lookback)
        self._last_price: float | None = None
        self._last_ts: object = None  # dedup guard
        self.z_score: float | None = None
        self.mean: float = 0.0
        self.std: float = 0.0

    def update(self, spread_price: float, ts: object = None) -> None:
        if ts is not None and ts == self._last_ts:
            return
        self._last_ts = ts
        # Detect rollover / large gap and reset buffer
        if self._last_price is not None and abs(spread_price - self._last_price) > self.JUMP_THRESHOLD:
            self._prices.clear()
            self.z_score = None
        self._last_price = spread_price
        self._prices.append(spread_price)
        if len(self._prices) < self._lookback:
            self.z_score = None
            return
        import numpy as np
        arr = np.array(self._prices)
        self.mean = float(np.mean(arr))
        self.std = float(np.std(arr))
        if self.std < self._min_std:
            self.z_score = None
            return
        self.z_score = (spread_price - self.mean) / self.std

    @property
    def ready(self) -> bool:
        return self.z_score is not None


class SpreadReversionEntryPolicy(EntryPolicy):
    """Enter when spread z-score exceeds entry_z threshold."""

    def __init__(
        self,
        state: _SpreadState,
        entry_z: float = 2.0,
        lots: float = 1.0,
        contract_type: str = "large",
    ) -> None:
        self._state = state
        self._entry_z = entry_z
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
        self._state.update(snapshot.price, ts=snapshot.timestamp)
        if not self._state.ready:
            return None
        z = self._state.z_score
        # Spread overextended upward → short the spread (expect reversion down)
        if z >= self._entry_z:
            return EntryDecision(
                lots=self._lots,
                contract_type=self._contract_type,
                initial_stop=snapshot.price + 1000,  # placeholder; StopPolicy overrides
                direction="short",
                metadata={"z": round(z, 2), "spread_mean": round(self._state.mean, 1)},
            )
        # Spread overextended downward → long the spread
        if z <= -self._entry_z:
            return EntryDecision(
                lots=self._lots,
                contract_type=self._contract_type,
                initial_stop=max(snapshot.price - 1000, 0.01),
                direction="long",
                metadata={"z": round(z, 2), "spread_mean": round(self._state.mean, 1)},
            )
        return None


class SpreadReversionStopPolicy(StopPolicy):
    """Z-score-based exit: take-profit at exit_z, stop at stop_z, or timeout."""

    def __init__(
        self,
        state: _SpreadState,
        entry_z: float = 2.0,
        exit_z: float = 0.3,
        stop_extra: float = 1.5,
        max_hold_bars: int = 180,
    ) -> None:
        self._state = state
        self._entry_z = entry_z
        self._exit_z = exit_z
        self._stop_z = entry_z + stop_extra
        self._max_hold = max_hold_bars
        self._bar_counts: dict[str, int] = {}

    def initial_stop(
        self, entry_price: float, direction: str, snapshot: MarketSnapshot,
    ) -> float:
        stop_dist = self._stop_z * self._state.std if self._state.std > 0 else 20.0
        if direction == "short":
            return entry_price + stop_dist
        return max(entry_price - stop_dist, 0.01)

    def update_stop(
        self,
        position: Position,
        snapshot: MarketSnapshot,
        high_history: deque[float],
    ) -> float:
        self._state.update(snapshot.price, ts=snapshot.timestamp)
        t = snapshot.timestamp.time()
        pid = position.position_id
        self._bar_counts[pid] = self._bar_counts.get(pid, 0) + 1
        # Force close: session end or max hold
        if in_force_close(t) or self._bar_counts[pid] >= self._max_hold:
            self._bar_counts.pop(pid, None)
            return snapshot.price
        if not self._state.ready:
            return position.stop_level
        z = self._state.z_score
        # Take profit: z reverted past exit threshold
        if position.direction == "short" and z <= self._exit_z:
            return snapshot.price
        if position.direction == "long" and z >= -self._exit_z:
            return snapshot.price
        # Stop loss: z extended further beyond stop threshold
        if position.direction == "short" and z >= self._stop_z:
            return snapshot.price
        if position.direction == "long" and z <= -self._stop_z:
            return snapshot.price
        return position.stop_level


def create_spread_reversion_engine(
    max_loss: float = 500_000.0,
    lots: float = 1.0,
    contract_type: str = "large",
    lookback: int = 60,
    entry_z: float = 2.0,
    exit_z: float = 0.3,
    stop_extra: float = 1.5,
    max_hold_bars: int = 180,
    min_std: float = 1.0,
) -> "PositionEngine":
    """Build a PositionEngine for spread mean-reversion.

    Designed to receive synthetic spread bars (price = R1 - R2).
    The facade auto-constructs these when STRATEGY_META has spread_legs.
    """
    from src.core.position_engine import PositionEngine

    state = _SpreadState(lookback=lookback, min_std=min_std)
    return PositionEngine(
        entry_policy=SpreadReversionEntryPolicy(
            state=state,
            entry_z=entry_z,
            lots=lots,
            contract_type=contract_type,
        ),
        add_policy=NoAddPolicy(),
        stop_policy=SpreadReversionStopPolicy(
            state=state,
            entry_z=entry_z,
            exit_z=exit_z,
            stop_extra=stop_extra,
            max_hold_bars=max_hold_bars,
        ),
        config=EngineConfig(max_loss=max_loss),
    )
