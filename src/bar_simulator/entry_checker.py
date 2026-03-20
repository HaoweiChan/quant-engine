"""Entry fill checking with look-ahead bias prevention."""
from __future__ import annotations

from typing import Literal

from src.bar_simulator.models import EntryFillResult, OHLCBar
from src.bar_simulator.price_sequence import HighLowOrder, intra_bar_price_sequence


def check_entry_intra_bar(
    signal_bar: OHLCBar,
    entry_mode: Literal["bar_close", "next_open"] = "bar_close",
    slippage: float = 2.0,
    next_bar: OHLCBar | None = None,
    limit_price: float | None = None,
    direction: Literal["long", "short"] = "long",
    high_low_order: HighLowOrder = "open_proximity",
) -> EntryFillResult:
    """Compute entry fill with look-ahead prevention.

    bar_close: fill at signal_bar.close ± slippage
    next_open: fill at next_bar.open ± slippage (raises ValueError if no next_bar)
    """
    slip_sign = 1.0 if direction == "long" else -1.0

    if entry_mode == "bar_close":
        return _bar_close_entry(signal_bar, slippage, slip_sign, limit_price, direction)
    return _next_open_entry(
        signal_bar, next_bar, slippage, slip_sign, limit_price, direction, high_low_order,
    )


def _bar_close_entry(
    signal_bar: OHLCBar,
    slippage: float,
    slip_sign: float,
    limit_price: float | None,
    direction: Literal["long", "short"],
) -> EntryFillResult:
    if limit_price is not None:
        if direction == "long":
            filled = signal_bar.low <= limit_price
        else:
            filled = signal_bar.high >= limit_price
        return EntryFillResult(
            filled=filled,
            fill_price=limit_price if filled else None,
            fill_bar="signal_bar_close",
            slippage=0.0 if filled else slippage,
        )
    return EntryFillResult(
        filled=True,
        fill_price=signal_bar.close + slip_sign * slippage,
        fill_bar="signal_bar_close",
        slippage=slippage,
    )


def _next_open_entry(
    signal_bar: OHLCBar,
    next_bar: OHLCBar | None,
    slippage: float,
    slip_sign: float,
    limit_price: float | None,
    direction: Literal["long", "short"],
    high_low_order: HighLowOrder,
) -> EntryFillResult:
    if next_bar is None:
        msg = "next_bar is required for entry_mode='next_open' but was None"
        raise ValueError(msg)
    if limit_price is not None:
        sequence = intra_bar_price_sequence(next_bar, high_low_order)
        if direction == "long":
            filled = any(p <= limit_price for p in sequence)
        else:
            filled = any(p >= limit_price for p in sequence)
        return EntryFillResult(
            filled=filled,
            fill_price=limit_price if filled else None,
            fill_bar="next_bar_open",
            slippage=0.0 if filled else slippage,
        )
    return EntryFillResult(
        filled=True,
        fill_price=next_bar.open + slip_sign * slippage,
        fill_bar="next_bar_open",
        slippage=slippage,
    )
