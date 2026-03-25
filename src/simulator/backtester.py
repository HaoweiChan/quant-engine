"""BacktestRunner: feeds historical bars through production PositionEngine."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from src.core.adapter import BaseAdapter
from src.core.position_engine import PositionEngine, create_pyramid_engine
from src.core.types import (
    AccountState,
    MarketSignal,
    MarketSnapshot,
    PyramidConfig,
)
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
    ) -> None:
        if callable(config) and not isinstance(config, PyramidConfig):
            self._engine_factory = config
        else:
            self._engine_factory = lambda: create_pyramid_engine(config)  # type: ignore[arg-type]
        self._adapter = adapter
        self._fill_model = fill_model or MarketImpactFillModel()
        self._initial_equity = initial_equity
        self._periods_per_year = periods_per_year

    def run(
        self,
        bars: list[dict[str, Any]],
        signals: list[MarketSignal | None] | None = None,
        timestamps: list[datetime] | None = None,
    ) -> BacktestResult:
        engine = self._engine_factory()
        equity = self._initial_equity
        equity_curve: list[float] = [equity]
        trade_log: list[Fill] = []
        ts_list: list[datetime] = []
        realized_pnl = 0.0
        # (entry_price, lots, entry_side) — supports both long and short
        open_entries: dict[str, tuple[float, float, str]] = {}

        for i, bar in enumerate(bars):
            signal = signals[i] if signals else None
            ts = timestamps[i] if timestamps else datetime(2024, 1, 1)
            ts_list.append(ts)
            snapshot = self._adapter.to_snapshot({**bar, "timestamp": ts})
            account = self._make_account(equity, realized_pnl, engine, snapshot)
            orders = engine.on_snapshot(snapshot, signal, account)

            for order in orders:
                fill = self._fill_model.simulate(order, bar, ts)
                trade_log.append(fill)
                sym = fill.symbol
                if sym in open_entries:
                    entry_price, entry_lots, entry_side = open_entries[sym]
                    if fill.side != entry_side:
                        # Closing position (opposite side)
                        if entry_side == "buy":
                            delta = fill.fill_price - entry_price
                        else:
                            delta = entry_price - fill.fill_price
                        pnl = delta * entry_lots * snapshot.point_value
                        realized_pnl += pnl
                        del open_entries[sym]
                    else:
                        # Adding to position (same side, e.g. pyramid)
                        total_lots = entry_lots + fill.lots
                        avg = (entry_price * entry_lots + fill.fill_price * fill.lots) / total_lots
                        open_entries[sym] = (avg, total_lots, entry_side)
                else:
                    open_entries[sym] = (fill.fill_price, fill.lots, fill.side)

            unrealized = self._calc_unrealized(open_entries, snapshot)
            equity = self._initial_equity + realized_pnl + unrealized
            equity_curve.append(equity)

        dd_series = drawdown_series(equity_curve)
        metrics = compute_all_metrics(equity_curve, trade_log, self._periods_per_year)
        m_returns = monthly_returns(equity_curve[1:], ts_list) if ts_list else {}
        y_returns = yearly_returns(equity_curve[1:], ts_list) if ts_list else {}
        impact_report = self._build_impact_report(trade_log, equity_curve)
        metrics["total_market_impact"] = impact_report.total_market_impact
        metrics["total_spread_cost"] = impact_report.total_spread_cost
        metrics["avg_latency_ms"] = impact_report.avg_latency_ms
        metrics["partial_fill_count"] = float(impact_report.partial_fill_count)

        return BacktestResult(
            equity_curve=equity_curve,
            drawdown_series=dd_series,
            trade_log=trade_log,
            metrics=metrics,
            monthly_returns=m_returns,
            yearly_returns=y_returns,
            impact_report=impact_report,
        )

    def _make_account(
        self,
        equity: float,
        realized_pnl: float,
        engine: PositionEngine,
        snapshot: MarketSnapshot,
    ) -> AccountState:
        state = engine.get_state()
        margin_used = sum(
            p.lots * snapshot.margin_per_unit for p in state.positions
        )
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
        latencies = [f.latency_ms for f in trade_log if f.latency_ms > 0]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
        partial_count = sum(1 for f in trade_log if f.is_partial)
        naive_pnl = equity_curve[-1] - equity_curve[0] + total_impact + total_spread
        realistic_pnl = equity_curve[-1] - equity_curve[0]
        ratio = realistic_pnl / naive_pnl if naive_pnl != 0 else 1.0
        breakdown = [
            {
                "timestamp": (
                    f.timestamp.isoformat()
                    if hasattr(f.timestamp, "isoformat") else str(f.timestamp)
                ),
                "side": f.side,
                "lots": f.lots,
                "market_impact": f.market_impact,
                "spread_cost": f.spread_cost,
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
