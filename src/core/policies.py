"""Trading policy ABCs and concrete implementations.

Policies answer "what to do"; the engine answers "how to execute it."
"""
import structlog
from abc import ABC, abstractmethod
from collections import deque

from src.core.types import (
    AccountState,
    AddDecision,
    EngineState,
    EntryDecision,
    MarketSignal,
    MarketSnapshot,
    Position,
    PyramidConfig,
)

logger = structlog.get_logger(__name__)


class EntryPolicy(ABC):
    @abstractmethod
    def should_enter(
        self,
        snapshot: MarketSnapshot,
        signal: MarketSignal | None,
        engine_state: EngineState,
        account: AccountState | None = None,
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
        logger.info(
            "pyramid_entry_policy_initialized",
            long_only_compat_mode=config.long_only_compat_mode,
            max_equity_risk_pct=config.max_equity_risk_pct,
        )

    def should_enter(
        self,
        snapshot: MarketSnapshot,
        signal: MarketSignal | None,
        engine_state: EngineState,
        account: AccountState | None = None,
    ) -> EntryDecision | None:
        if engine_state.mode in ("halted", "rule_only"):
            logger.debug("entry_policy_rejected", reason="engine_mode_block", mode=engine_state.mode)
            return None
        if signal is None:
            logger.debug("entry_policy_rejected", reason="missing_signal")
            return None
        if signal.direction_conf <= self._config.entry_conf_threshold:
            logger.debug(
                "entry_policy_rejected",
                reason="low_confidence",
                direction_conf=signal.direction_conf,
            )
            return None
        if abs(signal.direction) < 1e-9:
            logger.debug("entry_policy_rejected", reason="flat_direction")
            return None
        if self._config.long_only_compat_mode and signal.direction < 0:
            logger.info("entry_policy_rejected", reason="long_only_compat_mode")
            return None

        daily_atr = snapshot.atr["daily"]
        stop_distance = self._config.stop_atr_mult * daily_atr
        if stop_distance <= 0:
            return None
        direction = "long" if signal.direction > 0 else "short"
        risk_per_contract = stop_distance * snapshot.point_value
        if risk_per_contract <= 0:
            return None

        lot_spec = self._config.lot_schedule[0]
        schedule_lots = float(sum(lot_spec))
        if account is None:
            equity_risk_lots = schedule_lots
            logger.info("entry_policy_sizing_fallback", reason="missing_account_context")
        else:
            equity_risk_lots = (account.equity * self._config.max_equity_risk_pct) / risk_per_contract
        static_cap_lots = self._config.max_loss / risk_per_contract
        total_lots = min(schedule_lots, equity_risk_lots, static_cap_lots)
        if total_lots < snapshot.min_lot:
            logger.info(
                "entry_policy_rejected",
                reason="below_min_lot",
                total_lots=total_lots,
                min_lot=snapshot.min_lot,
            )
            return None

        stop_level = (
            snapshot.price - stop_distance
            if direction == "long"
            else snapshot.price + stop_distance
        )
        return EntryDecision(
            lots=total_lots,
            contract_type="large",
            initial_stop=stop_level,
            direction=direction,
            metadata={
                "signal_conf": signal.direction_conf,
                "equity_risk_lots": equity_risk_lots,
                "static_cap_lots": static_cap_lots,
                "compat_mode": self._config.long_only_compat_mode,
            },
        )


class PyramidAddPolicy(AddPolicy):
    def __init__(self, config: PyramidConfig) -> None:
        self._config = config
        self._price_history: deque[float] = deque(maxlen=config.internal_atr_len + 1)
        self._last_add_price: float | None = None
        self._prev_pyramid_level: int = 0

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
            self._last_add_price = None
            self._prev_pyramid_level = 0
            return None

        # Detect stop-out: pyramid level dropped since last call
        if engine_state.pyramid_level < self._prev_pyramid_level:
            # Reset reference to highest remaining position's entry
            self._last_add_price = engine_state.positions[-1].entry_price
        self._prev_pyramid_level = engine_state.pyramid_level

        direction = engine_state.positions[0].direction

        # Configurable ATR key with internal fallback
        self._price_history.append(snapshot.price)
        atr = snapshot.atr.get(self._config.atr_key)
        if atr is None or atr <= 0:
            n = len(self._price_history)
            if n > self._config.internal_atr_len:
                prices = list(self._price_history)
                diffs = [abs(prices[i] - prices[i - 1]) for i in range(1, n)]
                atr = sum(diffs) / len(diffs) * 1.6
            else:
                return None

        # Reference price: last add entry (or base entry for first add)
        ref_price = self._last_add_price or engine_state.positions[0].entry_price
        if direction == "long":
            floating_profit = snapshot.price - ref_price
        else:
            floating_profit = ref_price - snapshot.price

        trigger_idx = engine_state.pyramid_level - 1
        if trigger_idx < 0 or trigger_idx >= len(self._config.add_trigger_atr):
            return None

        trigger_threshold = self._config.add_trigger_atr[trigger_idx] * atr
        if floating_profit < trigger_threshold:
            return None

        # Gamma-based sizing when configured, else lot_schedule
        if self._config.gamma is not None:
            level = engine_state.pyramid_level
            lots = self._config.base_lots * (self._config.gamma ** level)
        else:
            lot_spec = self._config.lot_schedule[engine_state.pyramid_level]
            lots = float(sum(lot_spec))

        self._last_add_price = snapshot.price
        return AddDecision(
            lots=lots,
            contract_type="large",
            move_existing_to_breakeven=True,
        )

    def reset(self) -> None:
        """Clear internal state at session boundary."""
        self._price_history.clear()


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
