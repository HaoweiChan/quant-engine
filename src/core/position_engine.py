from collections import deque
from typing import Literal

from src.core.policies import (
    AddPolicy,
    ChandelierStopPolicy,
    EntryPolicy,
    PyramidAddPolicy,
    PyramidEntryPolicy,
    StopPolicy,
)
from src.core.types import (
    AccountState,
    AddDecision,
    EngineConfig,
    EngineState,
    EntryDecision,
    MarketSignal,
    MarketSnapshot,
    Order,
    Position,
    PyramidConfig,
)


class PositionEngine:
    def __init__(
        self,
        entry_policy: EntryPolicy,
        add_policy: AddPolicy,
        stop_policy: StopPolicy,
        config: EngineConfig,
    ) -> None:
        self._entry_policy = entry_policy
        self._add_policy = add_policy
        self._stop_policy = stop_policy
        self._config = config
        self._positions: list[Position] = []
        self._mode: Literal["model_assisted", "rule_only", "halted"] = "model_assisted"
        self._high_history: deque[float] = deque(maxlen=config.trail_lookback)

    # -- public API --

    def on_snapshot(
        self,
        snapshot: MarketSnapshot,
        signal: MarketSignal | None = None,
        account: AccountState | None = None,
    ) -> list[Order]:
        self._high_history.append(snapshot.price)
        orders: list[Order] = []

        # Priority 1: stop-loss check
        orders.extend(self._check_stops(snapshot))

        # Priority 2: trailing stop update (ratchet, no orders emitted)
        self._update_trailing_stops(snapshot)

        # Priority 3: margin safety
        if account is not None:
            orders.extend(self._check_margin_safety(snapshot, account))

        effective_signal = signal if self._mode == "model_assisted" else None
        state = self.get_state()

        # Priority 4: entry signal (delegate to policy)
        if not self._positions and self._mode != "halted":
            decision = self._entry_policy.should_enter(snapshot, effective_signal, state)
            if decision is not None:
                orders.extend(self._execute_entry(decision, snapshot))

        # Priority 5: add position (delegate to policy, engine gates on margin)
        if self._positions and self._mode != "halted":
            if account is not None and account.margin_ratio > self._config.margin_limit * 0.8:
                pass  # margin headroom insufficient, skip add
            else:
                add_state = self.get_state()
                add_decision = self._add_policy.should_add(snapshot, effective_signal, add_state)
                if add_decision is not None:
                    orders.extend(self._execute_add(add_decision, snapshot))

        # Priority 6: circuit breaker
        orders.extend(self._check_circuit_breaker(snapshot, account))

        return orders

    def set_mode(self, mode: str) -> None:
        if mode not in ("model_assisted", "rule_only", "halted"):
            raise ValueError(f"Invalid mode: {mode}")
        self._mode = mode  # type: ignore[assignment]

    def get_state(self) -> EngineState:
        pnl = self._total_unrealized_pnl(None)
        return EngineState(
            positions=tuple(self._positions),
            pyramid_level=len(self._positions),
            mode=self._mode,
            total_unrealized_pnl=pnl,
        )

    # -- private: stop-loss check (Priority 1) --

    def _check_stops(self, snapshot: MarketSnapshot) -> list[Order]:
        orders: list[Order] = []
        triggered: list[int] = []
        for i, pos in enumerate(self._positions):
            hit = (
                snapshot.price <= pos.stop_level
                if pos.direction == "long"
                else snapshot.price >= pos.stop_level
            )
            if hit:
                reason = "trailing_stop" if self._is_trailing(pos, snapshot) else "stop_loss"
                close_side = "sell" if pos.direction == "long" else "buy"
                orders.append(
                    Order(
                        order_type="market",
                        side=close_side,
                        symbol=snapshot.contract_specs.symbol,
                        contract_type=pos.contract_type,
                        lots=pos.lots,
                        price=None,
                        stop_price=None,
                        reason=reason,
                        metadata={"pyramid_level": pos.pyramid_level},
                    )
                )
                triggered.append(i)
        for i in reversed(triggered):
            self._positions.pop(i)
        return orders

    def _is_trailing(self, pos: Position, snapshot: MarketSnapshot) -> bool:
        """A stop is 'trailing' if it has moved past the initial stop level."""
        initial = self._stop_policy.initial_stop(pos.entry_price, pos.direction, snapshot)
        if pos.direction == "long":
            return pos.stop_level > initial
        return pos.stop_level < initial

    # -- private: trailing stop update (Priority 2) --

    def _update_trailing_stops(self, snapshot: MarketSnapshot) -> None:
        if not self._positions:
            return
        updated: list[Position] = []
        for pos in self._positions:
            new_stop = self._stop_policy.update_stop(pos, snapshot, self._high_history)
            # Ratchet: stops only move favorably
            if pos.direction == "long":
                new_stop = max(new_stop, pos.stop_level)
            else:
                new_stop = min(new_stop, pos.stop_level)
            if new_stop != pos.stop_level:
                updated.append(Position(
                    entry_price=pos.entry_price,
                    lots=pos.lots,
                    contract_type=pos.contract_type,
                    stop_level=new_stop,
                    pyramid_level=pos.pyramid_level,
                    entry_timestamp=pos.entry_timestamp,
                    direction=pos.direction,
                ))
            else:
                updated.append(pos)
        self._positions = updated

    # -- private: margin safety (Priority 3) --

    def _check_margin_safety(
        self, snapshot: MarketSnapshot, account: AccountState
    ) -> list[Order]:
        orders: list[Order] = []
        if account.margin_ratio > self._config.margin_limit and self._positions:
            pos = self._positions[-1]
            reduce_lots = max(pos.lots / 2, snapshot.min_lot)
            reduce_lots = min(reduce_lots, pos.lots)
            close_side = "sell" if pos.direction == "long" else "buy"
            orders.append(
                Order(
                    order_type="market",
                    side=close_side,
                    symbol=snapshot.contract_specs.symbol,
                    contract_type=pos.contract_type,
                    lots=reduce_lots,
                    price=None,
                    stop_price=None,
                    reason="margin_safety",
                )
            )
        return orders

    # -- private: execute entry decision --

    def _execute_entry(
        self, decision: EntryDecision, snapshot: MarketSnapshot
    ) -> list[Order]:
        entry_side = "buy" if decision.direction == "long" else "sell"
        position = Position(
            entry_price=snapshot.price,
            lots=decision.lots,
            contract_type=decision.contract_type,
            stop_level=decision.initial_stop,
            pyramid_level=0,
            entry_timestamp=snapshot.timestamp,
            direction=decision.direction,
        )
        self._positions.append(position)
        return [
            Order(
                order_type="market",
                side=entry_side,
                symbol=snapshot.contract_specs.symbol,
                contract_type=decision.contract_type,
                lots=decision.lots,
                price=None,
                stop_price=None,
                reason="entry",
                metadata=decision.metadata,
            )
        ]

    # -- private: execute add decision --

    def _execute_add(
        self, decision: AddDecision, snapshot: MarketSnapshot
    ) -> list[Order]:
        if not self._positions:
            return []
        direction = self._positions[0].direction
        entry_side = "buy" if direction == "long" else "sell"

        if decision.move_existing_to_breakeven:
            updated: list[Position] = []
            for pos in self._positions:
                needs_move = (
                    (pos.direction == "long" and pos.stop_level < pos.entry_price)
                    or (pos.direction == "short" and pos.stop_level > pos.entry_price)
                )
                if needs_move:
                    updated.append(Position(
                        entry_price=pos.entry_price,
                        lots=pos.lots,
                        contract_type=pos.contract_type,
                        stop_level=pos.entry_price,
                        pyramid_level=pos.pyramid_level,
                        entry_timestamp=pos.entry_timestamp,
                        direction=pos.direction,
                    ))
                else:
                    updated.append(pos)
            self._positions = updated

        new_stop = self._stop_policy.initial_stop(snapshot.price, direction, snapshot)
        pyramid_level = len(self._positions)
        new_position = Position(
            entry_price=snapshot.price,
            lots=decision.lots,
            contract_type=decision.contract_type,
            stop_level=new_stop,
            pyramid_level=pyramid_level,
            entry_timestamp=snapshot.timestamp,
            direction=direction,
        )
        self._positions.append(new_position)

        return [
            Order(
                order_type="market",
                side=entry_side,
                symbol=snapshot.contract_specs.symbol,
                contract_type=decision.contract_type,
                lots=decision.lots,
                price=None,
                stop_price=None,
                reason=f"add_level_{pyramid_level + 1}",
                metadata={"pyramid_level": pyramid_level + 1},
            )
        ]

    # -- private: circuit breaker (Priority 6) --

    def _check_circuit_breaker(
        self, snapshot: MarketSnapshot, account: AccountState | None
    ) -> list[Order]:
        if not self._positions:
            return []
        drawdown = self._estimate_drawdown(snapshot, account)
        if drawdown < self._config.max_loss:
            return []

        orders: list[Order] = []
        for pos in self._positions:
            close_side = "sell" if pos.direction == "long" else "buy"
            orders.append(
                Order(
                    order_type="market",
                    side=close_side,
                    symbol=snapshot.contract_specs.symbol,
                    contract_type=pos.contract_type,
                    lots=pos.lots,
                    price=None,
                    stop_price=None,
                    reason="circuit_breaker",
                    metadata={"pyramid_level": pos.pyramid_level},
                )
            )
        self._positions.clear()
        self._mode = "halted"
        return orders

    # -- private: helpers --

    def _estimate_drawdown(
        self, snapshot: MarketSnapshot, account: AccountState | None
    ) -> float:
        if account is not None:
            return account.drawdown_pct * account.equity
        total_loss = 0.0
        for pos in self._positions:
            if pos.direction == "long":
                pnl = (snapshot.price - pos.entry_price) * pos.lots * snapshot.point_value
            else:
                pnl = (pos.entry_price - snapshot.price) * pos.lots * snapshot.point_value
            if pnl < 0:
                total_loss += abs(pnl)
        return total_loss

    def _total_unrealized_pnl(self, snapshot: MarketSnapshot | None) -> float:
        if snapshot is None:
            return 0.0
        total = 0.0
        for pos in self._positions:
            if pos.direction == "long":
                total += (snapshot.price - pos.entry_price) * pos.lots * snapshot.point_value
            else:
                total += (pos.entry_price - snapshot.price) * pos.lots * snapshot.point_value
        return total


def create_pyramid_engine(config: PyramidConfig) -> PositionEngine:
    """Factory: build a PositionEngine with pyramid strategy policies."""
    engine_config = EngineConfig(
        max_loss=config.max_loss,
        margin_limit=config.margin_limit,
        trail_lookback=config.trail_lookback,
    )
    return PositionEngine(
        entry_policy=PyramidEntryPolicy(config),
        add_policy=PyramidAddPolicy(config),
        stop_policy=ChandelierStopPolicy(config),
        config=engine_config,
    )
