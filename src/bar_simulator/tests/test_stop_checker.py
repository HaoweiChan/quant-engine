"""Tests for check_stops_intra_bar."""
from datetime import datetime

from src.bar_simulator.models import OHLCBar, StopLevel
from src.bar_simulator.stop_checker import check_stops_intra_bar

TS = datetime(2024, 1, 1)


def _bar(o: float, h: float, lo: float, c: float) -> OHLCBar:
    return OHLCBar(timestamp=TS, open=o, high=h, low=lo, close=c, volume=100)


def test_long_stop_triggered_correct_fill() -> None:
    bar = _bar(34000, 34200, 33700, 33900)
    stop = StopLevel(price=33800, direction="below", label="initial_stop")
    result = check_stops_intra_bar(bar, [stop], slippage=2)
    assert result.triggered is True
    assert result.trigger_price == 33798  # 33800 - 2
    assert result.trigger_label == "initial_stop"


def test_stop_not_triggered_low_above_stop() -> None:
    bar = _bar(34000, 34200, 33850, 34100)
    stop = StopLevel(price=33800, direction="below", label="initial_stop")
    result = check_stops_intra_bar(bar, [stop], slippage=2)
    assert result.triggered is False


def test_multiple_stops_first_one_wins() -> None:
    bar = _bar(34000, 34200, 33600, 33700)
    stops = [
        StopLevel(price=33800, direction="below", label="trailing_stop"),
        StopLevel(price=33500, direction="below", label="circuit_breaker"),
    ]
    result = check_stops_intra_bar(bar, stops, slippage=2)
    assert result.trigger_label == "trailing_stop"
    assert result.trigger_price == 33798


def test_short_stop_above_direction() -> None:
    bar = _bar(34000, 34300, 33900, 34200)
    stop = StopLevel(price=34250, direction="above", label="short_stop")
    result = check_stops_intra_bar(bar, [stop], slippage=2)
    assert result.triggered is True
    assert result.trigger_price == 34252  # 34250 + 2
    assert result.trigger_label == "short_stop"


def test_empty_stops_list() -> None:
    bar = _bar(34000, 34200, 33700, 33900)
    result = check_stops_intra_bar(bar, [], slippage=2)
    assert result.triggered is False
    assert result.trigger_price is None


def test_stop_at_open_price() -> None:
    bar = _bar(33800, 34000, 33700, 33900)
    stop = StopLevel(price=33800, direction="below", label="exact_stop")
    result = check_stops_intra_bar(bar, [stop], slippage=2)
    assert result.triggered is True
    assert result.sequence_idx == 0  # triggered at open
