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
from src.indicators import RollingZScore, compose_param_schema
from src.strategies import HoldingPeriod, SignalTimeframe, StopArchitecture, StrategyCategory
from src.strategies._session_utils import in_force_close

if TYPE_CHECKING:
    from src.core.position_engine import PositionEngine


_INDICATOR_PARAMS = compose_param_schema({
    "lookback": (RollingZScore, "period"),
    "min_std": (RollingZScore, "min_std"),
})
# Override defaults / bounds to match 1-min spread semantics.
_INDICATOR_PARAMS["lookback"]["default"] = 60
_INDICATOR_PARAMS["lookback"]["min"] = 20
_INDICATOR_PARAMS["lookback"]["max"] = 200
_INDICATOR_PARAMS["lookback"]["description"] = "Rolling window for spread mean/std (1-min bars)."
_INDICATOR_PARAMS["min_std"]["default"] = 1.0
_INDICATOR_PARAMS["min_std"]["min"] = 0.1
_INDICATOR_PARAMS["min_std"]["max"] = 5.0
_INDICATOR_PARAMS["min_std"]["description"] = "Minimum spread std to consider the spread active."

PARAM_SCHEMA: dict[str, dict] = {
    **_INDICATOR_PARAMS,
    "entry_z": {
        "type": "float", "default": 2.0, "min": 1.0, "max": 4.0,
        "description": "Z-score threshold to enter mean-reversion trade.",
    },
    "exit_z": {
        "type": "float", "default": 0.3, "min": 0.0, "max": 1.5,
        "description": "Z-score threshold to take profit (near mean).",
    },
    "stop_extra": {
        "type": "float", "default": 1.5, "min": 0.5, "max": 3.0,
        "description": "Additional z beyond entry_z for stop-loss (stop_z = entry_z + stop_extra).",
    },
    "max_hold_bars": {
        "type": "int", "default": 180, "min": 30, "max": 600,
        "description": "Max bars to hold before time-exit (3h default).",
    },
}

# Contract-roll gap threshold (points): calendar spread levels jump on roll.
_SPREAD_JUMP_THRESHOLD = 40.0

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


class SpreadReversionEntryPolicy(EntryPolicy):
    """Enter when spread z-score exceeds entry_z threshold."""

    def __init__(
        self,
        z_score: RollingZScore,
        entry_z: float = 2.0,
    ) -> None:
        self._z = z_score
        self._entry_z = entry_z

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
        self._z.update(snapshot.price, timestamp=snapshot.timestamp)
        if not self._z.ready:
            return None
        z = self._z.value
        # Spread overextended upward → short the spread (expect reversion down)
        if z >= self._entry_z:
            return EntryDecision(
                lots=1,
                contract_type="large",
                initial_stop=snapshot.price + 1000,  # placeholder; StopPolicy overrides
                direction="short",
                metadata={"z": round(z, 2), "spread_mean": round(self._z.mean, 1)},
            )
        # Spread overextended downward → long the spread
        if z <= -self._entry_z:
            return EntryDecision(
                lots=1,
                contract_type="large",
                initial_stop=max(snapshot.price - 1000, 0.01),
                direction="long",
                metadata={"z": round(z, 2), "spread_mean": round(self._z.mean, 1)},
            )
        return None


class SpreadReversionStopPolicy(StopPolicy):
    """Z-score-based exit: take-profit at exit_z, stop at stop_z, or timeout."""

    def __init__(
        self,
        z_score: RollingZScore,
        entry_z: float = 2.0,
        exit_z: float = 0.3,
        stop_extra: float = 1.5,
        max_hold_bars: int = 180,
    ) -> None:
        self._z = z_score
        self._entry_z = entry_z
        self._exit_z = exit_z
        self._stop_z = entry_z + stop_extra
        self._max_hold = max_hold_bars
        self._bar_counts: dict[str, int] = {}

    def initial_stop(
        self, entry_price: float, direction: str, snapshot: MarketSnapshot,
    ) -> float:
        stop_dist = self._stop_z * self._z.std if self._z.std > 0 else 20.0
        if direction == "short":
            return entry_price + stop_dist
        return max(entry_price - stop_dist, 0.01)

    def update_stop(
        self,
        position: Position,
        snapshot: MarketSnapshot,
        high_history: deque[float],
    ) -> float:
        self._z.update(snapshot.price, timestamp=snapshot.timestamp)
        t = snapshot.timestamp.time()
        pid = position.position_id
        self._bar_counts[pid] = self._bar_counts.get(pid, 0) + 1
        # Force close: session end or max hold
        if in_force_close(t) or self._bar_counts[pid] >= self._max_hold:
            self._bar_counts.pop(pid, None)
            return snapshot.price
        if not self._z.ready:
            return position.stop_level
        z = self._z.value
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

    z_score = RollingZScore(
        period=lookback,
        min_std=min_std,
        jump_threshold=_SPREAD_JUMP_THRESHOLD,
    )
    return PositionEngine(
        entry_policy=SpreadReversionEntryPolicy(
            z_score=z_score,
            entry_z=entry_z,
        ),
        add_policy=NoAddPolicy(),
        stop_policy=SpreadReversionStopPolicy(
            z_score=z_score,
            entry_z=entry_z,
            exit_z=exit_z,
            stop_extra=stop_extra,
            max_hold_bars=max_hold_bars,
        ),
        config=EngineConfig(max_loss=max_loss),
    )
