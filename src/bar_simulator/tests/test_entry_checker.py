"""Tests for check_entry_intra_bar."""
from datetime import datetime

import pytest

from src.bar_simulator.entry_checker import check_entry_intra_bar
from src.bar_simulator.models import OHLCBar

TS = datetime(2024, 1, 1)
TS2 = datetime(2024, 1, 2)


def _bar(o: float, h: float, lo: float, c: float, ts: datetime = TS) -> OHLCBar:
    return OHLCBar(timestamp=ts, open=o, high=h, low=lo, close=c, volume=100)


def test_bar_close_market_entry_long() -> None:
    bar = _bar(34000, 34200, 33900, 34150)
    result = check_entry_intra_bar(bar, entry_mode="bar_close", slippage=2)
    assert result.filled is True
    assert result.fill_price == 34152  # close + slippage
    assert result.fill_bar == "signal_bar_close"


def test_bar_close_market_entry_short() -> None:
    bar = _bar(34000, 34200, 33900, 34150)
    result = check_entry_intra_bar(bar, entry_mode="bar_close", slippage=2, direction="short")
    assert result.filled is True
    assert result.fill_price == 34148  # close - slippage


def test_next_open_market_entry() -> None:
    bar = _bar(34000, 34200, 33900, 34150)
    next_bar = _bar(34100, 34300, 34000, 34200, ts=TS2)
    result = check_entry_intra_bar(bar, entry_mode="next_open", slippage=2, next_bar=next_bar)
    assert result.filled is True
    assert result.fill_price == 34102  # next_bar.open + slippage
    assert result.fill_bar == "next_bar_open"


def test_next_open_raises_without_next_bar() -> None:
    bar = _bar(34000, 34200, 33900, 34150)
    with pytest.raises(ValueError, match="next_bar is required"):
        check_entry_intra_bar(bar, entry_mode="next_open", slippage=2, next_bar=None)


def test_bar_close_limit_fill() -> None:
    bar = _bar(34000, 34200, 33900, 34150)
    result = check_entry_intra_bar(bar, entry_mode="bar_close", slippage=2, limit_price=34000)
    assert result.filled is True
    assert result.fill_price == 34000


def test_bar_close_limit_miss() -> None:
    bar = _bar(34000, 34200, 33900, 34150)
    result = check_entry_intra_bar(bar, entry_mode="bar_close", slippage=2, limit_price=33800)
    assert result.filled is False
    assert result.fill_price is None


def test_next_open_limit_fill() -> None:
    bar = _bar(34000, 34200, 33900, 34150)
    next_bar = _bar(34100, 34300, 33950, 34200, ts=TS2)
    result = check_entry_intra_bar(
        bar, entry_mode="next_open", slippage=2, next_bar=next_bar, limit_price=34000,
    )
    assert result.filled is True
    assert result.fill_price == 34000


def test_next_open_limit_miss() -> None:
    bar = _bar(34000, 34200, 33900, 34150)
    next_bar = _bar(34100, 34300, 34050, 34200, ts=TS2)
    result = check_entry_intra_bar(
        bar, entry_mode="next_open", slippage=2, next_bar=next_bar, limit_price=34000,
    )
    assert result.filled is False
