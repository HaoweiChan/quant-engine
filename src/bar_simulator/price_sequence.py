"""Intra-bar price sequence generation from OHLC data."""
from __future__ import annotations

from typing import Literal

from src.bar_simulator.models import OHLCBar

HighLowOrder = Literal["open_proximity", "always_up", "always_down"]


def _dedup_consecutive(seq: list[float]) -> list[float]:
    if not seq:
        return seq
    result = [seq[0]]
    for v in seq[1:]:
        if v != result[-1]:
            result.append(v)
    return result


def intra_bar_price_sequence(
    bar: OHLCBar,
    high_low_order: HighLowOrder = "open_proximity",
) -> list[float]:
    """Generate the conservative price path a bar visited.

    Rules:
      1. Open is always first.
      2. High/low order determined by open proximity (or override).
      3. Close is always last.
      4. Consecutive duplicates removed.
    """
    if high_low_order == "always_up":
        seq = [bar.open, bar.high, bar.low, bar.close]
    elif high_low_order == "always_down":
        seq = [bar.open, bar.low, bar.high, bar.close]
    else:
        dist_to_high = abs(bar.open - bar.high)
        dist_to_low = abs(bar.open - bar.low)
        if dist_to_high <= dist_to_low:
            seq = [bar.open, bar.high, bar.low, bar.close]
        else:
            seq = [bar.open, bar.low, bar.high, bar.close]
    return _dedup_consecutive(seq)
