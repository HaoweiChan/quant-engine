"""Unit tests for live correlation monitor."""
from __future__ import annotations

import numpy as np
import pytest

from src.monitoring.correlation_monitor import (
    CorrelationMonitor,
    CorrelationMonitorConfig,
)


class TestConstruction:
    def test_requires_at_least_two_strategies(self) -> None:
        with pytest.raises(ValueError, match="at least 2"):
            CorrelationMonitor(["only"])

    def test_rejects_unknown_strategy_update(self) -> None:
        m = CorrelationMonitor(["a", "b"])
        # Silently ignores unknown (with warning log — not an exception)
        m.update("nonexistent", 0.01)
        assert len(m._buffers) == 2


class TestCorrelationComputation:
    def test_identity_when_buffer_too_small(self) -> None:
        cfg = CorrelationMonitorConfig(min_observations=100)
        m = CorrelationMonitor(["a", "b"], cfg)
        # Only 10 observations — below min
        for i in range(10):
            m.update_all({"a": 0.01 * i, "b": 0.005 * i})
        corr = m.current_correlation_matrix()
        assert corr == [[1.0, 0.0], [0.0, 1.0]]

    def test_perfectly_correlated_returns(self) -> None:
        cfg = CorrelationMonitorConfig(min_observations=50)
        m = CorrelationMonitor(["a", "b"], cfg)
        rng = np.random.default_rng(1)
        for _ in range(100):
            r = rng.normal(0, 0.01)
            m.update_all({"a": r, "b": r})
        corr = np.array(m.current_correlation_matrix())
        assert abs(corr[0, 1] - 1.0) < 1e-6

    def test_uncorrelated_returns(self) -> None:
        cfg = CorrelationMonitorConfig(min_observations=50)
        m = CorrelationMonitor(["a", "b"], cfg)
        rng = np.random.default_rng(2)
        for _ in range(500):
            m.update_all({
                "a": float(rng.normal(0, 0.01)),
                "b": float(rng.normal(0, 0.01)),
            })
        corr = np.array(m.current_correlation_matrix())
        # ~0 but noisy — be generous
        assert abs(corr[0, 1]) < 0.15


class TestDriftTrigger:
    def test_no_trigger_when_correlations_stable(self) -> None:
        cfg = CorrelationMonitorConfig(min_observations=50, drift_threshold=0.2)
        m = CorrelationMonitor(["a", "b"], cfg)
        # Stream uncorrelated data
        rng = np.random.default_rng(42)
        for _ in range(500):
            m.update_all({
                "a": float(rng.normal(0, 0.01)),
                "b": float(rng.normal(0, 0.01)),
            })
        baseline = np.eye(2)
        event = m.check_drift(baseline)
        assert event.triggered is False
        assert event.max_delta < 0.2

    def test_trigger_when_correlation_diverges(self) -> None:
        cfg = CorrelationMonitorConfig(min_observations=50, drift_threshold=0.2)
        m = CorrelationMonitor(["a", "b"], cfg)
        rng = np.random.default_rng(7)
        # Stream strongly-correlated returns
        for _ in range(500):
            base = float(rng.normal(0, 0.01))
            m.update_all({
                "a": base,
                "b": base + float(rng.normal(0, 0.001)),  # tiny noise → corr ~1
            })
        # Baseline says they were uncorrelated
        baseline = np.array([[1.0, 0.0], [0.0, 1.0]])
        event = m.check_drift(baseline)
        assert event.triggered is True
        assert event.max_delta > 0.2
        assert len(event.pairs_drifted) == 1
        slug1, slug2, b_val, c_val = event.pairs_drifted[0]
        assert {slug1, slug2} == {"a", "b"}
        assert b_val == 0.0
        assert abs(c_val) > 0.2

    def test_sharpe_drift_trigger(self) -> None:
        cfg = CorrelationMonitorConfig(
            min_observations=50,
            drift_threshold=0.9,          # impossible threshold → never corr-trigger
            sharpe_drift_trigger=0.5,
        )
        m = CorrelationMonitor(["a", "b"], cfg)
        rng = np.random.default_rng(0)
        for _ in range(500):
            m.update_all({
                "a": float(rng.normal(0, 0.01)),
                "b": float(rng.normal(0, 0.01)),
            })
        event = m.check_drift(
            baseline_correlation=np.eye(2),
            trailing_sharpe=0.5,
            backtest_sharpe=2.0,
        )
        # 0.5 / 2.0 = 0.25 < 0.5 threshold
        assert event.triggered is True
        assert event.sharpe_triggered is True
        assert event.sharpe_ratio == pytest.approx(0.25)

    def test_sharpe_ok_when_above_threshold(self) -> None:
        cfg = CorrelationMonitorConfig(
            min_observations=50,
            drift_threshold=0.9,
            sharpe_drift_trigger=0.5,
        )
        m = CorrelationMonitor(["a", "b"], cfg)
        rng = np.random.default_rng(0)
        for _ in range(200):
            m.update_all({
                "a": float(rng.normal(0, 0.01)),
                "b": float(rng.normal(0, 0.01)),
            })
        event = m.check_drift(
            baseline_correlation=np.eye(2),
            trailing_sharpe=1.8,  # 1.8 / 2.0 = 0.9 > 0.5 trigger
            backtest_sharpe=2.0,
        )
        assert event.triggered is False
        assert event.sharpe_triggered is False

    def test_baseline_shape_validation(self) -> None:
        m = CorrelationMonitor(["a", "b"])
        with pytest.raises(ValueError, match="baseline correlation shape"):
            m.check_drift(np.zeros((3, 3)))


class TestReset:
    def test_reset_clears_all_buffers(self) -> None:
        m = CorrelationMonitor(["a", "b"])
        for _ in range(100):
            m.update_all({"a": 0.01, "b": 0.02})
        assert len(m._buffers["a"]) == 100
        m.reset()
        assert len(m._buffers["a"]) == 0
        assert len(m._buffers["b"]) == 0
