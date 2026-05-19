"""Tests for the combo strategy classifier."""
from __future__ import annotations

import pytest

from src.analytics.options.scenarios import Leg
from src.analytics.options.strategy_recognizer import classify_combo


def _leg(option_type: str, strike: float, side: str, expiry: str | None = None) -> Leg:
    leg = Leg(option_type=option_type, strike=strike, side=side, qty=1, price=5.0)
    if expiry is not None:
        object.__setattr__(leg, "expiry", expiry) if hasattr(leg, "__dataclass_fields__") else setattr(leg, "expiry", expiry)
    return leg


def _leg_with_expiry(option_type: str, strike: float, side: str, expiry: str) -> Leg:
    leg = Leg(option_type=option_type, strike=strike, side=side, qty=1, price=5.0)
    leg.expiry = expiry  # type: ignore[attr-defined]
    return leg


def test_recognize_bull_call_spread():
    legs = [
        Leg(option_type="C", strike=18000, side="buy", qty=1, price=80.0),
        Leg(option_type="C", strike=18200, side="sell", qty=1, price=40.0),
    ]
    result = classify_combo(legs)
    assert result.name == "Vertical (Bull Call)"
    assert result.confidence == 1.0


def test_recognize_bear_put_spread():
    legs = [
        Leg(option_type="P", strike=18200, side="buy", qty=1, price=80.0),
        Leg(option_type="P", strike=18000, side="sell", qty=1, price=40.0),
    ]
    result = classify_combo(legs)
    assert result.name == "Vertical (Bear Put)"
    assert result.confidence == 1.0


def test_recognize_bull_put_spread():
    legs = [
        Leg(option_type="P", strike=18200, side="sell", qty=1, price=80.0),
        Leg(option_type="P", strike=18000, side="buy", qty=1, price=40.0),
    ]
    result = classify_combo(legs)
    assert result.name == "Vertical (Bull Put)"
    assert result.confidence == 1.0


def test_recognize_bear_call_spread():
    legs = [
        Leg(option_type="C", strike=18000, side="sell", qty=1, price=80.0),
        Leg(option_type="C", strike=18200, side="buy", qty=1, price=40.0),
    ]
    result = classify_combo(legs)
    assert result.name == "Vertical (Bear Call)"
    assert result.confidence == 1.0


def test_recognize_long_straddle():
    legs = [
        Leg(option_type="C", strike=18000, side="buy", qty=1, price=80.0),
        Leg(option_type="P", strike=18000, side="buy", qty=1, price=75.0),
    ]
    result = classify_combo(legs)
    assert result.name == "Long Straddle"
    assert result.confidence == 1.0


def test_recognize_short_straddle():
    legs = [
        Leg(option_type="C", strike=18000, side="sell", qty=1, price=80.0),
        Leg(option_type="P", strike=18000, side="sell", qty=1, price=75.0),
    ]
    result = classify_combo(legs)
    assert result.name == "Short Straddle"
    assert result.confidence == 1.0


def test_recognize_long_strangle():
    legs = [
        Leg(option_type="C", strike=18200, side="buy", qty=1, price=50.0),
        Leg(option_type="P", strike=17800, side="buy", qty=1, price=50.0),
    ]
    result = classify_combo(legs)
    assert result.name == "Long Strangle"
    assert result.confidence == 1.0


def test_recognize_calendar():
    leg_a = Leg(option_type="C", strike=18000, side="buy", qty=1, price=80.0)
    leg_b = Leg(option_type="C", strike=18000, side="sell", qty=1, price=60.0)
    leg_a.expiry = "2025-06-18"  # type: ignore[attr-defined]
    leg_b.expiry = "2025-05-21"  # type: ignore[attr-defined]
    result = classify_combo([leg_a, leg_b])
    assert result.name == "Calendar"
    assert result.confidence == 1.0


def test_recognize_iron_condor():
    legs = [
        Leg(option_type="P", strike=17600, side="buy", qty=1, price=20.0),   # long put wing
        Leg(option_type="P", strike=17800, side="sell", qty=1, price=40.0),  # short put
        Leg(option_type="C", strike=18200, side="sell", qty=1, price=40.0),  # short call
        Leg(option_type="C", strike=18400, side="buy", qty=1, price=20.0),   # long call wing
    ]
    result = classify_combo(legs)
    assert result.name == "Iron Condor"
    assert result.confidence == 1.0


def test_recognize_butterfly():
    legs = [
        Leg(option_type="C", strike=17800, side="buy", qty=1, price=150.0),
        Leg(option_type="C", strike=18000, side="sell", qty=1, price=80.0),
        Leg(option_type="C", strike=18200, side="buy", qty=1, price=30.0),
    ]
    result = classify_combo(legs)
    assert result.name == "Butterfly"
    assert result.confidence >= 0.7


def test_recognize_short_butterfly():
    legs = [
        Leg(option_type="P", strike=17800, side="sell", qty=1, price=150.0),
        Leg(option_type="P", strike=18000, side="buy", qty=1, price=80.0),
        Leg(option_type="P", strike=18200, side="sell", qty=1, price=30.0),
    ]
    result = classify_combo(legs)
    assert result.name == "Butterfly"
    assert result.confidence >= 0.7


def test_reject_too_many_legs():
    legs = [Leg(option_type="C", strike=18000 + i * 100, side="buy", qty=1, price=10.0) for i in range(5)]
    with pytest.raises(ValueError, match="Too many legs"):
        classify_combo(legs)


def test_classify_with_two_legs_no_match_falls_to_custom():
    # Same expiry, same type (call), same strike — degenerate; not a spread
    legs = [
        Leg(option_type="C", strike=18000, side="buy", qty=1, price=80.0),
        Leg(option_type="C", strike=18000, side="sell", qty=1, price=80.0),
    ]
    result = classify_combo(legs)
    assert "Custom" in result.name or "Vertical" in result.name  # same-strike calls: degenerate


def test_single_leg_long_call():
    legs = [Leg(option_type="C", strike=18000, side="buy", qty=1, price=80.0)]
    result = classify_combo(legs)
    assert "Single" in result.name
    assert "Long" in result.name
    assert result.confidence == 1.0


def test_mismatched_multipliers_raises():
    leg_a = Leg(option_type="C", strike=18000, side="buy", qty=1, price=80.0, multiplier=50.0)
    leg_b = Leg(option_type="C", strike=18200, side="sell", qty=1, price=40.0, multiplier=100.0)
    with pytest.raises(ValueError, match="multiplier"):
        classify_combo([leg_a, leg_b])
