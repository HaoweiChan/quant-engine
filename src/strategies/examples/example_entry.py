"""Example entry policy: Pyramid entry based on model signal confidence.

Customize this file to change WHEN and HOW the engine opens new positions.
The engine calls `should_enter()` on every bar. Return an EntryDecision
to open a position, or None to skip.
"""
from src.core.policies import EntryPolicy
from src.core.types import (
    EngineState,
    EntryDecision,
    MarketSignal,
    MarketSnapshot,
    PyramidConfig,
)


class MyEntryPolicy(EntryPolicy):
    """Enter long when model confidence exceeds threshold and signal is bullish."""

    def __init__(self, config: PyramidConfig) -> None:
        self._config = config

    def should_enter(
        self,
        snapshot: MarketSnapshot,
        signal: MarketSignal | None,
        engine_state: EngineState,
    ) -> EntryDecision | None:
        # Skip if engine is halted or in rule-only mode
        if engine_state.mode in ("halted", "rule_only"):
            return None
        if signal is None:
            return None
        # Only enter when model confidence is high enough
        if signal.direction_conf <= self._config.entry_conf_threshold:
            return None
        # Only enter on bullish signals
        if signal.direction <= 0:
            return None

        daily_atr = snapshot.atr["daily"]
        lot_spec = self._config.lot_schedule[0]
        total_lots = float(sum(lot_spec))
        stop_distance = self._config.stop_atr_mult * daily_atr

        # Scale down lots if risk exceeds max_loss
        max_loss_if_stopped = total_lots * stop_distance * snapshot.point_value
        if max_loss_if_stopped > self._config.max_loss:
            scaled_lots = self._config.max_loss / (stop_distance * snapshot.point_value)
            if scaled_lots < snapshot.min_lot:
                return None
            total_lots = scaled_lots

        stop_level = snapshot.price - stop_distance
        return EntryDecision(
            lots=total_lots,
            contract_type="large",
            initial_stop=stop_level,
            direction="long",
            metadata={"signal_conf": signal.direction_conf},
        )
