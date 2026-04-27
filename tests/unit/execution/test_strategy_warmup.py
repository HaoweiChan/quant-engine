"""Tests for ``src/execution/strategy_warmup.py`` and warmup_mode flag."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from src.core.policies import (
    ChandelierStopPolicy,
    NoAddPolicy,
    PyramidEntryPolicy,
)
from src.core.position_engine import PositionEngine
from src.core.types import EngineConfig, PyramidConfig
from src.strategies.registry import get_warmup_bars
from tests.conftest import make_signal, make_snapshot


# -- warmup_mode flag in PositionEngine ----------------------------------


@pytest.fixture
def engine(contract_specs):
    config = PyramidConfig(max_loss=500_000.0)
    engine_config = EngineConfig(max_loss=config.max_loss)
    return PositionEngine(
        entry_policy=PyramidEntryPolicy(config),
        add_policy=NoAddPolicy(),
        stop_policy=ChandelierStopPolicy(config),
        config=engine_config,
    )


class TestWarmupMode:
    def test_warmup_emits_no_orders(self, engine, contract_specs):
        snap = make_snapshot(20000.0, contract_specs)
        signal = make_signal(direction=1.0, direction_conf=0.95)
        orders = engine.on_snapshot(snap, signal, account=None, warmup_mode=True)
        assert orders == []

    def test_warmup_does_not_open_positions(self, engine, contract_specs):
        snap = make_snapshot(20000.0, contract_specs)
        signal = make_signal(direction=1.0, direction_conf=0.95)
        engine.on_snapshot(snap, signal, account=None, warmup_mode=True)
        assert engine.get_state().positions == ()

    def test_warmup_then_live_emits_entry(self, engine, contract_specs):
        # Replay 50 warmup bars then one live bar with strong signal.
        for i in range(50):
            warmup_snap = make_snapshot(
                20000.0 + i,
                contract_specs,
                ts=datetime.now(UTC) - timedelta(minutes=50 - i),
            )
            engine.on_snapshot(
                warmup_snap, signal=None, account=None, warmup_mode=True,
            )
        assert engine.get_state().positions == ()
        live_snap = make_snapshot(20050.0, contract_specs)
        live_signal = make_signal(direction=1.0, direction_conf=0.95)
        orders = engine.on_snapshot(live_snap, live_signal, account=None)
        assert any(o.reason == "entry" for o in orders)

    def test_warmup_populates_high_history(self, engine, contract_specs):
        prices = [20000.0 + i for i in range(20)]
        for p in prices:
            engine.on_snapshot(
                make_snapshot(p, contract_specs), signal=None, account=None,
                warmup_mode=True,
            )
        # Internal state hydrated even though no orders flowed out.
        assert len(engine._high_history) == 20  # noqa: SLF001
        assert engine._high_history[-1] == prices[-1]  # noqa: SLF001


# -- get_warmup_bars registry helper -------------------------------------


class TestGetWarmupBars:
    def test_default_bars_for_unknown_strategy(self):
        # An unknown slug should return the default and never crash.
        n = get_warmup_bars("__nonexistent__/__no__")
        assert n >= 50

    def test_real_strategy_returns_positive(self):
        # ema_trend_pullback uses ema_trend=144 by default.
        n = get_warmup_bars("medium_term/trend_following/ema_trend_pullback")
        assert n >= 50
        assert n <= 5000

    def test_clamped_within_bounds(self):
        n = get_warmup_bars("__nonexistent__")
        assert 50 <= n <= 5000


# -- StrategyWarmup integration ------------------------------------------


@dataclass
class _Row:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class _StubDB:
    def __init__(self, rows):
        self._rows = rows

    def get_ohlcv(self, symbol, start, end):
        return [r for r in self._rows if start <= r.timestamp <= end]


class _StubAdapter:
    def __init__(self, contract_specs):
        self._specs = contract_specs

    def get_contract_specs(self, _symbol):
        return self._specs


class _StubRunner:
    """Minimal duck-typed LiveStrategyRunner for warmup tests."""

    def __init__(self, engine, contract_specs):
        self.session_id = "sess-1"
        self.symbol = "TXF"
        self.strategy_slug = "medium_term/trend_following/ema_trend_pullback"
        self._engine = engine
        self._adapter = _StubAdapter(contract_specs)

    def _bar_to_snapshot(self, bar):
        return make_snapshot(bar.close, self._adapter._specs, ts=bar.timestamp)


def _bars(n: int, start_price: float = 20000.0):
    base = datetime(2026, 4, 25, 9, 0, tzinfo=UTC)
    return [
        _Row(
            timestamp=base + timedelta(minutes=i),
            open=start_price + i,
            high=start_price + i + 1,
            low=start_price + i - 1,
            close=start_price + i,
            volume=10.0,
        )
        for i in range(n)
    ]


class TestStrategyWarmup:
    def test_replay_with_no_bars_returns_zero(self, engine, contract_specs):
        from src.execution.strategy_warmup import StrategyWarmup

        runner = _StubRunner(engine, contract_specs)
        warmup = StrategyWarmup(runner, db=_StubDB([]), lookback_bars=100)
        replayed = warmup.run(end=datetime(2026, 4, 25, 10, 0, tzinfo=UTC))
        assert replayed == 0

    def test_replay_hydrates_history_without_orders(self, engine, contract_specs):
        from src.execution.strategy_warmup import StrategyWarmup

        runner = _StubRunner(engine, contract_specs)
        warmup = StrategyWarmup(runner, db=_StubDB(_bars(120)), lookback_bars=200)
        # Last bar in _bars() is at 10:59 (120 bars from 09:00). Pin end
        # to that timestamp so the 200*1.5=300-minute lookback window
        # covers all seeded bars.
        end = datetime(2026, 4, 25, 10, 59, tzinfo=UTC)
        replayed = warmup.run(end=end)
        assert replayed == 120
        assert engine.get_state().positions == ()
        # _high_history is a bounded deque (trail_lookback=22 default), so
        # confirm hydration by checking it's saturated to its cap rather
        # than equal to the bar count.
        assert len(engine._high_history) == engine._high_history.maxlen  # noqa: SLF001
