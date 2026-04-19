"""Tests for SpreadBarsResult dataclass + _build_spread_bars return shape.

Covers the Step 1 acceptance criteria from .omc/plans/backtest-spread-panels.md:
- Dataclass has all 5 fields
- spread_bars / r1_aligned / r2_aligned have equal length
- Same timestamp at each index across the three lists
- Offset >= 0 and consistent with formula when no override
- Error is None on success, populated on missing/non-overlapping input
"""
from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from src.mcp_server.facade import SpreadBarsResult, _build_spread_bars


def _bar(ts: datetime, close: float, open_: float | None = None) -> SimpleNamespace:
    o = close if open_ is None else open_
    return SimpleNamespace(
        timestamp=ts,
        open=o,
        high=max(o, close),
        low=min(o, close),
        close=close,
        volume=1.0,
    )


class _StubDB:
    """Stub DB whose behavior is set by monkeypatching _load_bars_for_tf."""


def _install_loader(monkeypatch, per_symbol: dict[str, list]):
    """Patch facade._load_bars_for_tf to return per-symbol bars."""
    from src.mcp_server import facade

    def fake_loader(db, symbol, start, end, bar_agg=1):
        return list(per_symbol.get(symbol, []))

    monkeypatch.setattr(facade, "_load_bars_for_tf", fake_loader)


def test_dataclass_has_five_fields():
    names = {f.name for f in fields(SpreadBarsResult)}
    assert names == {"spread_bars", "r1_aligned", "r2_aligned", "offset", "error"}


def test_happy_path_aligned_equal_length(monkeypatch):
    t0 = datetime(2026, 1, 2, 10, 0, 0)
    r1 = [_bar(t0 + timedelta(minutes=i), 1000.0 + i) for i in range(5)]
    r2 = [_bar(t0 + timedelta(minutes=i), 990.0 + i * 0.5) for i in range(5)]
    _install_loader(monkeypatch, {"R1": r1, "R2": r2})

    result = _build_spread_bars(_StubDB(), "R1", "R2", t0, t0 + timedelta(hours=1))

    assert isinstance(result, SpreadBarsResult)
    assert result.error is None
    assert len(result.spread_bars) == len(result.r1_aligned) == len(result.r2_aligned) == 5


def test_same_timestamp_per_index(monkeypatch):
    t0 = datetime(2026, 1, 2, 10, 0, 0)
    r1 = [_bar(t0 + timedelta(minutes=i), 1000.0 + i) for i in range(5)]
    r2 = [_bar(t0 + timedelta(minutes=i), 990.0 + i * 0.5) for i in range(5)]
    _install_loader(monkeypatch, {"R1": r1, "R2": r2})

    result = _build_spread_bars(_StubDB(), "R1", "R2", t0, t0 + timedelta(hours=1))

    for sb, a, b in zip(result.spread_bars, result.r1_aligned, result.r2_aligned, strict=True):
        assert sb.timestamp == a.timestamp == b.timestamp


def test_offset_is_non_negative_without_override(monkeypatch):
    t0 = datetime(2026, 1, 2, 10, 0, 0)
    # Arrange so min(r1.close - r2.close) < 0 to force the formula to shift up
    r1 = [_bar(t0 + timedelta(minutes=i), 100.0) for i in range(3)]
    r2 = [_bar(t0 + timedelta(minutes=i), 200.0 + i) for i in range(3)]
    _install_loader(monkeypatch, {"R1": r1, "R2": r2})

    result = _build_spread_bars(_StubDB(), "R1", "R2", t0, t0 + timedelta(hours=1))

    raw_closes = [a.close - b.close for a, b in zip(r1, r2, strict=True)]
    expected = max(-min(raw_closes) + 100.0, 0.0)
    assert result.offset == pytest.approx(expected)
    assert result.offset >= 0.0


def test_offset_override_is_respected(monkeypatch):
    t0 = datetime(2026, 1, 2, 10, 0, 0)
    r1 = [_bar(t0 + timedelta(minutes=i), 100.0 + i) for i in range(3)]
    r2 = [_bar(t0 + timedelta(minutes=i), 95.0 + i) for i in range(3)]
    _install_loader(monkeypatch, {"R1": r1, "R2": r2})

    result = _build_spread_bars(
        _StubDB(), "R1", "R2", t0, t0 + timedelta(hours=1), offset_override=77.0,
    )

    assert result.offset == 77.0
    assert result.error is None


def test_missing_leg_returns_error(monkeypatch):
    t0 = datetime(2026, 1, 2, 10, 0, 0)
    _install_loader(monkeypatch, {"R1": [_bar(t0, 100.0)], "R2": []})

    result = _build_spread_bars(_StubDB(), "R1", "R2", t0, t0 + timedelta(hours=1))

    assert result.error is not None
    assert "R2" in result.error
    assert result.spread_bars == []
    assert result.r1_aligned == []
    assert result.r2_aligned == []
    assert result.offset == 0.0


def test_no_overlap_returns_error(monkeypatch):
    t0 = datetime(2026, 1, 2, 10, 0, 0)
    r1 = [_bar(t0, 100.0)]
    r2 = [_bar(t0 + timedelta(minutes=5), 95.0)]
    _install_loader(monkeypatch, {"R1": r1, "R2": r2})

    result = _build_spread_bars(_StubDB(), "R1", "R2", t0, t0 + timedelta(hours=1))

    assert result.error is not None
    assert "No overlapping" in result.error
    assert result.spread_bars == []
