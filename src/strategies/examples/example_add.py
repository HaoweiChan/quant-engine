"""Example add (pyramid) policy: add to winners when profit exceeds ATR thresholds.

Customize this file to change WHEN the engine adds to existing positions.
The engine calls `should_add()` on every bar when a position is open.
Return an AddDecision to pyramid, or None to skip.
"""
from src.core.policies import AddPolicy
from src.core.types import (
    AddDecision,
    EngineState,
    MarketSignal,
    MarketSnapshot,
    PyramidConfig,
)


class MyAddPolicy(AddPolicy):
    """Add lots when floating profit exceeds the ATR trigger for the current level."""

    def __init__(self, config: PyramidConfig) -> None:
        self._config = config

    def should_add(
        self,
        snapshot: MarketSnapshot,
        signal: MarketSignal | None,
        engine_state: EngineState,
    ) -> AddDecision | None:
        if engine_state.mode == "halted":
            return None
        # Don't exceed max pyramid levels
        if engine_state.pyramid_level >= self._config.max_levels:
            return None
        if not engine_state.positions:
            return None

        entry_price = engine_state.positions[0].entry_price
        daily_atr = snapshot.atr["daily"]
        floating_profit = snapshot.price - entry_price
        trigger_idx = engine_state.pyramid_level - 1

        if trigger_idx < 0 or trigger_idx >= len(self._config.add_trigger_atr):
            return None

        # Check if profit exceeds the trigger threshold for this level
        trigger_threshold = self._config.add_trigger_atr[trigger_idx] * daily_atr
        if floating_profit < trigger_threshold:
            return None

        lot_spec = self._config.lot_schedule[engine_state.pyramid_level]
        total_lots = float(sum(lot_spec))
        return AddDecision(
            lots=total_lots,
            contract_type="large",
            move_existing_to_breakeven=True,
        )
