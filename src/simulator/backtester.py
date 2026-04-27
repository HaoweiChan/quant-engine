"""BacktestRunner: feeds historical bars through production PositionEngine."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from src.core.adapter import BaseAdapter
from src.core.position_engine import PositionEngine, create_pyramid_engine
from src.core.sizing import PortfolioSizer, SizingConfig
from src.core.types import (
    METADATA_EXPOSURE_MULTIPLIER,
    METADATA_STRATEGY_SIZED,
    AccountState,
    AddDecision,
    EntryDecision,
    Event,
    EventEngineConfig,
    EventType,
    FillEvent,
    MarketEvent,
    MarketSignal,
    MarketSnapshot,
    Order,
    OrderEvent,
    Position,
    PyramidConfig,
)
from src.simulator.event_engine import EventEngine
from src.simulator.fill_model import FillModel, MarketImpactFillModel
from src.simulator.metrics import (
    compute_all_metrics,
    drawdown_series,
    monthly_returns,
    yearly_returns,
)
from src.simulator.types import BacktestResult, Fill, ImpactReport


class BacktestRunner:
    def __init__(
        self,
        config: PyramidConfig | Callable[[], PositionEngine],
        adapter: BaseAdapter,
        fill_model: FillModel | None = None,
        initial_equity: float = 2_000_000.0,
        periods_per_year: float = 252.0,
        event_engine_config: EventEngineConfig | None = None,
        sizing_config: SizingConfig | None = None,
    ) -> None:
        if callable(config) and not isinstance(config, PyramidConfig):
            self._engine_factory = config
        else:
            self._engine_factory = lambda: create_pyramid_engine(config)  # type: ignore[arg-type]
        self._adapter = adapter
        self._fill_model = fill_model or MarketImpactFillModel()
        self._initial_equity = initial_equity
        self._periods_per_year = periods_per_year
        self._ee_config = event_engine_config
        self._sizing_config = sizing_config
        self._sizer = PortfolioSizer(sizing_config) if sizing_config else None

    def run(
        self,
        bars: list[dict[str, Any]],
        signals: list[MarketSignal | None] | None = None,
        timestamps: list[datetime] | None = None,
        force_flat_indices: set[int] | None = None,
    ) -> BacktestResult:
        engine = self._engine_factory()
        self._attach_sizer(engine)
        equity = self._initial_equity
        equity_curve: list[float] = [equity]
        trade_log: list[Fill] = []
        ts_list: list[datetime] = []
        realized_pnl = 0.0
        lots_held: list[float] = []
        open_entries: dict[str, tuple[float, float, str]] = {}

        # Indicator collection — populated if engine has an IndicatorProvider attached
        _ind_provider = getattr(engine, "indicator_provider", None)
        _ind_series: dict[str, list[float | None]] = (
            {k: [] for k in _ind_provider.snapshot()} if _ind_provider is not None else {}
        )
        _ind_meta: dict[str, dict] = (
            _ind_provider.indicator_meta() if _ind_provider is not None else {}
        )

        # Build EventEngine for event dispatch per bar
        ee = EventEngine(config=self._ee_config)

        def on_market(event: MarketEvent) -> list[Event]:
            return []

        def on_order(event: OrderEvent) -> list[Event]:
            return []

        def on_fill(event: FillEvent) -> list[Event]:
            return []

        ee.register_handler(EventType.MARKET, on_market)
        ee.register_handler(EventType.ORDER, on_order)
        ee.register_handler(EventType.FILL, on_fill)

        for i, bar in enumerate(bars):
            signal = signals[i] if signals else None
            ts = timestamps[i] if timestamps else datetime(2024, 1, 1)
            ts_list.append(ts)
            snapshot = self._adapter.to_snapshot({**bar, "timestamp": ts})
            account = self._make_account(equity, realized_pnl, engine, snapshot)

            # Dispatch MarketEvent through EventEngine
            market_event = MarketEvent(
                event_type=EventType.MARKET,
                timestamp=ts,
                data=bar,
                symbol=bar.get("symbol", ""),
                open_price=bar.get("open", 0.0),
                high=bar.get("high", 0.0),
                low=bar.get("low", 0.0),
                close=bar.get("close", 0.0),
                volume=bar.get("volume", 0.0),
                atr=snapshot.atr.get("daily", 0.0) if hasattr(snapshot, "atr") else 0.0,
            )
            ee.push(market_event)
            ee.run()

            orders = engine.on_snapshot(snapshot, signal, account)

            # Snapshot indicators after on_snapshot so values reflect the current bar
            if _ind_provider is not None:
                for k, v in _ind_provider.snapshot().items():
                    if k in _ind_series:
                        _ind_series[k].append(v)

            for order in orders:
                # Dispatch OrderEvent
                order_event = OrderEvent(
                    event_type=EventType.ORDER,
                    timestamp=ts,
                    data={"order": order},
                    order=order,
                )
                ee.push(order_event)
                ee.run()

                fill = self._fill_model.simulate(order, bar, ts)
                trade_log.append(fill)
                realized_pnl -= fill.commission_cost

                # Dispatch FillEvent
                fill_event = FillEvent(
                    event_type=EventType.FILL,
                    timestamp=ts,
                    data={"fill": fill},
                    fill_price=fill.fill_price,
                    fill_lots=fill.lots,
                    side=fill.side,
                    symbol=fill.symbol,
                )
                ee.push(fill_event)
                ee.run()

                sym = fill.symbol
                if sym in open_entries:
                    entry_price, entry_lots, entry_side = open_entries[sym]
                    if fill.side != entry_side:
                        if entry_side == "buy":
                            delta = fill.fill_price - entry_price
                        else:
                            delta = entry_price - fill.fill_price
                        pnl = delta * entry_lots * snapshot.point_value
                        realized_pnl += pnl
                        del open_entries[sym]
                    else:
                        total_lots = entry_lots + fill.lots
                        avg = (entry_price * entry_lots + fill.fill_price * fill.lots) / total_lots
                        open_entries[sym] = (avg, total_lots, entry_side)
                else:
                    open_entries[sym] = (fill.fill_price, fill.lots, fill.side)

            # Session-end force-close must go through fill_model so commission and
            # slippage bill uniformly with normal exits.
            if force_flat_indices is not None and i in force_flat_indices and open_entries:
                for sym, (entry_price, lots, entry_side) in list(open_entries.items()):
                    exit_side = "sell" if entry_side == "buy" else "buy"
                    close_order = Order(
                        order_type="market",
                        side=exit_side,
                        symbol=sym,
                        contract_type="large",
                        lots=lots,
                        price=None,
                        stop_price=None,
                        reason="session_close",
                    )
                    fill = self._fill_model.simulate(close_order, bar, ts)
                    trade_log.append(fill)
                    realized_pnl -= fill.commission_cost
                    if entry_side == "buy":
                        delta = fill.fill_price - entry_price
                    else:
                        delta = entry_price - fill.fill_price
                    pnl = delta * lots * snapshot.point_value
                    realized_pnl += pnl
                open_entries.clear()
                engine = self._engine_factory()
                self._attach_sizer(engine)
                _ind_provider = getattr(engine, "indicator_provider", None)

            unrealized = self._calc_unrealized(open_entries, snapshot)
            equity = self._initial_equity + realized_pnl + unrealized
            lots_held.append(sum(lt for _, lt, _ in open_entries.values()))
            equity_curve.append(equity)

        dd_series = drawdown_series(equity_curve)
        last_close = bars[-1]["close"] if bars else None
        metrics = compute_all_metrics(equity_curve, trade_log, self._periods_per_year, last_price=last_close)
        m_returns = monthly_returns(equity_curve[1:], ts_list) if ts_list else {}
        y_returns = yearly_returns(equity_curve[1:], ts_list) if ts_list else {}
        impact_report = self._build_impact_report(trade_log, equity_curve)
        metrics["total_market_impact"] = impact_report.total_market_impact
        metrics["total_spread_cost"] = impact_report.total_spread_cost
        metrics["total_commission_cost"] = impact_report.total_commission_cost
        metrics["avg_latency_ms"] = impact_report.avg_latency_ms
        metrics["partial_fill_count"] = float(impact_report.partial_fill_count)
        # Cost breakdown metrics
        metrics["gross_pnl"] = impact_report.naive_pnl
        metrics["net_pnl"] = impact_report.realistic_pnl
        total_costs = (
            impact_report.total_market_impact
            + impact_report.total_spread_cost
            + impact_report.total_commission_cost
        )
        metrics["total_slippage_cost"] = impact_report.total_spread_cost
        metrics["total_commission_cost"] = impact_report.total_commission_cost
        cost_drag = (
            total_costs / impact_report.naive_pnl
            if impact_report.naive_pnl > 0
            else 0.0
        )
        metrics["cost_drag_pct"] = cost_drag * 100.0
        metrics["high_cost_drag"] = cost_drag > 0.5

        result = BacktestResult(
            equity_curve=equity_curve,
            drawdown_series=dd_series,
            trade_log=trade_log,
            metrics=metrics,
            monthly_returns=m_returns,
            yearly_returns=y_returns,
            impact_report=impact_report,
        )
        # Attach indicator data as instance attributes so older class definitions
        # (loaded in persistent subprocesses) don't fail on unknown constructor kwargs.
        result.indicator_series = _ind_series  # type: ignore[attr-defined]
        result.indicator_meta = _ind_meta  # type: ignore[attr-defined]
        result.lots_held_per_bar = lots_held  # type: ignore[attr-defined]
        return result

    def _make_account(
        self,
        equity: float,
        realized_pnl: float,
        engine: PositionEngine,
        snapshot: MarketSnapshot,
    ) -> AccountState:
        state = engine.get_state()
        margin_used = sum(p.lots * snapshot.margin_per_unit for p in state.positions)
        margin_avail = equity - margin_used
        margin_ratio = margin_used / equity if equity > 0 else 0.0
        dd_pct = max(0.0, min(1.0, 1.0 - equity / self._initial_equity))
        return AccountState(
            equity=equity,
            unrealized_pnl=state.total_unrealized_pnl,
            realized_pnl=realized_pnl,
            margin_used=margin_used,
            margin_available=margin_avail,
            margin_ratio=margin_ratio,
            drawdown_pct=dd_pct,
            positions=list(state.positions),
            timestamp=snapshot.timestamp,
        )

    @staticmethod
    def _build_impact_report(trade_log: list[Fill], equity_curve: list[float]) -> ImpactReport:
        total_impact = sum(abs(f.market_impact) for f in trade_log)
        total_spread = sum(abs(f.spread_cost) for f in trade_log)
        total_commission = sum(abs(f.commission_cost) for f in trade_log)
        latencies = [f.latency_ms for f in trade_log if f.latency_ms > 0]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
        partial_count = sum(1 for f in trade_log if f.is_partial)
        naive_pnl = equity_curve[-1] - equity_curve[0] + total_impact + total_spread + total_commission
        realistic_pnl = equity_curve[-1] - equity_curve[0]
        ratio = realistic_pnl / naive_pnl if naive_pnl != 0 else 1.0
        breakdown = [
            {
                "timestamp": (
                    f.timestamp.isoformat()
                    if hasattr(f.timestamp, "isoformat")
                    else str(f.timestamp)
                ),
                "side": f.side,
                "lots": f.lots,
                "market_impact": f.market_impact,
                "spread_cost": f.spread_cost,
                "commission_cost": f.commission_cost,
                "latency_ms": f.latency_ms,
                "is_partial": float(f.is_partial),
            }
            for f in trade_log
        ]
        return ImpactReport(
            naive_pnl=naive_pnl,
            realistic_pnl=realistic_pnl,
            pnl_ratio=ratio,
            total_market_impact=total_impact,
            total_spread_cost=total_spread,
            total_commission_cost=total_commission,
            avg_latency_ms=avg_latency,
            partial_fill_count=partial_count,
            per_trade_impact_breakdown=breakdown,
        )

    def _calc_unrealized(
        self,
        open_entries: dict[str, tuple[float, float, str]],
        snapshot: MarketSnapshot,
    ) -> float:
        total = 0.0
        for _sym, (entry_price, lots, side) in open_entries.items():
            if side == "buy":
                total += (snapshot.price - entry_price) * lots * snapshot.point_value
            else:
                total += (entry_price - snapshot.price) * lots * snapshot.point_value
        return total

    def _attach_sizer(self, engine: PositionEngine) -> None:
        """Attach PortfolioSizer hooks (entry + add) if sizing_config is set."""
        if self._sizer is None:
            return
        sizer = self._sizer
        initial_equity = self._initial_equity

        def _size_entry(
            decision: EntryDecision,
            snapshot: MarketSnapshot,
            account: AccountState | None,
        ) -> EntryDecision | None:
            # Strategy-sized opt-out: when the strategy already did account-aware
            # sizing (e.g. compounding_trend_long pulls margin headroom from the
            # _AccountHub), trust ``decision.lots`` and only enforce the
            # margin-cap safety rail. Never inflate, only trim if the request
            # would breach equity * portfolio_margin_cap. See
            # ``METADATA_STRATEGY_SIZED`` docstring in src/core/types.py.
            if decision.metadata.get(METADATA_STRATEGY_SIZED):
                equity_for_cap = account.equity if account is not None else initial_equity
                margin_cap = equity_for_cap * sizer._config.portfolio_margin_cap
                requested_margin = decision.lots * snapshot.margin_per_unit
                if requested_margin > margin_cap and snapshot.margin_per_unit > 0:
                    capped_lots = float(int(margin_cap / snapshot.margin_per_unit))
                    if capped_lots < 1:
                        return None
                    return EntryDecision(
                        lots=capped_lots,
                        contract_type=decision.contract_type,
                        initial_stop=decision.initial_stop,
                        direction=decision.direction,
                        metadata={**decision.metadata, "sizer": "strategy_sized_capped"},
                    )
                return decision

            equity = account.equity if account is not None else initial_equity
            stop_dist = abs(snapshot.price - decision.initial_stop)
            result = sizer.size_entry(
                equity=equity,
                stop_distance=stop_dist,
                point_value=snapshot.point_value,
                margin_per_unit=snapshot.margin_per_unit,
            )
            if result.lots < 1:
                return None
            return EntryDecision(
                lots=result.lots,
                contract_type=decision.contract_type,
                initial_stop=decision.initial_stop,
                direction=decision.direction,
                metadata={**decision.metadata, "sizer": result.method, "sizer_caps": result.caps_applied},
            )

        def _size_add(
            decision: AddDecision,
            snapshot: MarketSnapshot,
            positions: list[Position],
        ) -> AddDecision | None:
            from src.core.sizing import _base_position_lots

            # Strategy-sized opt-out: trust ``decision.lots`` and only enforce
            # margin-cap safety. Mirrors ``_size_entry`` behaviour.
            if decision.metadata.get(METADATA_STRATEGY_SIZED):
                margin_cap = initial_equity * sizer._config.portfolio_margin_cap
                existing_margin = sum(p.lots * snapshot.margin_per_unit for p in positions)
                requested_margin = decision.lots * snapshot.margin_per_unit
                if existing_margin + requested_margin > margin_cap and snapshot.margin_per_unit > 0:
                    headroom = max(0.0, margin_cap - existing_margin)
                    capped_lots = float(int(headroom / snapshot.margin_per_unit))
                    if capped_lots < 1:
                        return None
                    return AddDecision(
                        lots=capped_lots,
                        contract_type=decision.contract_type,
                        move_existing_to_breakeven=decision.move_existing_to_breakeven,
                        metadata={**decision.metadata, "sizer": "strategy_sized_capped"},
                    )
                return decision

            is_multiplier = bool(decision.metadata.get(METADATA_EXPOSURE_MULTIPLIER, False))
            base_lots = _base_position_lots(positions) if is_multiplier else 0.0
            existing_margin = sum(p.lots * snapshot.margin_per_unit for p in positions)
            # Estimate equity from initial + realised via positions; the sizer
            # caps by margin headroom so exact equity is not required here.
            # We fall back to initial_equity to mirror _size_entry.
            equity = initial_equity
            result = sizer.size_add(
                equity=equity,
                existing_margin_used=existing_margin,
                margin_per_unit=snapshot.margin_per_unit,
                requested_lots=decision.lots,
                base_lots=base_lots,
                is_multiplier=is_multiplier,
            )
            if result.lots < 1:
                return None
            return AddDecision(
                lots=result.lots,
                contract_type=decision.contract_type,
                move_existing_to_breakeven=decision.move_existing_to_breakeven,
                metadata={
                    **decision.metadata,
                    "sizer": result.method,
                    "sizer_caps": result.caps_applied,
                },
            )

        engine.entry_sizer = _size_entry
        engine.add_sizer = _size_add
