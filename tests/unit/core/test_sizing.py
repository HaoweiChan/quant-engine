"""Unit tests for PortfolioSizer and helpers."""
from __future__ import annotations

from src.core.sizing import (
    PortfolioSizer,
    SizingConfig,
    SizingMode,
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


# ---------------------------------------------------------------------------
# Portfolio-level extensions (US-006 + US-007)
# ---------------------------------------------------------------------------

class TestSharedMarginPool:
    """Shared margin pool: PortfolioSizer.set_open_exposure scales orders down
    so the combined book never exceeds equity × portfolio_margin_cap."""

    def test_empty_exposure_preserves_legacy_behavior(self) -> None:
        """Without set_open_exposure, legacy per-strategy margin cap applies unchanged."""
        sizer = PortfolioSizer(SizingConfig(margin_cap=0.5, max_lots=20, min_lots=1))
        result = sizer.size_entry(
            equity=2_000_000,
            stop_distance=50.0,
            point_value=200,
            margin_per_unit=184_000,
            strategy_slug="foo",
        )
        # Risk cap: 2M * 0.02 / (50 * 200) = 4 lots
        assert result.lots == 4.0

    def test_shared_pool_enforces_global_cap(self) -> None:
        """If other strategies have consumed near-all of the portfolio cap,
        new order is scaled down even though per-strategy margin cap allows more."""
        cfg = SizingConfig(
            margin_cap=0.5,
            max_lots=20,
            min_lots=1,
            portfolio_margin_cap=0.65,
        )
        sizer = PortfolioSizer(cfg)
        # Other strategies have used 1.3M of the 1.3M portfolio budget → 0 headroom
        sizer.set_open_exposure({"other": 1_300_000.0})
        result = sizer.size_entry(
            equity=2_000_000,
            stop_distance=10.0,  # very small stop → huge risk-based lots
            point_value=200,
            margin_per_unit=184_000,
            strategy_slug="foo",
        )
        assert result.lots == 0.0
        assert "portfolio_cap_exhausted" in result.caps_applied

    def test_shared_pool_partial_reduction_to_zero(self) -> None:
        """When available is positive but below one contract's margin,
        the cap is 'portfolio_cap' and lots floors to zero."""
        cfg = SizingConfig(
            margin_cap=0.5,
            max_lots=20,
            min_lots=1,
            portfolio_margin_cap=0.65,
        )
        sizer = PortfolioSizer(cfg)
        sizer.set_open_exposure({"other": 1_200_000.0})  # 100k headroom
        result = sizer.size_entry(
            equity=2_000_000,
            stop_distance=10.0,
            point_value=200,
            margin_per_unit=184_000,
            strategy_slug="foo",
        )
        # floor(100k / 184k) = 0 → cap label is partial reduction
        assert result.lots == 0.0
        assert "portfolio_cap" in result.caps_applied

    def test_shared_pool_partial_headroom(self) -> None:
        cfg = SizingConfig(
            margin_cap=0.5,
            max_lots=20,
            min_lots=1,
            portfolio_margin_cap=0.65,
        )
        sizer = PortfolioSizer(cfg)
        sizer.set_open_exposure({"other": 800_000.0})
        result = sizer.size_entry(
            equity=2_000_000,
            stop_distance=10.0,  # big risk-lot count
            point_value=200,
            margin_per_unit=184_000,
            strategy_slug="foo",
        )
        # Available = 2M * 0.65 - 800k = 500k → floor(500k / 184k) = 2
        assert result.lots == 2.0
        assert "portfolio_cap" in result.caps_applied

    def test_shared_pool_excludes_self_exposure(self) -> None:
        """A strategy's own existing exposure should not double-count when
        pricing its next order (the new order replaces the old sizing)."""
        cfg = SizingConfig(
            margin_cap=0.5,
            max_lots=20,
            min_lots=1,
            portfolio_margin_cap=0.65,
        )
        sizer = PortfolioSizer(cfg)
        sizer.set_open_exposure({"foo": 500_000.0, "bar": 100_000.0})
        result = sizer.size_entry(
            equity=2_000_000,
            stop_distance=10.0,
            point_value=200,
            margin_per_unit=184_000,
            strategy_slug="foo",
        )
        # Available excludes "foo" → 2M * 0.65 - 100k = 1.2M
        # floor(1.2M / 184k) = 6 lots. But per-strategy margin cap is
        # 2M * 0.5 / 184k = 5.43 → floor 5. So 5 lots.
        assert result.lots == 5.0

    def test_shared_pool_applies_to_size_add(self) -> None:
        cfg = SizingConfig(
            margin_cap=0.5,
            max_lots=20,
            min_lots=1,
            portfolio_margin_cap=0.65,
        )
        sizer = PortfolioSizer(cfg)
        sizer.set_open_exposure({"other": 1_300_000.0})  # zero headroom
        result = sizer.size_add(
            equity=2_000_000,
            existing_margin_used=0,
            margin_per_unit=184_000,
            requested_lots=5,
            strategy_slug="foo",
        )
        # Even though per-strategy margin_cap allows, shared pool caps to 0
        assert result.lots == 0.0
        assert "portfolio_cap_exhausted" in result.caps_applied


class TestKellyMode:
    """KELLY_PORTFOLIO mode scales risk-based lots by per-strategy weight."""

    def test_kelly_mode_scales_lots(self) -> None:
        cfg = SizingConfig(
            mode=SizingMode.KELLY_PORTFOLIO,
            kelly_weights={"foo": 0.50, "bar": 0.25},
            margin_cap=0.5,
            max_lots=20,
            min_lots=1,
        )
        sizer = PortfolioSizer(cfg)
        result = sizer.size_entry(
            equity=2_000_000,
            stop_distance=50.0,
            point_value=200,
            margin_per_unit=184_000,
            strategy_slug="foo",
        )
        # Base risk lots: 4. Kelly weight 0.5 → 2.0, floor 2.
        assert result.lots == 2.0
        assert result.method == "kelly_portfolio"
        assert "kelly_scaled" in result.caps_applied
        assert result.details["kelly"]["weight"] == 0.5

    def test_kelly_mode_fallback_when_slug_missing(self) -> None:
        cfg = SizingConfig(
            mode=SizingMode.KELLY_PORTFOLIO,
            kelly_weights={"foo": 0.50},
            margin_cap=0.5,
            max_lots=20,
            min_lots=1,
        )
        sizer = PortfolioSizer(cfg)
        result = sizer.size_entry(
            equity=2_000_000,
            stop_distance=50.0,
            point_value=200,
            margin_per_unit=184_000,
            strategy_slug="unknown",  # not in kelly_weights
        )
        # Fallback to risk-based sizing (4 lots unchanged)
        assert result.lots == 4.0
        assert "kelly_fallback" in result.caps_applied

    def test_kelly_mode_zero_weight_returns_zero(self) -> None:
        cfg = SizingConfig(
            mode=SizingMode.KELLY_PORTFOLIO,
            kelly_weights={"foo": 0.0},
            margin_cap=0.5,
            max_lots=20,
            min_lots=1,
        )
        sizer = PortfolioSizer(cfg)
        result = sizer.size_entry(
            equity=2_000_000,
            stop_distance=50.0,
            point_value=200,
            margin_per_unit=184_000,
            strategy_slug="foo",
        )
        assert result.lots == 0.0
        assert "kelly_zero_weight" in result.caps_applied

    def test_risk_stop_mode_ignores_kelly_weights(self) -> None:
        """Even with kelly_weights set, RISK_STOP mode doesn't apply them."""
        cfg = SizingConfig(
            mode=SizingMode.RISK_STOP,
            kelly_weights={"foo": 0.25},  # would be 1 lot under Kelly
            margin_cap=0.5,
            max_lots=20,
            min_lots=1,
        )
        sizer = PortfolioSizer(cfg)
        result = sizer.size_entry(
            equity=2_000_000,
            stop_distance=50.0,
            point_value=200,
            margin_per_unit=184_000,
            strategy_slug="foo",
        )
        # Legacy risk-based 4 lots
        assert result.lots == 4.0
        assert result.method == "risk"

    def test_kelly_plus_shared_pool_stack(self) -> None:
        """Both portfolio-level features stack: Kelly first, then shared pool cap."""
        cfg = SizingConfig(
            mode=SizingMode.KELLY_PORTFOLIO,
            kelly_weights={"foo": 0.75},
            margin_cap=0.5,
            max_lots=20,
            min_lots=1,
            portfolio_margin_cap=0.65,
        )
        sizer = PortfolioSizer(cfg)
        sizer.set_open_exposure({"other": 900_000.0})  # 400k headroom
        result = sizer.size_entry(
            equity=2_000_000,
            stop_distance=10.0,  # 20 raw risk lots
            point_value=200,
            margin_per_unit=184_000,
            strategy_slug="foo",
        )
        # Risk base ≤ margin cap of 2M*0.5/184k = 5. Kelly 0.75 → 3.75.
        # Portfolio headroom 400k / 184k = 2.17 → floor 2.
        # Should be floor(min(3.75, 2.17)) = 2.
        assert result.lots == 2.0
        assert "kelly_scaled" in result.caps_applied
        assert "portfolio_cap" in result.caps_applied


class TestOpenExposureProperty:
    def test_open_exposure_returns_copy(self) -> None:
        sizer = PortfolioSizer()
        sizer.set_open_exposure({"foo": 100.0})
        exposure = sizer.open_exposure
        exposure["foo"] = 999.0
        assert sizer.open_exposure == {"foo": 100.0}  # Not mutated
