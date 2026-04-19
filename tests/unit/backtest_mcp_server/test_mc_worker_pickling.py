"""MC worker pickling tests for the Pin-by-Hash refactor.

Verifies that a strategy compiled through ``pinned_loader.load_pinned_strategy``
produces artifacts picklable across the ProcessPoolExecutor boundary. The
synthetic module is registered in ``sys.modules`` under a unique qualified
name, so classes defined in the pinned source survive ``pickle.dumps`` and can
round-trip back in a worker process.

We exercise ``_mc_single_path`` end-to-end via an in-process
``ProcessPoolExecutor`` — which is how ``run_monte_carlo_for_mcp`` invokes
workers when ``n_paths >= 20``. We keep the work set small so the test is fast.
"""
from __future__ import annotations

import os
import pickle
from concurrent.futures import ProcessPoolExecutor

import pytest

from src.mcp_server import facade
from src.simulator.types import PathConfig


@pytest.fixture(autouse=True)
def _clear_pin_caches():
    facade._factory_cache_by_hash.clear()
    facade._warned_drift_slugs.clear()
    facade._warned_fallback_slugs.clear()
    yield
    facade._factory_cache_by_hash.clear()


def _make_path_config(n_bars: int = 100) -> PathConfig:
    return PathConfig(
        drift=0.0, volatility=0.01,
        garch_omega=0.0, garch_alpha=0.0, garch_beta=0.0,
        student_t_df=0.0,
        jump_intensity=0.0, jump_mean=0.0, jump_std=0.0,
        ou_theta=0.0, ou_mu=0.0, ou_sigma=0.0,
        n_bars=n_bars, start_price=20000.0, seed=42,
    )


def test_8tuple_matches_6tuple_results(monkeypatch):
    """``_mc_single_path`` produces the same (pnl, dd, sharpe) regardless of
    whether the pinned-hash+code pair is provided (new 8-tuple) or omitted
    (legacy 6-tuple)."""
    monkeypatch.setenv("QUANT_PINNED_EXECUTION", "1")

    strategy = "short_term/mean_reversion/spread_reversion"
    # Pull the real active-candidate pin so both branches resolve identically.
    active_hash, active_code, _ = facade._fetch_active_pin(strategy)
    if not (active_hash and active_code):
        pytest.skip("No active pin for spread_reversion; skipping")

    path_config = _make_path_config()
    six = (strategy, {}, 0, path_config, "daily", 1)
    eight = (strategy, {}, 0, path_config, "daily", 1, active_hash, active_code)

    r_six = facade._mc_single_path(six)
    r_eight = facade._mc_single_path(eight)
    assert r_six == r_eight


def test_pinned_factory_is_picklable(monkeypatch):
    """A pinned factory returned by ``resolve_factory_by_hash`` survives a
    ``pickle.dumps/loads`` round-trip — the invariant ProcessPoolExecutor
    relies on when dispatching work items that indirectly reference it."""
    monkeypatch.setenv("QUANT_PINNED_EXECUTION", "1")

    strategy = "short_term/mean_reversion/spread_reversion"
    active_hash, active_code, _ = facade._fetch_active_pin(strategy)
    if not (active_hash and active_code):
        pytest.skip("No active pin for spread_reversion; skipping")

    factory, _ = facade.resolve_factory_by_hash(
        strategy, strategy_hash=active_hash, strategy_code=active_code,
    )
    dumped = pickle.dumps(factory)
    loaded = pickle.loads(dumped)
    assert loaded is factory or loaded.__name__ == factory.__name__


@pytest.mark.skipif(
    os.environ.get("CI") == "true",
    reason="ProcessPoolExecutor in CI can be flaky due to fork semantics",
)
def test_mc_parallel_matches_serial(monkeypatch):
    """Small MC parallel run produces the same aggregate stats as serial."""
    monkeypatch.setenv("QUANT_PINNED_EXECUTION", "1")

    strategy = "short_term/mean_reversion/spread_reversion"
    active_hash, active_code, _ = facade._fetch_active_pin(strategy)
    if not (active_hash and active_code):
        pytest.skip("No active pin for spread_reversion; skipping")

    path_config = _make_path_config(n_bars=80)
    items = [
        (strategy, {}, i, path_config, "daily", 1, active_hash, active_code)
        for i in range(4)
    ]

    serial = [facade._mc_single_path(x) for x in items]
    with ProcessPoolExecutor(max_workers=2) as pool:
        parallel = list(pool.map(facade._mc_single_path, items))

    assert serial == parallel
