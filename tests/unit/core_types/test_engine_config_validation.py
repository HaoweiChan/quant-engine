"""Tests for EngineConfig validation: disaster_atr_mult > stop_atr_mult."""

from __future__ import annotations

import pytest

from src.core.types import EngineConfig, PyramidConfig
from src.core.position_engine import create_pyramid_engine


class TestEngineConfigValidation:
    def test_disaster_atr_mult_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="disaster_atr_mult must be positive"):
            EngineConfig(max_loss=50000.0, disaster_atr_mult=-1.0)

    def test_disaster_atr_mult_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="disaster_atr_mult must be positive"):
            EngineConfig(max_loss=50000.0, disaster_atr_mult=0.0)

    def test_valid_disaster_atr_mult(self) -> None:
        config = EngineConfig(max_loss=50000.0, disaster_atr_mult=4.5)
        assert config.disaster_atr_mult == 4.5

    def test_disaster_stop_enabled_defaults_false(self) -> None:
        config = EngineConfig(max_loss=50000.0)
        assert config.disaster_stop_enabled is False

    def test_create_pyramid_engine_with_disaster_stop_validates(self) -> None:
        pyramid_config = PyramidConfig(max_loss=50000.0, stop_atr_mult=1.5)
        config = EngineConfig(
            max_loss=pyramid_config.max_loss,
            disaster_atr_mult=4.5,
            disaster_stop_enabled=True,
        )
        engine = create_pyramid_engine(pyramid_config)
        assert engine._config.disaster_atr_mult == 4.5

    def test_create_pyramid_engine_disaster_atr_mult_equal_no_raise_when_disabled(self) -> None:
        pyramid_config = PyramidConfig(max_loss=50000.0, stop_atr_mult=4.5)
        engine = create_pyramid_engine(pyramid_config)
        assert engine._config.disaster_atr_mult == 4.5
        assert engine._config.disaster_stop_enabled is False

    def test_pyramid_config_max_equity_risk_pct_validation(self) -> None:
        with pytest.raises(ValueError, match="max_equity_risk_pct"):
            PyramidConfig(max_loss=50000.0, max_equity_risk_pct=0.0)

    def test_pyramid_config_risk_symmetry_defaults(self) -> None:
        config = PyramidConfig(max_loss=50000.0)
        assert config.max_equity_risk_pct == 0.02
        assert config.long_only_compat_mode is False
