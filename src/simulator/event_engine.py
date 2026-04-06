"""Event-driven simulation engine with queue-based event processing."""

from __future__ import annotations

import heapq
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import count
from typing import TYPE_CHECKING, Any

from src.core.adapter import BaseAdapter
from src.core.types import (
    AccountState,
    Event,
    EventEngineConfig,
    EventType,
    MarketEvent,
    SignalEvent,
)
from src.simulator.types import BacktestResult, Fill

if TYPE_CHECKING:
    from src.audit.trail import AuditTrail

EVENT_PRIORITY: dict[EventType, int] = {
    EventType.RISK: 0,
    EventType.FILL: 1,
    EventType.MARKET: 2,
    EventType.SIGNAL: 3,
    EventType.ORDER: 4,
    EventType.AUDIT: 5,
}


def generate_synthetic_ticks(
    open_price: float,
    high: float,
    low: float,
    close: float,
    volume: float,
    atr: float,
    n_ticks: int = 10,
) -> list[dict[str, Any]]:
    if high - low <= 0:
        return [
            {"open": close, "high": close, "low": close, "close": close, "volume": volume / n_ticks}
        ]

    path = [open_price]
    remaining_steps = n_ticks - 1
    touch_high = False
    touch_low = False

    for i in range(remaining_steps):
        progress = (i + 1) / n_ticks
        target_high = high - (high - open_price) * (1 - progress) if not touch_high else high
        target_low = low + (open_price - low) * (1 - progress) if not touch_low else low

        if not touch_high and random.random() < 0.3:
            price = target_high
            touch_high = True
        elif not touch_low and random.random() < 0.3:
            price = target_low
            touch_low = True
        else:
            price = random.uniform(low, high)

        path.append(price)

    path[-1] = close

    ticks = []
    for i in range(len(path) - 1):
        tick_open = path[i]
        tick_close = path[i + 1]
        tick_high = max(tick_open, tick_close)
        tick_low = min(tick_open, tick_close)
        tick_vol = volume / n_ticks
        ticks.append(
            {
                "open": tick_open,
                "high": tick_high,
                "low": tick_low,
                "close": tick_close,
                "volume": tick_vol,
            }
        )

    return ticks


@dataclass
class EventEngine:
    config: EventEngineConfig | None = None
    _heap: list[tuple[int, int, Event]] = field(default_factory=list)
    _handlers: dict[EventType, list[Callable[[Event], list[Event] | None]]] = field(
        default_factory=dict
    )
    _audit_trail: "AuditTrail | None" = field(default=None, repr=False)
    _counter: count = field(default_factory=count)

    def __post_init__(self) -> None:
        if self.config is None:
            self.config = EventEngineConfig()

    @property
    def _queue(self) -> list:
        """Backward-compat alias for tests that check len(engine._queue)."""
        return self._heap

    def set_audit_trail(self, audit_trail: "AuditTrail | None") -> None:
        self._audit_trail = audit_trail

    def register_handler(
        self, event_type: EventType, handler: Callable[[Event], list[Event] | None]
    ) -> None:
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    def push(self, event: Event) -> None:
        priority = EVENT_PRIORITY.get(event.event_type, 999)
        heapq.heappush(self._heap, (priority, next(self._counter), event))

    def _audit_event(self, event: Event, account_state: AccountState | None = None) -> None:
        if self._audit_trail is None or (self.config and not self.config.audit_enabled):
            return
        if account_state is None:
            account_state = AccountState(
                equity=0.0,
                unrealized_pnl=0.0,
                realized_pnl=0.0,
                margin_used=0.0,
                margin_available=0.0,
                margin_ratio=0.0,
                drawdown_pct=0.0,
                positions=[],
                timestamp=event.timestamp,
            )
        event_type_map = {
            EventType.ORDER: "order_generated",
            EventType.FILL: "fill_executed",
            EventType.RISK: "risk_action",
        }
        audit_type = event_type_map.get(event.event_type)
        if audit_type:
            self._audit_trail.append(
                event_type=audit_type,
                account=account_state,
                event_data={"event": str(event), "timestamp": event.timestamp.isoformat()},
            )

    def run(self) -> None:
        heap = self._heap
        counter = self._counter
        while heap:
            _, _, event = heapq.heappop(heap)
            handlers = self._handlers.get(event.event_type, [])
            for handler in handlers:
                new_events = handler(event)
                if new_events:
                    for new_event in new_events:
                        priority = EVENT_PRIORITY.get(new_event.event_type, 999)
                        heapq.heappush(heap, (priority, next(counter), new_event))

    def run_backtest(
        self,
        bars: list[dict[str, Any]],
        adapter: BaseAdapter,
        initial_equity: float = 2_000_000.0,
        precomputed_signals: list[SignalEvent | None] | None = None,
    ) -> BacktestResult:
        from src.simulator.metrics import (
            compute_all_metrics,
            drawdown_series,
            monthly_returns,
            yearly_returns,
        )

        engine_state: dict[str, Any] = {}
        equity = initial_equity
        equity_curve: list[float] = [equity]
        trade_log: list[Fill] = []
        ts_list: list[datetime] = []
        realized_pnl = 0.0

        tick_drill_mult = self.config.tick_drill_atr_mult if self.config else 2.0
        tick_drill_enabled = self.config.tick_drill_enabled if self.config else True

        for i, bar in enumerate(bars):
            ts = bar.get("timestamp", datetime(2024, 1, 1))
            ts_list.append(ts)

            snapshot = adapter.to_snapshot({**bar, "timestamp": ts})
            bar_high = bar.get("high", 0.0)
            bar_low = bar.get("low", 0.0)
            daily_atr = snapshot.atr.get("daily", 0.0) if hasattr(snapshot, "atr") else 0.0

            should_drill = (
                tick_drill_enabled
                and daily_atr > 0
                and (bar_high - bar_low) > tick_drill_mult * daily_atr
            )

            if should_drill:
                n_ticks = min(self.config.max_events_per_bar if self.config else 1000, 10)
                ticks = generate_synthetic_ticks(
                    open_price=bar.get("open", 0.0),
                    high=bar_high,
                    low=bar_low,
                    close=bar.get("close", 0.0),
                    volume=bar.get("volume", 0.0),
                    atr=daily_atr,
                    n_ticks=n_ticks,
                )
                for tick in ticks:
                    tick_ts = ts + timedelta(seconds=30)
                    market_event = MarketEvent(
                        event_type=EventType.MARKET,
                        timestamp=tick_ts,
                        data=tick,
                        symbol=bar.get("symbol", ""),
                        open_price=tick["open"],
                        high=tick["high"],
                        low=tick["low"],
                        close=tick["close"],
                        volume=tick["volume"],
                        atr=daily_atr,
                    )
                    self.push(market_event)
                    self.run()
            else:
                market_event = MarketEvent(
                    event_type=EventType.MARKET,
                    timestamp=ts,
                    data=bar,
                    symbol=bar.get("symbol", ""),
                    open_price=bar.get("open", 0.0),
                    high=bar_high,
                    low=bar_low,
                    close=bar.get("close", 0.0),
                    volume=bar.get("volume", 0.0),
                    atr=daily_atr,
                )
                self.push(market_event)
                self.run()

        dd_series = drawdown_series(equity_curve)
        metrics = compute_all_metrics(equity_curve, trade_log, 252.0)
        m_returns = monthly_returns(equity_curve[1:], ts_list) if ts_list else {}
        y_returns = yearly_returns(equity_curve[1:], ts_list) if ts_list else {}

        return BacktestResult(
            equity_curve=equity_curve,
            drawdown_series=dd_series,
            trade_log=trade_log,
            metrics=metrics,
            monthly_returns=m_returns,
            yearly_returns=y_returns,
            impact_report=None,
        )
