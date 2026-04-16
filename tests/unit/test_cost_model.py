"""Unit tests for InstrumentCostConfig and MCP facade cost injection."""

from __future__ import annotations

import pytest

from src.core.types import (
    INSTRUMENT_COSTS,
    get_instrument_cost_config,
)


class TestInstrumentCostConfig:
    def test_tx_defaults(self) -> None:
        cfg = INSTRUMENT_COSTS["TX"]
        assert cfg.slippage_pct == 0.1
        assert cfg.commission_per_contract == 100.0
        assert cfg.symbol == "TX"

    def test_mtx_defaults(self) -> None:
        cfg = INSTRUMENT_COSTS["MTX"]
        assert cfg.slippage_pct == 0.1
        assert cfg.commission_per_contract == 40.0
        assert cfg.symbol == "MTX"

    def test_slippage_bps_conversion(self) -> None:
        cfg = INSTRUMENT_COSTS["TX"]
        assert cfg.slippage_bps == pytest.approx(1.0)  # 0.1% -> 1.0 bps

    def test_commission_bps_is_zero(self) -> None:
        cfg = INSTRUMENT_COSTS["TX"]
        assert cfg.commission_bps == 0.0

    def test_frozen(self) -> None:
        cfg = INSTRUMENT_COSTS["TX"]
        with pytest.raises(AttributeError):
            cfg.slippage_pct = 0.5  # type: ignore[misc]


class TestGetInstrumentCostConfig:
    def test_known_symbol(self) -> None:
        cfg = get_instrument_cost_config("TX")
        assert cfg.symbol == "TX"

    def test_unknown_symbol_falls_back_to_tx(self) -> None:
        cfg = get_instrument_cost_config("UNKNOWN_SYMBOL")
        assert cfg.symbol == "TX"
        assert cfg.commission_per_contract == 100.0

    def test_mtx_lookup(self) -> None:
        cfg = get_instrument_cost_config("MTX")
        assert cfg.commission_per_contract == 40.0
