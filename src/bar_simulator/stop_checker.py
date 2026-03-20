"""Stop condition checking against an intra-bar price sequence."""
from __future__ import annotations

from src.bar_simulator.models import OHLCBar, StopLevel, StopTriggerResult
from src.bar_simulator.price_sequence import HighLowOrder, intra_bar_price_sequence


def _stop_triggered(price: float, stop: StopLevel) -> bool:
    if stop.direction == "below":
        return price <= stop.price
    return price >= stop.price


def _fill_price(stop: StopLevel, slippage: float) -> float:
    if stop.direction == "below":
        return stop.price - slippage
    return stop.price + slippage


def check_stops_intra_bar(
    bar: OHLCBar,
    stops: list[StopLevel],
    slippage: float = 2.0,
    high_low_order: HighLowOrder = "open_proximity",
) -> StopTriggerResult:
    """Walk the intra-bar price path and return the first triggered stop."""
    no_trigger = StopTriggerResult(
        triggered=False, trigger_price=None, trigger_label=None, sequence_idx=None,
    )
    if not stops:
        return no_trigger
    sequence = intra_bar_price_sequence(bar, high_low_order)
    for idx, price in enumerate(sequence):
        for stop in stops:
            if _stop_triggered(price, stop):
                return StopTriggerResult(
                    triggered=True,
                    trigger_price=_fill_price(stop, slippage),
                    trigger_label=stop.label,
                    sequence_idx=idx,
                )
    return no_trigger
