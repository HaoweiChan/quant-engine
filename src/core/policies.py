"""Trading policy ABCs and concrete implementations.

Policies answer "what to do"; the engine answers "how to execute it."
"""
from abc import ABC, abstractmethod
from collections import deque

from src.core.types import (
    AddDecision,
    EngineState,
    EntryDecision,
    MarketSignal,
    MarketSnapshot,
    Position,
    PyramidConfig,
)


class EntryPolicy(ABC):
    @abstractmethod
    def should_enter(
        self,
        snapshot: MarketSnapshot,
        signal: MarketSignal | None,
        engine_state: EngineState,
    ) -> EntryDecision | None: ...


class AddPolicy(ABC):
    @abstractmethod
    def should_add(
        self,
        snapshot: MarketSnapshot,
        signal: MarketSignal | None,
        engine_state: EngineState,
    ) -> AddDecision | None: ...


class StopPolicy(ABC):
    @abstractmethod
    def initial_stop(
        self, entry_price: float, direction: str, snapshot: MarketSnapshot,
    ) -> float: ...

    @abstractmethod
    def update_stop(
        self,
        position: Position,
        snapshot: MarketSnapshot,
        high_history: deque[float],
    ) -> float: ...


class PyramidEntryPolicy(EntryPolicy):
    def __init__(self, config: PyramidConfig) -> None:
        self._config = config

    def should_enter(
        self,
        snapshot: MarketSnapshot,
        signal: MarketSignal | None,
        engine_state: EngineState,
    ) -> EntryDecision | None:
        if engine_state.mode in ("halted", "rule_only"):
            return None
        if signal is None:
            return None
        if signal.direction_conf <= self._config.entry_conf_threshold:
            return None
        if signal.direction <= 0:
            return None

        daily_atr = snapshot.atr["daily"]
        lot_spec = self._config.lot_schedule[0]
        total_lots = float(sum(lot_spec))
        stop_distance = self._config.stop_atr_mult * daily_atr

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


class PyramidAddPolicy(AddPolicy):
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


class ChandelierStopPolicy(StopPolicy):
    def __init__(self, config: PyramidConfig) -> None:
        self._config = config

    def initial_stop(
        self, entry_price: float, direction: str, snapshot: MarketSnapshot,
    ) -> float:
        daily_atr = snapshot.atr["daily"]
        distance = self._config.stop_atr_mult * daily_atr
        if direction == "short":
            return entry_price + distance
        return entry_price - distance

    def update_stop(
        self,
        position: Position,
        snapshot: MarketSnapshot,
        high_history: deque[float],
    ) -> float:
        daily_atr = snapshot.atr["daily"]
        new_stop = position.stop_level

        if position.direction == "long":
            floating_profit = snapshot.price - position.entry_price
            if floating_profit > daily_atr and position.stop_level < position.entry_price:
                new_stop = position.entry_price
            if high_history:
                chandelier = max(high_history) - self._config.trail_atr_mult * daily_atr
                new_stop = max(new_stop, chandelier)
        else:
            floating_profit = position.entry_price - snapshot.price
            if floating_profit > daily_atr and position.stop_level > position.entry_price:
                new_stop = position.entry_price
            if high_history:
                chandelier = min(high_history) + self._config.trail_atr_mult * daily_atr
                new_stop = min(new_stop, chandelier)

        return new_stop


class NoAddPolicy(AddPolicy):
    def should_add(
        self,
        snapshot: MarketSnapshot,
        signal: MarketSignal | None,
        engine_state: EngineState,
    ) -> AddDecision | None:
        return None
