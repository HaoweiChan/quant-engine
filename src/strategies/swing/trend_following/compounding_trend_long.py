"""Compounding trend-following long — daily-bar reference scaffold.

Long-only TAIFEX index-futures strategy that scales contract count to free margin in
trending bull regimes and applies a mechanical ATR stop to cap drawdowns. The
margin-scaling mechanic was inspired by PTT Stock Board post M.1771684247 (a retail
trader who grew NT$7.4M to NT$385M over eight months in 2025 by pyramiding lots
whenever free margin allowed and cutting lots when a sell-off threatened the
maintenance threshold). This implementation tightens the discretionary cut rule into
an ATR-based mechanical stop so the worst case is bounded rather than open-ended.

Position sizing
---------------
The strategy is **account-aware**: initial entry consumes ~``initial_margin_pct`` of
free margin at the time of entry, and each subsequent add consumes
``add_margin_fraction`` of *current* free margin. The standalone simulator at
``experiment/scripts/compounding_trend_long_replication.py`` does the same math
in its while-loop. Without this sizing the strategy emits ``lots=1.0`` per snapshot,
which collapses the compounding edge that motivated the PTT result in the first
place — a single TX lot at NT$22k underlying is < 7% of a NT$7.4M account.

A shared ``_AccountHub`` mirrors the ``vol_managed_bnh._OverlayHub`` pattern:
``EntryPolicy`` receives ``AccountState`` and stashes it on the hub; ``AddPolicy``
(which has no ``account`` parameter in the ABC) reads from the hub to size adds.

Status
------
This file is a *reference scaffold* — daily-bar logic that documents the policy
shape and runs end-to-end via the MCP backtest loop. The production multi-timeframe
strategy is ``compounding_trend_long_mtf``. Do not promote this file past L0.
"""
from __future__ import annotations

from collections import deque
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
from src.strategies import (
    HoldingPeriod,
    SignalTimeframe,
    StopArchitecture,
    StrategyCategory,
)

if TYPE_CHECKING:
    from src.core.position_engine import PositionEngine


PARAM_SCHEMA: dict[str, dict] = {
    "stop_atr_mult": {
        "type": "float", "default": 1.5, "min": 0.5, "max": 5.0,
        "description": "ATR multiplier for the daily trailing stop.",
    },
    "max_pyramid_levels": {
        "type": "int", "default": 50, "min": 1, "max": 500,
        "description": "Hard cap on pyramid depth (number of consecutive AddDecisions).",
    },
    "initial_margin_pct": {
        "type": "float", "default": 0.90, "min": 0.05, "max": 0.97,
        "description": "Fraction of free margin to deploy on the initial entry.",
    },
    "add_margin_fraction": {
        "type": "float", "default": 0.50, "min": 0.05, "max": 0.95,
        "description": "Fraction of current free margin to deploy per pyramid add.",
    },
}

STRATEGY_META: dict = {
    "category": StrategyCategory.TREND_FOLLOWING,
    "signal_timeframe": SignalTimeframe.DAILY,
    "holding_period": HoldingPeriod.SWING,
    "stop_architecture": StopArchitecture.SWING,
    "expected_duration_minutes": (10080, 40320),
    "tradeable_sessions": ["day", "night"],
    "description": (
        "Long-only daily-bar trend follower with margin-scaled pyramid and ATR stop "
        "(reference scaffold; production strategy is compounding_trend_long_mtf)."
    ),
}


def _safe_atr(snapshot: MarketSnapshot, fallback_pct: float) -> float:
    atr_map = getattr(snapshot, "atr", None) or {}
    atr = atr_map.get("daily", 0.0) if isinstance(atr_map, dict) else 0.0
    if atr and atr > 0:
        return float(atr)
    return float(snapshot.price) * fallback_pct


def _margin_per_lot(snapshot: MarketSnapshot, default: float = 477_000.0) -> float:
    """Resolve initial margin per lot from snapshot; fall back to TX default."""
    mpu = getattr(snapshot, "margin_per_unit", None)
    if mpu and mpu > 0:
        return float(mpu)
    specs = getattr(snapshot, "contract_specs", None)
    if specs is not None:
        m = getattr(specs, "margin_initial", None)
        if m and m > 0:
            return float(m)
    return default


def _affordable_lots(margin_available: float, margin_per_lot: float, fraction: float) -> float:
    """Integer lots fundable from a fraction of free margin."""
    if margin_per_lot <= 0:
        return 0.0
    n = int(max(0.0, margin_available) * fraction / margin_per_lot)
    return float(n)


class _AccountHub:
    """Last-seen AccountState bridge between entry and add policies.

    AddPolicy.should_add does not receive AccountState by ABC design; the hub
    lets the entry policy stash it once per snapshot so the add policy can read
    a fresh copy. Same pattern as vol_managed_bnh._OverlayHub.
    """

    def __init__(self) -> None:
        self.account: AccountState | None = None

    def update(self, account: AccountState | None) -> None:
        if account is not None:
            self.account = account


class CompoundingTrendLongEntry(EntryPolicy):
    """Open a base long position sized to ``initial_margin_pct`` of free margin."""

    def __init__(
        self, hub: _AccountHub, stop_atr_mult: float, initial_margin_pct: float,
    ) -> None:
        self._hub = hub
        self._stop_atr_mult = stop_atr_mult
        self._initial_margin_pct = initial_margin_pct

    def should_enter(
        self,
        snapshot: MarketSnapshot,
        signal: MarketSignal | None,
        engine_state: EngineState,
        account: AccountState | None = None,
    ) -> EntryDecision | None:
        self._hub.update(account)
        if engine_state.mode == "halted" or engine_state.positions:
            return None
        if account is None or account.equity <= 0:
            return None

        mpl = _margin_per_lot(snapshot)
        lots = _affordable_lots(account.margin_available, mpl, self._initial_margin_pct)
        if lots < 1.0:
            return None

        atr = _safe_atr(snapshot, fallback_pct=0.02)
        stop_distance = self._stop_atr_mult * atr
        return EntryDecision(
            lots=lots,
            contract_type="large",
            initial_stop=snapshot.price - stop_distance,
            direction="long",
            metadata={
                "reason": "trend_entry",
                "atr": atr,
                "margin_per_lot": mpl,
                METADATA_STRATEGY_SIZED: True,
            },
        )


class CompoundingTrendLongAdd(AddPolicy):
    """Pyramid using a fraction of *current* free margin per add."""

    def __init__(
        self, hub: _AccountHub, max_pyramid_levels: int, add_margin_fraction: float,
    ) -> None:
        self._hub = hub
        self._max_pyramid_levels = max_pyramid_levels
        self._add_margin_fraction = add_margin_fraction

    def should_add(
        self,
        snapshot: MarketSnapshot,
        signal: MarketSignal | None,
        engine_state: EngineState,
    ) -> AddDecision | None:
        if engine_state.mode == "halted" or not engine_state.positions:
            return None
        if engine_state.pyramid_level >= self._max_pyramid_levels:
            return None

        account = self._hub.account
        if account is None or account.margin_available <= 0:
            return None

        # Add ONE lot per snapshot when free margin can fund it. The pyramid
        # builds from many sequential 1-lot adds; ``add_margin_fraction``
        # scales the headroom threshold so 0.50 → require 2 lots' worth of
        # free margin per add (more conservative as positions grow).
        mpl = _margin_per_lot(snapshot)
        threshold = mpl / max(self._add_margin_fraction, 0.05)
        if account.margin_available < threshold:
            return None

        return AddDecision(
            lots=1.0,
            contract_type="large",
            move_existing_to_breakeven=False,
            metadata={
                "reason": "margin_available",
                "margin_per_lot": mpl,
                METADATA_STRATEGY_SIZED: True,
            },
        )


class CompoundingTrendLongStop(StopPolicy):
    def __init__(self, stop_atr_mult: float) -> None:
        self._stop_atr_mult = stop_atr_mult

    def initial_stop(
        self, entry_price: float, direction: str, snapshot: MarketSnapshot,
    ) -> float:
        atr = _safe_atr(snapshot, fallback_pct=0.02)
        distance = self._stop_atr_mult * atr
        return entry_price - distance if direction == "long" else entry_price + distance

    def update_stop(
        self,
        position: Position,
        snapshot: MarketSnapshot,
        high_history: deque[float],
    ) -> float:
        atr = _safe_atr(snapshot, fallback_pct=0.02)
        high_water = max(high_history) if high_history else snapshot.price
        distance = self._stop_atr_mult * atr
        if position.direction == "long":
            return max(position.stop_level, high_water - distance)
        return min(position.stop_level, high_water + distance)


def create_compounding_trend_long_engine(
    max_loss: float = 1_000_000.0,
    stop_atr_mult: float = 1.5,
    max_pyramid_levels: int = 50,
    initial_margin_pct: float = 0.90,
    add_margin_fraction: float = 0.50,
    session_id: str | None = None,  # noqa: ARG001 - accepted for runner parity
) -> PositionEngine:
    """Build a PositionEngine wired with the account-aware compounding_trend_long."""
    from src.core.position_engine import PositionEngine

    hub = _AccountHub()
    return PositionEngine(
        entry_policy=CompoundingTrendLongEntry(
            hub=hub, stop_atr_mult=stop_atr_mult, initial_margin_pct=initial_margin_pct,
        ),
        add_policy=CompoundingTrendLongAdd(
            hub=hub, max_pyramid_levels=max_pyramid_levels,
            add_margin_fraction=add_margin_fraction,
        ),
        stop_policy=CompoundingTrendLongStop(stop_atr_mult=stop_atr_mult),
        config=EngineConfig(
            max_loss=max_loss,
            margin_limit=0.97,  # match the strategy's intent (PTT trader sat at ~110% margin coefficient)
            trail_lookback=22,
            min_hold_lots=0.0,
        ),
    )
