"""Unit tests for walk-forward validation engine."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.simulator.walk_forward import (
    FoldResult,
    WalkForwardResult,
    build_walk_forward_result,
    classify_overfit,
    compute_expanding_folds,
    compute_overfit_ratio,
    evaluate_quality_gates,
    filter_bars_by_session,
)


class TestComputeExpandingFolds:
    def test_three_folds_on_1000_bars(self) -> None:
        ts = [datetime(2020, 1, 1) + timedelta(days=i) for i in range(1000)]
        folds = compute_expanding_folds(ts, n_folds=3, oos_fraction=0.2)
        assert len(folds) == 3
        for is_idx, oos_idx in folds:
            assert len(is_idx) > 0
            assert len(oos_idx) > 0
            # OOS follows IS
            assert max(is_idx) < min(oos_idx)

    def test_expanding_is_windows(self) -> None:
        ts = [datetime(2020, 1, 1) + timedelta(days=i) for i in range(1000)]
        folds = compute_expanding_folds(ts, n_folds=3, oos_fraction=0.2)
        # Each fold's IS should be larger than the previous
        is_sizes = [len(is_idx) for is_idx, _ in folds]
        assert is_sizes == sorted(is_sizes)

    def test_oos_windows_same_size(self) -> None:
        ts = [datetime(2020, 1, 1) + timedelta(days=i) for i in range(1000)]
        folds = compute_expanding_folds(ts, n_folds=3, oos_fraction=0.2)
        oos_sizes = [len(oos_idx) for _, oos_idx in folds]
        # All OOS windows should be the same size
        assert len(set(oos_sizes)) == 1

    def test_no_overlap_between_is_and_oos(self) -> None:
        ts = [datetime(2020, 1, 1) + timedelta(days=i) for i in range(500)]
        folds = compute_expanding_folds(ts, n_folds=3, oos_fraction=0.2)
        for is_idx, oos_idx in folds:
            assert not set(is_idx) & set(oos_idx)


class TestFilterBarsBySession:
    def _make_bars(self, hours: list[int]) -> tuple[list[dict], list[datetime]]:
        bars = [{"close": 20000 + i} for i in range(len(hours))]
        timestamps = [datetime(2024, 1, 2, h, 0) for h in hours]
        return bars, timestamps

    def test_all_session(self) -> None:
        bars, ts = self._make_bars([9, 10, 11, 15, 16, 17])
        filtered_bars, filtered_ts, _ = filter_bars_by_session(bars, ts, "all")
        assert len(filtered_bars) == 6

    def test_day_session_filter(self) -> None:
        bars, ts = self._make_bars([8, 9, 10, 13, 14, 15, 16])
        _, _, indices = filter_bars_by_session(bars, ts, "day")
        filtered_hours = [ts[i].hour for i in indices]
        # Should include 9, 10, 13 (within 08:45-13:45)
        assert all(8 <= h <= 13 for h in filtered_hours)
        assert 15 not in filtered_hours
        assert 16 not in filtered_hours

    def test_night_session_filter(self) -> None:
        bars, ts = self._make_bars([3, 4, 9, 10, 15, 16, 22])
        _, _, indices = filter_bars_by_session(bars, ts, "night")
        filtered_hours = [ts[i].hour for i in indices]
        # Should include 3, 4, 15, 16, 22
        assert 9 not in filtered_hours
        assert 10 not in filtered_hours


class TestOverfitClassification:
    def test_no_overfit(self) -> None:
        assert classify_overfit(0.8) == "none"
        assert classify_overfit(0.7) == "none"
        assert classify_overfit(1.0) == "none"

    def test_mild_overfit(self) -> None:
        assert classify_overfit(0.5) == "mild"
        assert classify_overfit(0.3) == "mild"

    def test_severe_overfit(self) -> None:
        assert classify_overfit(0.29) == "severe"
        assert classify_overfit(0.0) == "severe"


class TestComputeOverfitRatio:
    def test_positive_ratio(self) -> None:
        assert compute_overfit_ratio(1.0, 0.8) == pytest.approx(0.8)

    def test_negative_oos_returns_zero(self) -> None:
        assert compute_overfit_ratio(1.0, -0.5) == 0.0

    def test_negative_is_returns_zero(self) -> None:
        assert compute_overfit_ratio(-0.5, 0.5) == 0.0


class TestQualityGates:
    def _make_fold(self, **overrides) -> FoldResult:
        defaults = {
            "fold_index": 0,
            "is_start": datetime(2020, 1, 1),
            "is_end": datetime(2021, 1, 1),
            "oos_start": datetime(2021, 1, 1),
            "oos_end": datetime(2022, 1, 1),
            "is_best_params": {},
            "is_sharpe": 1.2,
            "oos_sharpe": 0.9,
            "oos_mdd_pct": 0.15,
            "oos_win_rate": 0.50,
            "oos_n_trades": 50,
            "oos_profit_factor": 1.5,
            "overfit_ratio": 0.75,
        }
        defaults.update(overrides)
        return FoldResult(**defaults)

    def test_all_pass(self) -> None:
        folds = [self._make_fold(fold_index=i) for i in range(3)]
        passed, reasons = evaluate_quality_gates(folds, 1.1, "none")
        assert passed is True
        assert reasons == []

    def test_low_aggregate_sharpe(self) -> None:
        folds = [self._make_fold(fold_index=i) for i in range(3)]
        passed, reasons = evaluate_quality_gates(folds, 0.4, "none")
        assert passed is False
        assert any("Aggregate OOS Sharpe" in r for r in reasons)

    def test_severe_overfit(self) -> None:
        folds = [self._make_fold(fold_index=i) for i in range(3)]
        passed, reasons = evaluate_quality_gates(folds, 0.9, "severe")
        assert passed is False
        assert any("Severe overfit" in r for r in reasons)

    def test_high_mdd(self) -> None:
        folds = [self._make_fold(fold_index=0, oos_mdd_pct=25.0)]
        passed, reasons = evaluate_quality_gates(folds, 0.9, "none")
        assert passed is False
        assert any("MDD" in r for r in reasons)

    def test_low_trade_count(self) -> None:
        folds = [self._make_fold(fold_index=0, oos_n_trades=10)]
        passed, reasons = evaluate_quality_gates(folds, 0.9, "none")
        assert passed is False
        assert any("trades" in r for r in reasons)

    def test_low_profit_factor(self) -> None:
        folds = [self._make_fold(fold_index=0, oos_profit_factor=0.9)]
        passed, reasons = evaluate_quality_gates(folds, 0.9, "none")
        assert passed is False
        assert any("Profit factor" in r for r in reasons)


class TestBuildWalkForwardResult:
    def _make_fold(self, idx: int, is_sharpe: float, oos_sharpe: float) -> FoldResult:
        ratio = compute_overfit_ratio(is_sharpe, oos_sharpe)
        return FoldResult(
            fold_index=idx,
            is_start=datetime(2020, 1, 1),
            is_end=datetime(2021, 1, 1),
            oos_start=datetime(2021, 1, 1),
            oos_end=datetime(2022, 1, 1),
            is_best_params={},
            is_sharpe=is_sharpe,
            oos_sharpe=oos_sharpe,
            oos_mdd_pct=0.10,
            oos_win_rate=0.50,
            oos_n_trades=50,
            oos_profit_factor=1.5,
            overfit_ratio=ratio,
        )

    def test_passing_result(self) -> None:
        folds = [self._make_fold(i, 1.5, 1.1) for i in range(3)]
        result = build_walk_forward_result(folds)
        assert result.passed is True
        assert result.overfit_flag == "none"

    def test_severe_overfit_result(self) -> None:
        folds = [self._make_fold(i, 2.0, 0.3) for i in range(3)]
        result = build_walk_forward_result(folds)
        assert result.overfit_flag == "severe"
        assert result.passed is False

    def test_empty_folds(self) -> None:
        result = build_walk_forward_result([])
        assert result.passed is False
        assert "No folds computed" in result.failure_reasons
