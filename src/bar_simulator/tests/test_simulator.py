"""Tests for BarSimulator integration."""
from datetime import datetime

from src.bar_simulator.models import OHLCBar, StopLevel
from src.bar_simulator.simulator import BarSimulator

TS = datetime(2024, 1, 1)
TS2 = datetime(2024, 1, 2)


def _bar(o: float, h: float, lo: float, c: float, ts: datetime = TS) -> OHLCBar:
    return OHLCBar(timestamp=ts, open=o, high=h, low=lo, close=c, volume=100)


def test_stop_only_bar() -> None:
    sim = BarSimulator(slippage_points=2, entry_mode="bar_close")
    bar = _bar(34000, 34200, 33700, 33900)
    stop = StopLevel(price=33800, direction="below", label="stop")
    result = sim.process_bar(bar, next_bar=None, stops=[stop], entry_signal=False)
    assert result.stop_result.triggered is True
    assert result.entry_result is None
    assert result.stop_before_entry is False


def test_entry_only_bar() -> None:
    sim = BarSimulator(slippage_points=2, entry_mode="bar_close")
    bar = _bar(34000, 34200, 33900, 34150)
    result = sim.process_bar(bar, next_bar=None, stops=[], entry_signal=True)
    assert result.stop_result.triggered is False
    assert result.entry_result is not None
    assert result.entry_result.filled is True
    assert result.entry_result.fill_price == 34152


def test_same_bar_stop_and_entry_stop_wins() -> None:
    sim = BarSimulator(slippage_points=2, entry_mode="bar_close")
    bar = _bar(34000, 34050, 33600, 33700)
    stop = StopLevel(price=33800, direction="below", label="stop")
    result = sim.process_bar(bar, next_bar=None, stops=[stop], entry_signal=True)
    assert result.stop_before_entry is True
    assert result.stop_result.triggered is True
    assert result.entry_result is None


def test_no_stops_no_entry() -> None:
    sim = BarSimulator(slippage_points=2, entry_mode="bar_close")
    bar = _bar(34000, 34200, 33900, 34100)
    result = sim.process_bar(bar, next_bar=None, stops=[], entry_signal=False)
    assert result.stop_result.triggered is False
    assert result.entry_result is None
    assert result.stop_before_entry is False


def test_price_sequence_in_result() -> None:
    sim = BarSimulator(slippage_points=2, entry_mode="bar_close")
    bar = _bar(34000, 34050, 33600, 33700)
    result = sim.process_bar(bar, next_bar=None, stops=[], entry_signal=False)
    assert result.price_sequence == [34000, 34050, 33600, 33700]


def test_next_open_entry_mode() -> None:
    sim = BarSimulator(slippage_points=2, entry_mode="next_open")
    bar = _bar(34000, 34200, 33900, 34150)
    next_bar = _bar(34100, 34300, 34000, 34200, ts=TS2)
    result = sim.process_bar(bar, next_bar=next_bar, stops=[], entry_signal=True)
    assert result.entry_result is not None
    assert result.entry_result.filled is True
    assert result.entry_result.fill_price == 34102
    assert result.entry_result.fill_bar == "next_bar_open"
