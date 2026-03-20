"""Data models for intra-bar price simulation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass
class OHLCBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class StopLevel:
    price: float
    direction: Literal["below", "above"]
    label: str


@dataclass
class StopTriggerResult:
    triggered: bool
    trigger_price: float | None
    trigger_label: str | None
    sequence_idx: int | None


@dataclass
class EntryFillResult:
    filled: bool
    fill_price: float | None
    fill_bar: Literal["signal_bar_close", "next_bar_open"]
    slippage: float


@dataclass
class BarSimResult:
    stop_result: StopTriggerResult
    entry_result: EntryFillResult | None
    price_sequence: list[float]
    stop_before_entry: bool
