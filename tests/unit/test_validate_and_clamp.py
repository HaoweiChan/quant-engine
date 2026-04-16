"""Tests for validate_and_clamp function in registry module."""

from __future__ import annotations

from src.strategies.registry import validate_and_clamp


class TestValidateAndClamp:
    def test_clamp_below_min(self) -> None:
        clamped, warnings = validate_and_clamp("pyramid", {"stop_atr_mult": 0.1})
        assert clamped["stop_atr_mult"] == 0.5
        assert any("clamped" in w and "0.1" in w and "0.5" in w for w in warnings)

    def test_clamp_above_max(self) -> None:
        clamped, warnings = validate_and_clamp("pyramid", {"trail_atr_mult": 99.0})
        assert clamped["trail_atr_mult"] == 6.0
        assert any("clamped" in w and "99.0" in w and "6.0" in w for w in warnings)

    def test_int_coercion(self) -> None:
        clamped, warnings = validate_and_clamp("pyramid", {"max_levels": 14.7})
        assert clamped["max_levels"] == 8
        coercion_warnings = [w for w in warnings if "coerced" in w]
        assert len(coercion_warnings) == 1

    def test_float_coercion_from_int(self) -> None:
        clamped, warnings = validate_and_clamp("pyramid", {"stop_atr_mult": 2})
        assert clamped["stop_atr_mult"] == 2.0

    def test_float_coercion_from_string(self) -> None:
        clamped, warnings = validate_and_clamp("pyramid", {"stop_atr_mult": "2.5"})
        assert clamped["stop_atr_mult"] == 2.5

    def test_unknown_param_passthrough(self) -> None:
        clamped, warnings = validate_and_clamp("pyramid", {"unknown_param": 42})
        assert clamped["unknown_param"] == 42
        assert any("unknown_param" in w and "not a known parameter" in w for w in warnings)

    def test_no_warnings_when_valid(self) -> None:
        clamped, warnings = validate_and_clamp(
            "pyramid", {"stop_atr_mult": 1.5, "trail_atr_mult": 3.0}
        )
        assert clamped["stop_atr_mult"] == 1.5
        assert clamped["trail_atr_mult"] == 3.0
        assert warnings == []

    def test_input_dict_not_mutated(self) -> None:
        original: dict[str, object] = {"stop_atr_mult": 0.1}
        validate_and_clamp("pyramid", original)
        assert original["stop_atr_mult"] == 0.1

    def test_empty_params(self) -> None:
        clamped, warnings = validate_and_clamp("pyramid", {})
        assert clamped == {}
        assert warnings == []

    def test_valid_value_unchanged(self) -> None:
        clamped, warnings = validate_and_clamp(
            "pyramid", {"stop_atr_mult": 2.5, "trail_atr_mult": 4.0}
        )
        assert clamped["stop_atr_mult"] == 2.5
        assert clamped["trail_atr_mult"] == 4.0
        assert warnings == []
