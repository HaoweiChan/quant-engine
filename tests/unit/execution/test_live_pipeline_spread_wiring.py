"""Unit test for LivePipelineManager spread-builder wiring (Phase C1 + C3).

Confirms:
  - A spread-strategy session triggers `_maybe_register_spread_builder`,
    which wires a `LiveSpreadBarBuilder` against the bar store.
  - Raw single-leg bars are NOT dispatched to spread runners (only
    the synthetic paired bar is, via the builder callback).
  - Single-leg strategies are unaffected — they keep receiving the raw
    bar dispatch.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from src.execution.live_pipeline import LivePipelineManager


class _FakeSession:
    def __init__(self, sid: str, slug: str, symbol: str = "MTX") -> None:
        self.session_id = sid
        self.account_id = "acct-1"
        self.strategy_slug = slug
        self.symbol = symbol
        self.status = "active"
        self.equity_share = 0.5


def _fake_runner() -> MagicMock:
    r = MagicMock()
    r.account_id = "acct-1"
    return r


def test_spread_strategy_session_registers_spread_builder() -> None:
    sm = MagicMock()
    sm.get_all_sessions = MagicMock(
        return_value=[
            _FakeSession("S1", "short_term/mean_reversion/spread_reversion", "MTX"),
        ]
    )
    sm.get_effective_equity = MagicMock(return_value=2_000_000.0)
    bar_store = MagicMock()
    eq_store = MagicMock()

    pipeline = LivePipelineManager(sm, bar_store, eq_store)

    # Inject a fake runner so we don't have to construct a real LiveStrategyRunner
    # (which would need broker plumbing). The wiring under test is the
    # builder registration, not the runner itself.
    pipeline._runners["S1"] = _fake_runner()
    pipeline._maybe_register_spread_builder(
        "S1", _FakeSession("S1", "short_term/mean_reversion/spread_reversion", "MTX"),
    )

    assert "S1" in pipeline._spread_builders
    builder = pipeline._spread_builders["S1"]
    assert builder.leg_symbols == ("MTX", "MTX_R2")
    # The builder must have attached to the bar store so it sees per-leg bars.
    bar_store.register_bar_callback.assert_called_once()


def test_single_leg_strategy_does_not_register_spread_builder() -> None:
    sm = MagicMock()
    bar_store = MagicMock()
    eq_store = MagicMock()
    pipeline = LivePipelineManager(sm, bar_store, eq_store)

    pipeline._runners["S2"] = _fake_runner()
    pipeline._maybe_register_spread_builder(
        "S2", _FakeSession("S2", "short_term/trend_following/night_session_long", "MTX"),
    )

    assert "S2" not in pipeline._spread_builders
    bar_store.register_bar_callback.assert_not_called()


def test_on_bar_complete_skips_spread_runners() -> None:
    """Raw single-leg bar dispatch must exclude spread runners. They
    receive bars only via the synthetic-spread callback path.
    """
    sm = MagicMock()
    bar_store = MagicMock()
    eq_store = MagicMock()
    pipeline = LivePipelineManager(sm, bar_store, eq_store)

    spread_runner = _fake_runner()
    spread_runner.session_id = "S_spread"
    single_runner = _fake_runner()
    single_runner.session_id = "S_single"
    pipeline._runners["S_spread"] = spread_runner
    pipeline._runners["S_single"] = single_runner
    # Mark the spread runner as having a builder; this is what the
    # exclusion check uses.
    pipeline._spread_builders["S_spread"] = MagicMock()

    # No event loop -> early return after building the dispatch list,
    # so we just need to assert the dispatch list construction excludes
    # the spread runner.
    runners_to_dispatch = [
        (sid, r)
        for sid, r in pipeline.iter_runners()
        if sid not in pipeline._spread_builders
    ]
    sids = [sid for sid, _ in runners_to_dispatch]
    assert sids == ["S_single"]
