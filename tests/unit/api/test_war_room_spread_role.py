"""Unit tests for the spread_role tagging emitted by /api/war-room.

Spread strategies in the seeder produce 2 fills per trade_signal (one per
leg). The frontend's SpreadPanels filters signals per panel using the
backend-emitted `spread_role` so each leg's marker lands on its own chart
without symbol-equality heuristics.
"""
from __future__ import annotations

from src.api.routes.war_room import _spread_role_for_fill, _spread_legs_for_slug


def test_spread_role_for_known_spread_strategy() -> None:
    slug = "short_term/mean_reversion/spread_reversion"
    legs = _spread_legs_for_slug(slug)
    assert legs is not None and len(legs) == 2

    # Direct META match: leg1 → "r1", leg2 → "r2".
    assert _spread_role_for_fill(slug, legs[0]) == "r1"
    assert _spread_role_for_fill(slug, legs[1]) == "r2"


def test_spread_role_for_account_relative_legs() -> None:
    """Seeder uses account-override legs (e.g. MTX/MTX_R2) instead of META
    defaults (TX/TX_R2). The role helper must still tag fills correctly.
    """
    slug = "short_term/mean_reversion/spread_reversion"
    # Override-style symbols: MTX is leg1 (no _R2 suffix); MTX_R2 is leg2.
    assert _spread_role_for_fill(slug, "MTX") == "r1"
    assert _spread_role_for_fill(slug, "MTX_R2") == "r2"


def test_spread_role_for_single_leg_strategy() -> None:
    """Non-spread strategies should always tag as "single" so the spread
    chart filter excludes them entirely (their price scale doesn't match
    the synthetic spread axis).
    """
    slug = "short_term/trend_following/night_session_long"
    assert _spread_legs_for_slug(slug) is None
    assert _spread_role_for_fill(slug, "MTX") == "single"
    assert _spread_role_for_fill(slug, "TX") == "single"


def test_spread_role_for_unknown_strategy_returns_single() -> None:
    """Unknown slugs must not crash the war-room aggregation; they degrade
    gracefully to 'single' so any account fills still render somewhere.
    """
    assert _spread_role_for_fill("nonexistent/strategy", "MTX") == "single"
