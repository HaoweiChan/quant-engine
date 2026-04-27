"""Intraday max-long 當沖 strategy for TAIFEX TX futures.

User intent (deployed manually on a Sinopac account with 當沖 buying-power
pre-enabled):

  1. At ``entry_time`` on the day session (default 08:50), buy the maximum
     number of TX contracts the account can support under the half-margin
     intraday rule. Sizing is computed inside the strategy from
     ``account.margin_available`` and the configured
     ``intraday_margin_per_contract`` (Sinopac-published 當沖 margin), then
     capped by ``position_cap`` so a stale margin number can't put on a
     runaway position.

  2. At ``half_exit_at`` (default 13:20), the runner — driven by
     ``STRATEGY_META["half_exit_at"]`` — sells half of the open lots.
     That leg books cleanly as 當沖 (open + close same day) at the broker.

  3. The remaining half is left open. Because
     ``STRATEGY_META["force_flat_at_session_end"] = False``, the
     ``LivePipelineManager`` 13:44 deterministic safety-net does NOT
     flatten this runner. Whatever Sinopac does to the unclosed 當沖 leg
     at end-of-session (auto-convert to overnight + re-check initial
     margin, or force-liquidate if cash is short) is accepted as part of
     the user's manual oversight stance.

The strategy emits no stops, no trailing logic, no add-on entries. It is
deliberately the simplest possible long-only single-shot.

Risk surface — read before deploying:
  * ``intraday_margin_per_contract`` is a config knob, not a broker
    lookup. If the published Sinopac figure changes mid-session and the
    strategy still divides by the stale value, the resulting buy will be
    rejected by Sinopac's pre-trade BP check (best case) or partially
    filled (worse). The ``position_cap`` is the second-line backstop.
  * The strategy intentionally violates the CLAUDE.md core invariant #7
    ("intraday strategies go flat at session close") for the kept half.
    The ``force_flat_at_session_end=False`` opt-out and this comment are
    the only places the violation is documented; the Risk Auditor will
    see both on the next audit pass.
"""
from __future__ import annotations

from collections import deque
from datetime import date, datetime, time
from typing import TYPE_CHECKING

from src.core.policies import EntryPolicy, NoAddPolicy, StopPolicy
from src.core.types import (
    METADATA_STRATEGY_SIZED,
    AccountState,
    EngineConfig,
    EngineState,
    EntryDecision,
    MarketSignal,
    MarketSnapshot,
    Position,
)
from src.strategies import HoldingPeriod, SignalTimeframe, StopArchitecture, StrategyCategory

if TYPE_CHECKING:
    from src.core.position_engine import PositionEngine


PARAM_SCHEMA: dict[str, dict] = {
    "intraday_margin_per_contract": {
        "type": "float", "default": 92_000.0, "min": 10_000.0, "max": 500_000.0,
        "description": "Sinopac 當沖 (intraday) initial margin per TX contract (NTD).",
    },
    "position_cap": {
        "type": "int", "default": 30, "min": 1, "max": 100,
        "description": "Hard cap on contracts per session (safety against stale margin).",
    },
    "entry_time": {
        "type": "str", "default": "08:50",
        "description": "First bar at or after this HH:MM triggers the open (Taipei time).",
    },
}

STRATEGY_META: dict = {
    "category": StrategyCategory.BREAKOUT,
    "signal_timeframe": SignalTimeframe.ONE_MIN,
    "holding_period": HoldingPeriod.SHORT_TERM,
    # Marked INTRADAY for the optimization-gate machinery, but the runner
    # honours the explicit `force_flat_at_session_end` flag below for the
    # actual session-end behaviour. Don't change this without re-reading
    # the runner's `_meta_force_flat` handling.
    "stop_architecture": StopArchitecture.INTRADAY,
    "tradeable_sessions": ["day"],
    "daytrade": True,
    "half_exit_at": "13:20",
    "force_flat_at_session_end": False,
    "description": (
        "當沖 max-long: buy max-allowed contracts at 08:50, sell half at "
        "13:20, ride the rest into Sinopac's end-of-session handling."
    ),
}


def _parse_hhmm(value: str | time) -> time:
    if isinstance(value, time):
        return value
    h, m = value.split(":", 1)
    return time(int(h), int(m))


class IntradayMaxLongEntryPolicy(EntryPolicy):
    """Single-shot long-only 當沖 entry sized to the account's intraday BP."""

    def __init__(
        self,
        intraday_margin_per_contract: float = 92_000.0,
        position_cap: int = 30,
        entry_time: str | time = "08:50",
        contract_type: str = "large",
    ) -> None:
        self._margin_per_contract = float(intraday_margin_per_contract)
        self._cap = int(position_cap)
        self._entry_time = _parse_hhmm(entry_time)
        self._contract_type = contract_type
        self._entered_on_day: date | None = None

    def reset_for_test(self) -> None:
        """Clear the per-day entry latch — used by unit tests."""
        self._entered_on_day = None

    def should_enter(
        self,
        snapshot: MarketSnapshot,
        signal: MarketSignal | None,
        engine_state: EngineState,
        account: AccountState | None = None,
    ) -> EntryDecision | None:
        if engine_state.mode == "halted":
            return None
        if engine_state.positions:
            return None
        ts = snapshot.timestamp
        # Only operate on the TAIFEX day session — the 當沖 half-margin
        # rule does not apply to the night session.
        if not (time(8, 45) <= ts.time() <= time(13, 30)):
            return None
        if ts.time() < self._entry_time:
            return None
        # One-shot per trading day. ``snapshot.timestamp.date()`` is good
        # enough for the day session (the night session never enters this
        # branch because of the in-day-session check above).
        today = ts.date()
        if self._entered_on_day == today:
            return None
        if account is None or account.margin_available <= 0:
            return None
        max_by_bp = int(account.margin_available // self._margin_per_contract)
        lots = min(max_by_bp, self._cap)
        if lots < 1:
            return None
        # No real stop — set the initial stop far enough below current
        # price that the PositionEngine's stop-check never fires. The
        # half-exit at 13:20 is the only programmatic close path.
        stop_floor = snapshot.price * 0.5
        self._entered_on_day = today
        return EntryDecision(
            lots=float(lots),
            contract_type=self._contract_type,
            initial_stop=stop_floor,
            direction="long",
            metadata={
                METADATA_STRATEGY_SIZED: True,
                "intraday_margin_per_contract": self._margin_per_contract,
                "max_by_bp": max_by_bp,
                "position_cap": self._cap,
            },
        )


class _NoopStopPolicy(StopPolicy):
    """Stop policy that never moves the stop — exits are runner-driven."""

    def initial_stop(
        self, entry_price: float, direction: str, snapshot: MarketSnapshot,
    ) -> float:
        return entry_price * 0.5 if direction == "long" else entry_price * 1.5

    def update_stop(
        self,
        position: Position,
        snapshot: MarketSnapshot,
        high_history: deque[float],
    ) -> float:
        return position.stop_level


def create_intraday_max_long_engine(
    intraday_margin_per_contract: float = 92_000.0,
    position_cap: int = 30,
    entry_time: str | time = "08:50",
    max_loss: float = 10_000_000.0,
    contract_type: str = "large",
) -> "PositionEngine":
    """Build a PositionEngine wired for the intraday max-long 當沖 strategy.

    ``max_loss`` is set high (10M NTD) so the engine's circuit-breaker
    does not fire before the user's manual oversight kicks in. The user
    has explicitly accepted that they own the kill-switch decision for
    this strategy ("I will stop it if I think it has to").

    The runner injects ``session_id`` as a kwarg; we don't accept it on
    the signature on purpose so ``registry.validate_schemas`` stays clean
    — the runner's TypeError-fallback path drops the kwarg and retries.
    """
    from src.core.position_engine import PositionEngine

    entry = IntradayMaxLongEntryPolicy(
        intraday_margin_per_contract=intraday_margin_per_contract,
        position_cap=position_cap,
        entry_time=entry_time,
        contract_type=contract_type,
    )
    return PositionEngine(
        entry_policy=entry,
        add_policy=NoAddPolicy(),
        stop_policy=_NoopStopPolicy(),
        # margin_limit=0.95: the strategy is intentionally near-max-leveraged
        # under 當沖 half-margin, so the engine's default 0.50 margin_safety
        # would trim the position immediately on any unrealised gain. We keep
        # the safety net at 0.95 to still catch a runaway, but don't let it
        # second-guess the user's "buy max" intent.
        config=EngineConfig(
            max_loss=max_loss,
            margin_limit=0.95,
            disaster_stop_enabled=False,
        ),
    )
