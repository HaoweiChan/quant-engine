"""Spread-META hash-awareness tests for the Pin-by-Hash refactor.

``_get_spread_meta`` now takes a ``pinned_meta`` override so spread-leg
routing stays consistent with whichever source the engine is actually
executing. This prevents the class of bugs where ``STRATEGY_META`` is
edited on disk (e.g., legs renamed) while the engine runs pinned code that
still expects the original legs.
"""
from __future__ import annotations

import pytest

from src.mcp_server.facade import _get_spread_meta


class _FakeInfo:
    def __init__(self, meta):
        self.meta = meta


def test_pinned_meta_wins_over_current_file(monkeypatch):
    """Pinned META legs are returned even when the current file has different legs."""
    monkeypatch.setattr(
        "src.strategies.registry.get_info",
        lambda slug: _FakeInfo({"spread_legs": ["MTX", "MTX_R2"], "extra": "current"}),
    )
    pinned = {"spread_legs": ["TX", "TX_R2"], "extra": "pinned"}
    result = _get_spread_meta("any/slug", pinned_meta=pinned)
    assert result is pinned
    assert result["spread_legs"] == ["TX", "TX_R2"]
    assert result["extra"] == "pinned"


def test_pinned_meta_without_legs_falls_back_to_current(monkeypatch):
    """A pinned META that lacks ``spread_legs`` must not override the current file."""
    monkeypatch.setattr(
        "src.strategies.registry.get_info",
        lambda slug: _FakeInfo({"spread_legs": ["TX", "TX_R2"]}),
    )
    pinned = {"some_other_key": 1}
    result = _get_spread_meta("any/slug", pinned_meta=pinned)
    assert result is not None
    assert result["spread_legs"] == ["TX", "TX_R2"]


def test_no_spread_legs_anywhere_returns_none(monkeypatch):
    monkeypatch.setattr(
        "src.strategies.registry.get_info",
        lambda slug: _FakeInfo({}),
    )
    assert _get_spread_meta("any/slug") is None
    assert _get_spread_meta("any/slug", pinned_meta={}) is None


def test_current_meta_used_when_pinned_not_provided(monkeypatch):
    """Backwards-compat: calling without pinned_meta falls back to registry info."""
    monkeypatch.setattr(
        "src.strategies.registry.get_info",
        lambda slug: _FakeInfo({"spread_legs": ["AAA", "BBB"]}),
    )
    result = _get_spread_meta("any/slug")
    assert result is not None
    assert result["spread_legs"] == ["AAA", "BBB"]


def test_pinned_meta_list_length_guard(monkeypatch):
    """Pinned META with only 1 leg is rejected, falls back to registry info."""
    monkeypatch.setattr(
        "src.strategies.registry.get_info",
        lambda slug: _FakeInfo({"spread_legs": ["CURR_R1", "CURR_R2"]}),
    )
    pinned = {"spread_legs": ["JUST_ONE"]}
    result = _get_spread_meta("any/slug", pinned_meta=pinned)
    # Should fall back to current file's valid 2-leg pair.
    assert result is not None
    assert result["spread_legs"] == ["CURR_R1", "CURR_R2"]
