"""BarSimulator: unified interface for intra-bar price simulation."""
from __future__ import annotations

from typing import Literal

from src.bar_simulator.entry_checker import check_entry_intra_bar
from src.bar_simulator.models import BarSimResult, OHLCBar, StopLevel
from src.bar_simulator.price_sequence import HighLowOrder, intra_bar_price_sequence
from src.bar_simulator.stop_checker import check_stops_intra_bar


class BarSimulator:
    """Wraps intra_bar_price_sequence and stop/entry checking
    into a single interface consumed by BacktestRunner."""

    def __init__(
        self,
        slippage_points: float = 2.0,
        entry_mode: Literal["bar_close", "next_open"] = "bar_close",
        high_low_order: HighLowOrder = "open_proximity",
    ) -> None:
        self._slippage = slippage_points
        self._entry_mode = entry_mode
        self._high_low_order = high_low_order

    def process_bar(
        self,
        bar: OHLCBar,
        next_bar: OHLCBar | None,
        stops: list[StopLevel],
        entry_signal: bool,
        limit_price: float | None = None,
    ) -> BarSimResult:
        sequence = intra_bar_price_sequence(bar, self._high_low_order)
        stop_result = check_stops_intra_bar(bar, stops, self._slippage, self._high_low_order)

        # If stop triggered and entry signal on same bar, stop wins
        if stop_result.triggered and entry_signal:
            return BarSimResult(
                stop_result=stop_result,
                entry_result=None,
                price_sequence=sequence,
                stop_before_entry=True,
            )

        entry_result = None
        if entry_signal:
            entry_result = check_entry_intra_bar(
                signal_bar=bar,
                entry_mode=self._entry_mode,
                slippage=self._slippage,
                next_bar=next_bar,
                limit_price=limit_price,
                high_low_order=self._high_low_order,
            )

        return BarSimResult(
            stop_result=stop_result,
            entry_result=entry_result,
            price_sequence=sequence,
            stop_before_entry=False,
        )
