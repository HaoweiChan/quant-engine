"""Tests for intra_bar_price_sequence."""
from datetime import datetime

from src.bar_simulator.models import OHLCBar
from src.bar_simulator.price_sequence import intra_bar_price_sequence

TS = datetime(2024, 1, 1)


def _bar(o: float, h: float, lo: float, c: float) -> OHLCBar:
    return OHLCBar(timestamp=TS, open=o, high=h, low=lo, close=c, volume=100)


def test_open_near_high_up_first() -> None:
    bar = _bar(34000, 34050, 33600, 33700)
    assert intra_bar_price_sequence(bar) == [34000, 34050, 33600, 33700]


def test_open_near_low_down_first() -> None:
    bar = _bar(34000, 34500, 33950, 34200)
    assert intra_bar_price_sequence(bar) == [34000, 33950, 34500, 34200]


def test_equidistant_default_up_first() -> None:
    bar = _bar(34000, 34200, 33800, 34000)
    assert intra_bar_price_sequence(bar) == [34000, 34200, 33800, 34000]


def test_doji_bar_single_element() -> None:
    bar = _bar(34000, 34000, 34000, 34000)
    assert intra_bar_price_sequence(bar) == [34000]


def test_always_up_override() -> None:
    bar = _bar(34000, 34500, 33950, 34200)
    assert intra_bar_price_sequence(bar, "always_up") == [34000, 34500, 33950, 34200]


def test_always_down_override() -> None:
    bar = _bar(34000, 34050, 33600, 33700)
    assert intra_bar_price_sequence(bar, "always_down") == [34000, 33600, 34050, 33700]


def test_open_equals_high_dedup() -> None:
    bar = _bar(34200, 34200, 33800, 34000)
    # open == high → dedup: [34200, 33800, 34000]
    assert intra_bar_price_sequence(bar) == [34200, 33800, 34000]


def test_open_equals_close_no_dedup_when_separated() -> None:
    bar = _bar(34000, 34200, 33800, 34000)
    # open=34000, high=34200, low=33800, close=34000 — no consecutive dups
    assert intra_bar_price_sequence(bar) == [34000, 34200, 33800, 34000]
