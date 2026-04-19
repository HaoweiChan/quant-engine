"""Unit tests for ``facade.resolve_factory_by_hash``.

Covers the Phase 1 acceptance criteria in the Pin-by-Hash refactor plan:
- LRU cache: second call with the same ``(slug, hash)`` returns the cached
  factory object and does not re-exec the source.
- LRU eviction when the cache exceeds ``_PIN_CACHE_MAX``.
- Fallback to ``resolve_factory`` when no active pin exists.
- Explicit ``strategy_hash`` with no matching row raises ``StrategyHashNotFound``.
- Flag ``QUANT_PINNED_EXECUTION=0`` skips the pin resolver entirely.
"""
from __future__ import annotations

import hashlib

import pytest

from src.mcp_server import facade
from src.mcp_server.facade import (
    PinnedExecutionError,
    StrategyHashNotFound,
    resolve_factory_by_hash,
)


_MINIMAL_SOURCE = """
STRATEGY_META = {"tradeable_sessions": ["day"]}
PARAM_SCHEMA = {}

class _Marker:
    pass

def create_minimal_engine():
    return _Marker()
"""


def _sha(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


@pytest.fixture(autouse=True)
def _enable_pinning_and_reset(monkeypatch):
    """Enable the pin flag and clear caches between tests."""
    monkeypatch.setenv("QUANT_PINNED_EXECUTION", "1")
    facade._factory_cache_by_hash.clear()
    facade._warned_drift_slugs.clear()
    facade._warned_fallback_slugs.clear()
    yield
    facade._factory_cache_by_hash.clear()
    facade._warned_drift_slugs.clear()
    facade._warned_fallback_slugs.clear()


def _patch_factory_name(monkeypatch, slug_to_factory: dict[str, str]) -> None:
    """Stub ``get_info(slug).factory`` for fake slugs used in these tests."""
    from src.strategies import registry

    real_get_info = registry.get_info

    def fake_get_info(slug):
        if slug in slug_to_factory:
            from src.strategies.registry import StrategyInfo

            return StrategyInfo(
                name=slug,
                slug=slug,
                module=f"pinned_{slug}",
                factory=slug_to_factory[slug],
                param_schema={},
                meta={},
            )
        return real_get_info(slug)

    monkeypatch.setattr("src.strategies.registry.get_info", fake_get_info)


def test_explicit_code_compiles_and_caches(monkeypatch):
    _patch_factory_name(monkeypatch, {"fake/rbh/cache": "create_minimal_engine"})
    h = _sha(_MINIMAL_SOURCE)

    f1, m1 = resolve_factory_by_hash("fake/rbh/cache", h, _MINIMAL_SOURCE)
    f2, m2 = resolve_factory_by_hash("fake/rbh/cache", h)  # cache hit, no code

    assert f1 is f2
    assert m1 == m2
    assert ("fake/rbh/cache", h) in facade._factory_cache_by_hash


def test_lru_eviction(monkeypatch):
    """Inserting past ``_PIN_CACHE_MAX`` evicts the oldest entry."""
    _patch_factory_name(
        monkeypatch,
        {f"fake/rbh/lru_{i}": "create_minimal_engine" for i in range(5)},
    )
    monkeypatch.setattr(facade, "_PIN_CACHE_MAX", 3)

    hashes = []
    for i in range(4):
        src = _MINIMAL_SOURCE + f"\n# marker {i}\n"
        h = _sha(src)
        hashes.append(h)
        resolve_factory_by_hash(f"fake/rbh/lru_{i}", h, src)

    # Oldest (i=0) should have been evicted.
    assert ("fake/rbh/lru_0", hashes[0]) not in facade._factory_cache_by_hash
    assert ("fake/rbh/lru_3", hashes[3]) in facade._factory_cache_by_hash
    assert len(facade._factory_cache_by_hash) == 3


def test_hash_not_found_raises(monkeypatch):
    _patch_factory_name(monkeypatch, {"fake/rbh/missing": "create_minimal_engine"})

    # Simulate ``get_code_by_hash`` returning no row.
    monkeypatch.setattr(facade, "_fetch_code_by_hash", lambda slug, h: (None, None))

    with pytest.raises(StrategyHashNotFound):
        resolve_factory_by_hash("fake/rbh/missing", "deadbeef" * 8)


def test_no_active_pin_falls_back_to_current_file(monkeypatch):
    """When no hash/code is provided and no active candidate exists, use file."""
    called: dict[str, bool] = {"fallback": False}

    def fake_resolve(slug):
        called["fallback"] = True
        return lambda **kw: object()

    monkeypatch.setattr(facade, "resolve_factory", fake_resolve)
    monkeypatch.setattr(facade, "_fetch_active_pin", lambda slug: (None, None, None))

    from src.strategies.registry import StrategyInfo

    monkeypatch.setattr(
        "src.strategies.registry.get_info",
        lambda slug: StrategyInfo(
            name=slug, slug=slug, module="m", factory="f",
            param_schema={}, meta={"tradeable_sessions": ["day"]},
        ),
    )

    factory, meta = resolve_factory_by_hash("fake/rbh/nopin")
    assert called["fallback"] is True
    assert callable(factory)
    assert meta["tradeable_sessions"] == ["day"]


def test_flag_off_skips_pin_entirely(monkeypatch):
    monkeypatch.setenv("QUANT_PINNED_EXECUTION", "0")

    calls: dict[str, int] = {"resolve_factory": 0, "active_pin": 0}

    def fake_resolve(slug):
        calls["resolve_factory"] += 1
        return lambda **kw: object()

    def fake_active(slug):
        calls["active_pin"] += 1
        return ("h", "code", {})

    monkeypatch.setattr(facade, "resolve_factory", fake_resolve)
    monkeypatch.setattr(facade, "_fetch_active_pin", fake_active)

    from src.strategies.registry import StrategyInfo
    monkeypatch.setattr(
        "src.strategies.registry.get_info",
        lambda slug: StrategyInfo(
            name=slug, slug=slug, module="m", factory="f",
            param_schema={}, meta={},
        ),
    )

    resolve_factory_by_hash("fake/rbh/flagoff")
    # Even when an active pin would be available, flag=0 short-circuits.
    assert calls["resolve_factory"] == 1
    assert calls["active_pin"] == 0


def test_compile_failure_raises_pinned_execution_error(monkeypatch):
    _patch_factory_name(monkeypatch, {"fake/rbh/brokenpin": "create_minimal_engine"})
    broken = "def create_minimal_engine(: pass"  # syntax error
    with pytest.raises(PinnedExecutionError):
        resolve_factory_by_hash("fake/rbh/brokenpin", _sha(broken), broken)
