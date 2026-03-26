"""Unit tests for StrategyOptimizer.

Uses synthetic constant-price OHLCV bars so tests are fast and fully
deterministic — no database access required.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.core.types import ContractSpecs, MarketSnapshot, TradingHours
from src.simulator.strategy_optimizer import (
    StrategyOptimizer,
    _check_pickle_safety,
    _compute_efficiency,
    _low_trade_count_warnings,
    _validate_objective,
)
from src.simulator.types import BacktestResult, WindowResult


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

def _make_bars(n: int, price: float = 20_000.0) -> tuple[list[dict[str, Any]], list[datetime]]:
    """Generate N synthetic 1-min bars at a fixed price."""
    base = datetime(2024, 1, 2, 9, 0, 0)
    bars = [
        {
            "symbol": "TX",
            "price": price,
            "open": price,
            "high": price + 10,
            "low": price - 10,
            "close": price,
            "volume": 100,
            "daily_atr": 100.0,
            "timestamp": base + timedelta(minutes=i),
        }
        for i in range(n)
    ]
    timestamps = [b["timestamp"] for b in bars]
    return bars, timestamps


def _make_contract_specs() -> ContractSpecs:
    return ContractSpecs(
        symbol="TX",
        exchange="TAIFEX",
        currency="TWD",
        point_value=200.0,
        margin_initial=100_000.0,
        margin_maintenance=80_000.0,
        min_tick=1.0,
        trading_hours=TradingHours(open_time="09:00", close_time="13:45", timezone="Asia/Taipei"),
        fee_per_contract=60.0,
        tax_rate=0.0,
        lot_types={"large": 1.0},
    )


def _make_mock_adapter() -> MagicMock:
    specs = _make_contract_specs()
    adapter = MagicMock()
    adapter.to_snapshot.side_effect = lambda bar: MarketSnapshot(
        price=float(bar["price"]),
        atr={"daily": float(bar.get("daily_atr", 100.0))},
        timestamp=bar["timestamp"],
        margin_per_unit=100_000.0,
        point_value=200.0,
        min_lot=1.0,
        contract_specs=specs,
    )
    return adapter


def _make_empty_backtest(n_bars: int = 100) -> BacktestResult:
    eq = [2_000_000.0] * (n_bars + 1)
    return BacktestResult(
        equity_curve=eq,
        drawdown_series=[0.0] * (n_bars + 1),
        trade_log=[],
        metrics={"sharpe": 0.0, "sortino": 0.0, "calmar": 0.0,
                 "max_drawdown_abs": 0.0, "max_drawdown_pct": 0.0,
                 "win_rate": 0.0, "profit_factor": 0.0,
                 "avg_win": 0.0, "avg_loss": 0.0,
                 "trade_count": 0.0, "avg_holding_period": 0.0},
        monthly_returns={},
        yearly_returns={},
    )


# ---------------------------------------------------------------------------
# _validate_objective
# ---------------------------------------------------------------------------

class TestValidateObjective:
    def test_valid_objective_passes(self) -> None:
        row = {"sharpe": 0.5, "win_rate": 0.6, "kc_len": 90}
        _validate_objective("sharpe", row)  # should not raise

    def test_invalid_objective_raises(self) -> None:
        row = {"sharpe": 0.5, "kc_len": 90}
        with pytest.raises(ValueError, match="nonexistent"):
            _validate_objective("nonexistent", row)

    def test_error_lists_valid_metrics(self) -> None:
        row = {"sharpe": 0.5}
        with pytest.raises(ValueError, match="Available metrics"):
            _validate_objective("bad_metric", row)


# ---------------------------------------------------------------------------
# _check_pickle_safety
# ---------------------------------------------------------------------------

class TestPickleSafety:
    def test_lambda_raises(self) -> None:
        with pytest.raises(ValueError, match="lambda"):
            _check_pickle_safety(lambda: None)  # type: ignore[arg-type]

    def test_module_level_function_passes(self) -> None:
        # A real module-level function should not raise
        from src.strategies.intraday.mean_reversion.atr_mean_reversion import create_atr_mean_reversion_engine
        _check_pickle_safety(create_atr_mean_reversion_engine)  # should not raise

    def test_local_closure_raises(self) -> None:
        def local_factory(**kwargs: Any) -> None:  # type: ignore[return]
            pass
        with pytest.raises(ValueError, match="closure"):
            _check_pickle_safety(local_factory)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _low_trade_count_warnings
# ---------------------------------------------------------------------------

class TestLowTradeCountWarnings:
    def test_below_threshold_generates_warning(self) -> None:
        rows = [{"kc_len": 90, "_trade_count": 5, "sharpe": 0.1}]
        warnings = _low_trade_count_warnings(rows, ["kc_len"])
        assert len(warnings) == 1
        assert "kc_len=90" in warnings[0]

    def test_above_threshold_no_warning(self) -> None:
        rows = [{"kc_len": 90, "_trade_count": 50, "sharpe": 0.1}]
        warnings = _low_trade_count_warnings(rows, ["kc_len"])
        assert warnings == []

    def test_mixed_rows(self) -> None:
        rows = [
            {"kc_len": 60, "_trade_count": 5, "sharpe": 0.2},
            {"kc_len": 90, "_trade_count": 40, "sharpe": 0.3},
        ]
        warnings = _low_trade_count_warnings(rows, ["kc_len"])
        assert len(warnings) == 1


# ---------------------------------------------------------------------------
# _compute_efficiency
# ---------------------------------------------------------------------------

class TestComputeEfficiency:
    def _make_window(self, is_sharpe: float, oos_sharpe: float) -> WindowResult:
        is_bt = _make_empty_backtest()
        oos_bt = _make_empty_backtest()
        is_bt.metrics["sharpe"] = is_sharpe
        oos_bt.metrics["sharpe"] = oos_sharpe
        return WindowResult(
            window_idx=0, is_bars=100, oos_bars=20,
            best_params={}, is_result=is_bt, oos_result=oos_bt,
        )

    def test_perfect_efficiency(self) -> None:
        windows = [self._make_window(1.0, 1.0), self._make_window(2.0, 2.0)]
        eff = _compute_efficiency(windows, "sharpe")
        assert abs(eff - 1.0) < 1e-6

    def test_efficiency_ratio_correct(self) -> None:
        # IS mean = 2.0, OOS mean = 1.0 → efficiency = 0.5
        windows = [self._make_window(2.0, 1.0), self._make_window(2.0, 1.0)]
        eff = _compute_efficiency(windows, "sharpe")
        assert abs(eff - 0.5) < 1e-6

    def test_zero_is_returns_zero(self) -> None:
        windows = [self._make_window(0.0, 1.0)]
        eff = _compute_efficiency(windows, "sharpe")
        assert eff == 0.0

    def test_efficiency_precision(self) -> None:
        """Task 6.4: efficiency equals mean(oos)/mean(is) to 4 decimal places."""
        is_sharpes = [0.8, 1.2, 1.0]
        oos_sharpes = [0.5, 0.7, 0.6]
        windows = [self._make_window(i, o) for i, o in zip(is_sharpes, oos_sharpes)]
        eff = _compute_efficiency(windows, "sharpe")
        expected = (sum(oos_sharpes) / len(oos_sharpes)) / (sum(is_sharpes) / len(is_sharpes))
        assert abs(eff - expected) < 1e-4


# ---------------------------------------------------------------------------
# StrategyOptimizer.grid_search — structural tests (no DB)
# ---------------------------------------------------------------------------

class TestGridSearch:
    def setup_method(self) -> None:
        self.bars, self.ts = _make_bars(200)
        self.adapter = _make_mock_adapter()
        self.opt = StrategyOptimizer(adapter=self.adapter, n_jobs=1)

    def test_row_count_equals_combinations(self) -> None:
        from src.strategies.intraday.mean_reversion.atr_mean_reversion import create_atr_mean_reversion_engine
        param_grid = {"max_loss": [100_000], "kc_len": [15, 20, 25]}
        result = self.opt.grid_search(
            create_atr_mean_reversion_engine, param_grid,
            self.bars, self.ts, is_fraction=1.0,
        )
        assert result.trials.shape[0] == 3

    def test_trials_sorted_descending_by_objective(self) -> None:
        """Task 6.3: trials sorted descending."""
        from src.strategies.intraday.mean_reversion.atr_mean_reversion import create_atr_mean_reversion_engine
        param_grid = {"max_loss": [100_000], "kc_len": [15, 20, 25]}
        result = self.opt.grid_search(
            create_atr_mean_reversion_engine, param_grid,
            self.bars, self.ts, is_fraction=1.0,
        )
        sharpes = result.trials["sharpe"].to_list()
        assert sharpes == sorted(sharpes, reverse=True)

    def test_no_oos_result_when_is_fraction_one(self) -> None:
        from src.strategies.intraday.mean_reversion.atr_mean_reversion import create_atr_mean_reversion_engine
        param_grid = {"max_loss": [100_000], "kc_len": [20]}
        result = self.opt.grid_search(
            create_atr_mean_reversion_engine, param_grid,
            self.bars, self.ts, is_fraction=1.0,
        )
        assert result.best_oos_result is None

    def test_oos_result_present_when_split(self) -> None:
        from src.strategies.intraday.mean_reversion.atr_mean_reversion import create_atr_mean_reversion_engine
        param_grid = {"max_loss": [100_000], "kc_len": [20]}
        result = self.opt.grid_search(
            create_atr_mean_reversion_engine, param_grid,
            self.bars, self.ts, is_fraction=0.8,
        )
        assert result.best_oos_result is not None

    def test_is_oos_bar_counts(self) -> None:
        from src.strategies.intraday.mean_reversion.atr_mean_reversion import create_atr_mean_reversion_engine
        param_grid = {"max_loss": [100_000], "kc_len": [20]}
        result = self.opt.grid_search(
            create_atr_mean_reversion_engine, param_grid,
            self.bars, self.ts, is_fraction=0.8,
        )
        # IS has 80% of 200 = 160 bars, OOS has 40 bars
        # equity curve length = n_bars + 1
        assert len(result.best_is_result.equity_curve) == 161
        assert len(result.best_oos_result.equity_curve) == 41  # type: ignore[union-attr]

    def test_bad_objective_raises(self) -> None:
        from src.strategies.intraday.mean_reversion.atr_mean_reversion import create_atr_mean_reversion_engine
        with pytest.raises(ValueError, match="nonexistent_metric"):
            self.opt.grid_search(
                create_atr_mean_reversion_engine,
                {"max_loss": [100_000], "kc_len": [20]},
                self.bars, self.ts,
                objective="nonexistent_metric",
            )

    def test_lambda_factory_with_njobs_raises(self) -> None:
        parallel_opt = StrategyOptimizer(adapter=self.adapter, n_jobs=2)
        with pytest.raises(ValueError, match="lambda"):
            parallel_opt.grid_search(
                lambda **kw: None,  # type: ignore[return-value, arg-type]
                {"max_loss": [100_000]},
                self.bars, self.ts,
            )


# ---------------------------------------------------------------------------
# StrategyOptimizer.walk_forward — structural tests
# ---------------------------------------------------------------------------

class TestWalkForward:
    def setup_method(self) -> None:
        self.bars, self.ts = _make_bars(500)
        self.adapter = _make_mock_adapter()
        self.opt = StrategyOptimizer(adapter=self.adapter, n_jobs=1)

    def test_window_count_formula(self) -> None:
        """(total_bars - train_bars) // test_bars"""
        from src.strategies.intraday.mean_reversion.atr_mean_reversion import create_atr_mean_reversion_engine
        train, test = 200, 50
        result = self.opt.walk_forward(
            create_atr_mean_reversion_engine,
            {"max_loss": [100_000], "kc_len": [20]},
            self.bars, self.ts,
            train_bars=train, test_bars=test,
        )
        expected = (500 - train) // test
        assert len(result.windows) == expected

    def test_raises_on_insufficient_bars(self) -> None:
        from src.strategies.intraday.mean_reversion.atr_mean_reversion import create_atr_mean_reversion_engine
        with pytest.raises(ValueError, match="exceeds total bars"):
            self.opt.walk_forward(
                create_atr_mean_reversion_engine,
                {"max_loss": [100_000], "kc_len": [20]},
                self.bars[:100], self.ts[:100],
                train_bars=80, test_bars=50,
            )

    def test_no_bar_overlap_between_is_and_oos(self) -> None:
        from src.strategies.intraday.mean_reversion.atr_mean_reversion import create_atr_mean_reversion_engine
        train, test = 200, 50
        result = self.opt.walk_forward(
            create_atr_mean_reversion_engine,
            {"max_loss": [100_000], "kc_len": [20]},
            self.bars, self.ts,
            train_bars=train, test_bars=test,
        )
        for w in result.windows:
            assert w.is_bars == train
            assert w.oos_bars == test

    def test_efficiency_is_float(self) -> None:
        from src.strategies.intraday.mean_reversion.atr_mean_reversion import create_atr_mean_reversion_engine
        result = self.opt.walk_forward(
            create_atr_mean_reversion_engine,
            {"max_loss": [100_000], "kc_len": [20]},
            self.bars, self.ts,
            train_bars=200, test_bars=50,
        )
        assert isinstance(result.efficiency, float)
        assert not math.isnan(result.efficiency)
