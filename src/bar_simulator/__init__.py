"""Bar-level price simulation (模擬逐筆洗價) for OHLC backtesting."""
from src.bar_simulator.entry_checker import check_entry_intra_bar
from src.bar_simulator.models import (
    BarSimResult,
    EntryFillResult,
    OHLCBar,
    StopLevel,
    StopTriggerResult,
)
from src.bar_simulator.price_sequence import intra_bar_price_sequence
from src.bar_simulator.simulator import BarSimulator
from src.bar_simulator.stop_checker import check_stops_intra_bar

__all__ = [
    "BarSimResult",
    "BarSimulator",
    "EntryFillResult",
    "OHLCBar",
    "StopLevel",
    "StopTriggerResult",
    "check_entry_intra_bar",
    "check_stops_intra_bar",
    "intra_bar_price_sequence",
]
