"""Tests for compute_disaster_level: long/short level computation, parametrized ATR multiples."""

from __future__ import annotations

import pytest

from src.execution.disaster_stop_monitor import compute_disaster_level


class TestComputeDisasterLevel:
    def test_long_disaster_level_below_entry(self) -> None:
        level = compute_disaster_level(20000.0, "long", 100.0, 4.5)
        assert level == 20000.0 - 4.5 * 100.0
        assert level == 19550.0

    def test_short_disaster_level_above_entry(self) -> None:
        level = compute_disaster_level(20000.0, "short", 100.0, 4.5)
        assert level == 20000.0 + 4.5 * 100.0
        assert level == 20450.0

    @pytest.mark.parametrize("atr_mult", [1.0, 2.0, 3.0, 4.5, 5.0, 10.0])
    def test_parametrized_atr_multiples_long(self, atr_mult: float) -> None:
        entry_price = 20000.0
        daily_atr = 100.0
        level = compute_disaster_level(entry_price, "long", daily_atr, atr_mult)
        assert level == entry_price - atr_mult * daily_atr

    @pytest.mark.parametrize("atr_mult", [1.0, 2.0, 3.0, 4.5, 5.0, 10.0])
    def test_parametrized_atr_multiples_short(self, atr_mult: float) -> None:
        entry_price = 20000.0
        daily_atr = 100.0
        level = compute_disaster_level(entry_price, "short", daily_atr, atr_mult)
        assert level == entry_price + atr_mult * daily_atr
