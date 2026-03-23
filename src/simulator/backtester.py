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
from src.simulator.fill_model import ClosePriceFillModel, FillModel
from src.simulator.metrics import (
    compute_all_metrics,
    drawdown_series,
    monthly_returns,
    yearly_returns,
)
from src.simulator.types import BacktestResult, Fill


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
        self._fill_model = fill_model or ClosePriceFillModel()
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
            snapshot = self._adapter.to_snapshot(bar)
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
                            pnl = (fill.fill_price - entry_price) * entry_lots * snapshot.point_value
                        else:
                            pnl = (entry_price - fill.fill_price) * entry_lots * snapshot.point_value
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

        return BacktestResult(
            equity_curve=equity_curve,
            drawdown_series=dd_series,
            trade_log=trade_log,
            metrics=metrics,
            monthly_returns=m_returns,
            yearly_returns=y_returns,
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
