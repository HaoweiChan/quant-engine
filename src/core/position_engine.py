from __future__ import annotations

from collections import deque
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

import structlog

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

if TYPE_CHECKING:
    from src.risk.pre_trade import PreTradeRiskCheck

logger = structlog.get_logger(__name__)

# Signature: (decision, snapshot, account) → modified decision or None to skip
EntrySizerFn = Callable[
    [EntryDecision, MarketSnapshot, AccountState | None],
    EntryDecision | None,
]

# Signature: (decision, snapshot, positions) → modified decision or None to skip.
# Mirrors EntrySizerFn: hook returns None to abort the add silently (e.g. margin cap,
# multiplier resolved to 0 lots).
AddSizerFn = Callable[
    [AddDecision, MarketSnapshot, list[Position]],
    AddDecision | None,
]


class PositionEngine:
    def __init__(
        self,
        entry_policy: EntryPolicy,
        add_policy: AddPolicy,
        stop_policy: StopPolicy,
        config: EngineConfig,
        pre_trade_check: PreTradeRiskCheck | None = None,
    ) -> None:
        self._entry_policy = entry_policy
        self._add_policy = add_policy
        self._stop_policy = stop_policy
        self._config = config
        self._pre_trade_check = pre_trade_check
        self._entry_sizer: EntrySizerFn | None = None
        self._add_sizer: AddSizerFn | None = None
        self._positions: list[Position] = []
        self._mode: Literal["model_assisted", "rule_only", "halted"] = "model_assisted"
        self._high_history: deque[float] = deque(maxlen=config.trail_lookback)
        self._pre_trade_rejection_events: list[dict[str, Any]] = []

    @property
    def entry_sizer(self) -> EntrySizerFn | None:
        return self._entry_sizer

    @entry_sizer.setter
    def entry_sizer(self, fn: EntrySizerFn | None) -> None:
        self._entry_sizer = fn

    @property
    def add_sizer(self) -> AddSizerFn | None:
        return self._add_sizer

    @add_sizer.setter
    def add_sizer(self, fn: AddSizerFn | None) -> None:
        self._add_sizer = fn

    # -- public API --

    def on_snapshot(
        self,
        snapshot: MarketSnapshot,
        signal: MarketSignal | None = None,
        account: AccountState | None = None,
        warmup_mode: bool = False,
    ) -> list[Order]:
        self._high_history.append(snapshot.price)

        # Warmup short-circuit: hydrate policy and stop-history state from
        # historical bars without emitting orders or mutating the position
        # ledger. Used by StrategyWarmup to prime indicators (e.g. EMA-144)
        # before the first live bar arrives.
        if warmup_mode:
            self._update_trailing_stops(snapshot)
            effective_signal = signal if self._mode == "model_assisted" else None
            state = self.get_state()
            if not self._positions and self._mode != "halted":
                self._entry_policy.should_enter(snapshot, effective_signal, state, account)
            if self._positions and self._mode != "halted":
                self._add_policy.should_add(snapshot, effective_signal, state)
            return []

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
            decision = self._entry_policy.should_enter(snapshot, effective_signal, state, account)
            if decision is not None and self._entry_sizer is not None:
                decision = self._entry_sizer(decision, snapshot, account)
            if decision is not None:
                if not self._passes_entry_margin_gate(decision, snapshot, account):
                    decision = None
                else:
                    entry_orders = self._execute_entry(decision, snapshot)
                    entry_orders = self._gate_orders(entry_orders, snapshot, account)
                    orders.extend(entry_orders)

        # Priority 5: add position (delegate to policy, engine gates on margin)
        if self._positions and self._mode != "halted":
            if account is not None and account.margin_ratio > self._config.margin_limit * 0.8:
                pass  # margin headroom insufficient, skip add
            else:
                add_state = self.get_state()
                add_decision = self._add_policy.should_add(snapshot, effective_signal, add_state)
                if add_decision is not None:
                    add_orders = self._execute_add(add_decision, snapshot)
                    add_orders = self._gate_orders(add_orders, snapshot, account)
                    orders.extend(add_orders)

        # Priority 6: circuit breaker
        orders.extend(self._check_circuit_breaker(snapshot, account))

        return orders

    def check_stops(self, snapshot: MarketSnapshot) -> list[Order]:
        """Check stop-loss exits without updating indicator state.

        Called on every 1m bar for timely stop execution, even when the
        strategy evaluates on a coarser timeframe.
        """
        orders = self._check_stops(snapshot)
        self._update_trailing_stops(snapshot)
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

    def close_position_by_disaster_stop(
        self,
        position_id: str,
        fill_price: float,
        fill_timestamp: datetime,
    ) -> Position | None:
        for i, pos in enumerate(self._positions):
            if pos.position_id == position_id:
                self._positions.pop(i)
                return pos
        return None

    @property
    def pre_trade_rejection_events(self) -> list[dict[str, Any]]:
        return list(self._pre_trade_rejection_events)

    # -- private: stop-loss check (Priority 1) --

    def _check_stops(self, snapshot: MarketSnapshot) -> list[Order]:
        intrabar = self._config.intrabar_stop_check
        whole_book = self._config.whole_book_exit_on_stop
        fill_at_level = self._config.stop_fill_at_level
        min_tick = snapshot.contract_specs.min_tick

        # Phase 1: per-position trigger detection.
        triggered: list[int] = []
        for i, pos in enumerate(self._positions):
            # min_hold_lots: skip base position (level 0) so it acts as permanent B&H
            if self._config.min_hold_lots > 0 and pos.pyramid_level == 0:
                continue
            same_bar_entry = pos.entry_timestamp == snapshot.timestamp
            if intrabar and not same_bar_entry:
                if pos.direction == "long":
                    trigger_price = (
                        snapshot.bar_low if snapshot.bar_low is not None else snapshot.price
                    )
                    hit = trigger_price <= pos.stop_level
                else:
                    trigger_price = (
                        snapshot.bar_high if snapshot.bar_high is not None else snapshot.price
                    )
                    hit = trigger_price >= pos.stop_level
            else:
                hit = (
                    snapshot.price <= pos.stop_level
                    if pos.direction == "long"
                    else snapshot.price >= pos.stop_level
                )
            if hit:
                triggered.append(i)

        # Phase 2: whole-book expansion. The first triggered position decides
        # which direction's book to flatten; min_hold_lots still shields level 0.
        if whole_book and triggered:
            direction = self._positions[triggered[0]].direction
            triggered_set = set(triggered)
            for j, pos in enumerate(self._positions):
                if j in triggered_set:
                    continue
                if pos.direction != direction:
                    continue
                if self._config.min_hold_lots > 0 and pos.pyramid_level == 0:
                    continue
                triggered.append(j)
            triggered.sort()

        # Phase 3: emit one exit Order per triggered position.
        orders: list[Order] = []
        for i in triggered:
            pos = self._positions[i]
            reason = "trailing_stop" if self._is_trailing(pos, snapshot) else "stop_loss"
            close_side = "sell" if pos.direction == "long" else "buy"
            metadata: dict[str, object] = {
                "pyramid_level": pos.pyramid_level,
                "urgency": "immediate",
                "entry_price": pos.entry_price,
            }
            if fill_at_level:
                # Fill at the stop level (worst-case for the trader): one tick
                # below for longs, one tick above for shorts. The fill model
                # still adds spread/impact/latency/commission on top.
                offset = min_tick if pos.direction == "long" else -min_tick
                metadata["fill_price_override"] = pos.stop_level - offset
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
                    metadata=metadata,
                    parent_position_id=pos.position_id,
                    order_class="algo_exit",
                )
            )
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
                updated.append(
                    Position(
                        entry_price=pos.entry_price,
                        lots=pos.lots,
                        contract_type=pos.contract_type,
                        stop_level=new_stop,
                        pyramid_level=pos.pyramid_level,
                        entry_timestamp=pos.entry_timestamp,
                        direction=pos.direction,
                    )
                )
            else:
                updated.append(pos)
        self._positions = updated

    # -- private: margin safety (Priority 3) --

    def _check_margin_safety(self, snapshot: MarketSnapshot, account: AccountState) -> list[Order]:
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

    def _execute_entry(self, decision: EntryDecision, snapshot: MarketSnapshot) -> list[Order]:
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
        meta = {**decision.metadata, "urgency": "normal"}
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
                metadata=meta,
                parent_position_id=position.position_id,
            )
        ]

    # -- private: execute add decision --

    def _execute_add(self, decision: AddDecision, snapshot: MarketSnapshot) -> list[Order]:
        if not self._positions:
            return []
        # Sizing hook — resolves AddDecision multipliers and applies margin caps.
        # Mirrors the entry_sizer pattern; a None return (or lots<=0) aborts silently.
        if self._add_sizer is not None:
            sized = self._add_sizer(decision, snapshot, self._positions)
            if sized is None or sized.lots <= 0:
                return []
            decision = sized
        direction = self._positions[0].direction
        entry_side = "buy" if direction == "long" else "sell"

        if decision.move_existing_to_breakeven:
            updated: list[Position] = []
            for pos in self._positions:
                needs_move = (pos.direction == "long" and pos.stop_level < pos.entry_price) or (
                    pos.direction == "short" and pos.stop_level > pos.entry_price
                )
                if needs_move:
                    updated.append(
                        Position(
                            entry_price=pos.entry_price,
                            lots=pos.lots,
                            contract_type=pos.contract_type,
                            stop_level=pos.entry_price,
                            pyramid_level=pos.pyramid_level,
                            entry_timestamp=pos.entry_timestamp,
                            direction=pos.direction,
                        )
                    )
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
                metadata={"pyramid_level": pyramid_level + 1, "urgency": "normal"},
                parent_position_id=new_position.position_id,
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
                    parent_position_id=pos.position_id,
                    order_class="algo_exit",
                )
            )
        self._positions.clear()
        self._mode = "halted"
        return orders

    # -- private: pre-trade risk gate --

    def _gate_orders(
        self, orders: list[Order], snapshot: MarketSnapshot, account: AccountState | None,
    ) -> list[Order]:
        if self._pre_trade_check is None or account is None:
            return orders
        approved: list[Order] = []
        for order in orders:
            market_data = {
                "margin_per_unit": snapshot.margin_per_unit,
                "adv": snapshot.contract_specs.lot_types.get("large", 50000.0),
            }
            result = self._pre_trade_check.evaluate(order, account, market_data)
            if result.approved:
                approved.append(order)
        return approved

    def _passes_entry_margin_gate(
        self,
        decision: EntryDecision,
        snapshot: MarketSnapshot,
        account: AccountState | None,
    ) -> bool:
        # Strategies that operate under reduced-margin rules (e.g. TAIFEX
        # 當沖 at ~half the overnight initial margin) declare their real
        # per-contract margin via decision.metadata["intraday_margin_per_contract"].
        # When present, this gate uses that value instead of snapshot.margin_per_unit
        # so the engine doesn't reject entries the broker would happily fill.
        per_unit = float(
            (decision.metadata or {}).get(
                "intraday_margin_per_contract", snapshot.margin_per_unit,
            )
        )
        required_margin = decision.lots * per_unit
        if account is None:
            if not self._config.require_account_for_entry:
                return True
            self._record_pre_trade_rejection(
                reason="missing_account_context",
                snapshot=snapshot,
                decision=decision,
                required_margin=required_margin,
                available_margin=None,
            )
            return False
        try:
            available_margin = float(account.margin_available)
        except (TypeError, ValueError):
            return True
        if available_margin < required_margin:
            self._record_pre_trade_rejection(
                reason="insufficient_margin",
                snapshot=snapshot,
                decision=decision,
                required_margin=required_margin,
                available_margin=available_margin,
            )
            return False
        return True

    def _record_pre_trade_rejection(
        self,
        reason: str,
        snapshot: MarketSnapshot,
        decision: EntryDecision,
        required_margin: float,
        available_margin: float | None,
    ) -> None:
        event = {
            "event_type": "pre_trade_rejection",
            "strategy": decision.metadata.get("strategy", "pyramid_entry"),
            "reason": reason,
            "symbol": snapshot.contract_specs.symbol,
            "required_margin": required_margin,
            "available_margin": available_margin,
            "decision_lots": decision.lots,
            "decision_direction": decision.direction,
            "timestamp": snapshot.timestamp.isoformat(),
        }
        self._pre_trade_rejection_events.append(event)
        logger.warning("pre_trade_rejection", **event)

    # -- private: helpers --

    def _estimate_drawdown(self, snapshot: MarketSnapshot, account: AccountState | None) -> float:
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


def create_pyramid_engine(
    config: PyramidConfig,
    pre_trade_check: PreTradeRiskCheck | None = None,
) -> PositionEngine:
    """Factory: build a PositionEngine with pyramid strategy policies."""
    engine_config = EngineConfig(
        max_loss=config.max_loss,
        margin_limit=config.margin_limit,
        trail_lookback=config.trail_lookback,
    )
    if (
        engine_config.disaster_stop_enabled
        and engine_config.disaster_atr_mult <= config.stop_atr_mult
    ):
        raise ValueError("disaster_atr_mult must exceed stop_atr_mult")
    return PositionEngine(
        entry_policy=PyramidEntryPolicy(config),
        add_policy=PyramidAddPolicy(config),
        stop_policy=ChandelierStopPolicy(config),
        config=engine_config,
        pre_trade_check=pre_trade_check,
    )
