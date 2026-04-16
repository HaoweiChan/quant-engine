"""Unit tests for PortfolioSizer and helpers."""
from __future__ import annotations

from src.core.sizing import (
    PortfolioSizer,
    SizingConfig,
    _base_position_lots,
)


class _FakePos:
    def __init__(self, lots: float) -> None:
        self.lots = lots


class TestBasePositionLots:
    def test_empty_returns_zero(self) -> None:
        assert _base_position_lots([]) == 0.0

    def test_first_position_is_base(self) -> None:
        positions = [_FakePos(5.0), _FakePos(7.0)]
        assert _base_position_lots(positions) == 5.0

    def test_ignores_later_positions(self) -> None:
        """After an overlay add, positions[-1] is overlay — must not use that."""
        positions = [_FakePos(3.0), _FakePos(999.0)]
        assert _base_position_lots(positions) == 3.0


class TestSizeAddAbsolute:
    def test_size_add_absolute_path_unchanged(self) -> None:
        """Without multiplier flag, requested_lots is an absolute count."""
        sizer = PortfolioSizer(SizingConfig(margin_cap=0.5, max_lots=20, min_lots=1))
        result = sizer.size_add(
            equity=2_000_000,
            existing_margin_used=0,
            margin_per_unit=184_000,
            requested_lots=3,
        )
        assert result.details["is_multiplier"] is False
        assert result.details["resolved_requested"] == 3
        assert result.lots == 3.0


class TestSizeAddMultiplier:
    def test_size_add_multiplier_path(self) -> None:
        """Multiplier ratio 1.5 * base_lots 5 = 7.5; margin caps to 5."""
        sizer = PortfolioSizer(SizingConfig(margin_cap=0.5, max_lots=20, min_lots=1))
        result = sizer.size_add(
            equity=2_000_000,
            existing_margin_used=0,
            margin_per_unit=184_000,
            requested_lots=1.5,
            base_lots=5,
            is_multiplier=True,
        )
        assert result.details["resolved_requested"] == 7.5
        assert result.details["is_multiplier"] is True
        assert result.details["base_lots"] == 5
        # equity * margin_cap / margin_per_unit = 1_000_000 / 184_000 ~= 5.43 → floor 5
        assert result.lots == 5.0
        assert "margin_headroom" in result.caps_applied

    def test_multiplier_with_base_zero_returns_zero(self) -> None:
        """If base_lots is 0, multiplier yields 0 resolved and below_min cap."""
        sizer = PortfolioSizer(SizingConfig(min_lots=1))
        result = sizer.size_add(
            equity=2_000_000,
            existing_margin_used=0,
            margin_per_unit=184_000,
            requested_lots=1.5,
            base_lots=0,
            is_multiplier=True,
        )
        # With is_multiplier + base=0, the function does NOT multiply
        # (base_lots > 0 guard false), so resolved_requested stays at 1.5
        # and gets floored to 1.
        assert result.details["resolved_requested"] == 1.5
        assert result.lots == 1.0

    def test_multiplier_under_one_floors_to_zero(self) -> None:
        """ratio * base below min_lots → lots=0 with below_min cap."""
        sizer = PortfolioSizer(SizingConfig(min_lots=1))
        result = sizer.size_add(
            equity=2_000_000,
            existing_margin_used=0,
            margin_per_unit=184_000,
            requested_lots=0.1,
            base_lots=2,
            is_multiplier=True,
        )
        # 0.1 * 2 = 0.2, floor=0 → below min
        assert result.lots == 0
        assert "below_min" in result.caps_applied


class TestSizeAddMarginCap:
    def test_no_margin_returns_zero(self) -> None:
        sizer = PortfolioSizer()
        result = sizer.size_add(
            equity=100_000,
            existing_margin_used=100_000,  # 100% used already
            margin_per_unit=184_000,
            requested_lots=1,
        )
        assert result.lots == 0
        assert "no_margin" in result.caps_applied
