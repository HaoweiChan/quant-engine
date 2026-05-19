"""Classify a list of option legs into a named combo structure."""
from __future__ import annotations

from dataclasses import dataclass

from src.analytics.options.scenarios import Leg


@dataclass
class ComboKind:
    name: str
    confidence: float  # 0..1
    notes: str


def classify_combo(legs: list[Leg]) -> ComboKind:
    """Classify N legs into a known options structure.

    Recognized shapes:
    - 1 leg: 'Single'
    - 2 legs same expiry, same type, different strikes → 'Vertical' with Bull/Bear sub-label
    - 2 legs same expiry, opposite types, same strike → 'Long/Short Straddle'
    - 2 legs same expiry, opposite types, different strikes → 'Long/Short Strangle'
    - 2 legs same type, same strike, different expiry → 'Calendar'
    - 4 legs same expiry, balanced calls+puts → 'Iron Condor'
    - 3 legs same expiry, 1L-2S-1L pattern → 'Butterfly'
    - Anything else → 'Custom (N legs)'

    Raises ValueError when len(legs) > 4 or multipliers don't all match.
    """
    if len(legs) > 4:
        raise ValueError(f"Too many legs: {len(legs)}. Maximum supported is 4.")

    multipliers = {leg.multiplier for leg in legs}
    if len(multipliers) > 1:
        raise ValueError(f"All legs must share the same multiplier; got {multipliers}.")

    n = len(legs)

    if n == 1:
        leg = legs[0]
        direction = "Long" if leg.side == "buy" else "Short"
        opt = "Call" if leg.option_type == "C" else "Put"
        return ComboKind(
            name=f"Single ({direction} {opt})",
            confidence=1.0,
            notes="Single-leg position.",
        )

    if n == 2:
        return _classify_two_legs(legs)

    if n == 3:
        return _classify_three_legs(legs)

    # n == 4
    return _classify_four_legs(legs)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _expiry_key(leg: Leg) -> object:
    """Return a hashable expiry key; Leg doesn't carry expiry, use strike as proxy.

    Note: Leg dataclass from scenarios.py has no expiry field. We detect
    Calendar by checking that expiry differs — but since Leg has no expiry
    attribute, Calendar detection relies on callers tagging legs with a custom
    attribute OR we use an augmented Leg. For now we check for an optional
    ``expiry`` attribute via getattr so this works with augmented Legs.
    """
    return getattr(leg, "expiry", None)


def _has_expiry_info(legs: list[Leg]) -> bool:
    return all(getattr(leg, "expiry", None) is not None for leg in legs)


def _classify_two_legs(legs: list[Leg]) -> ComboKind:
    a, b = legs
    a_type, b_type = a.option_type, b.option_type
    a_strike, b_strike = a.strike, b.strike
    a_side, b_side = a.side, b.side

    # Calendar: same type, same strike, different expiry
    if _has_expiry_info(legs):
        a_exp = getattr(a, "expiry", None)
        b_exp = getattr(b, "expiry", None)
        if a_type == b_type and a_strike == b_strike and a_exp != b_exp:
            direction = "Long" if a_side == "buy" else "Short"
            return ComboKind(
                name="Calendar",
                confidence=1.0,
                notes=f"{direction} calendar on {a_type} K={a_strike}.",
            )

    same_type = a_type == b_type
    same_strike = a_strike == b_strike

    if same_type and not same_strike:
        # Vertical spread
        return _classify_vertical(a, b)

    if not same_type and same_strike:
        # Straddle
        if a_side == "buy" and b_side == "buy":
            return ComboKind(
                name="Long Straddle",
                confidence=1.0,
                notes=f"Long call + long put at K={a_strike}.",
            )
        if a_side == "sell" and b_side == "sell":
            return ComboKind(
                name="Short Straddle",
                confidence=1.0,
                notes=f"Short call + short put at K={a_strike}.",
            )
        # Degenerate: mixed sides — fall through to Custom

    if not same_type and not same_strike:
        # Strangle
        if a_side == "buy" and b_side == "buy":
            return ComboKind(
                name="Long Strangle",
                confidence=1.0,
                notes="Long call + long put at different strikes.",
            )
        if a_side == "sell" and b_side == "sell":
            return ComboKind(
                name="Short Strangle",
                confidence=1.0,
                notes="Short call + short put at different strikes.",
            )
        # Mixed sides — fall through to Custom

    # Same type, same strike — degenerate or unrecognised
    return ComboKind(
        name=f"Custom ({len([a, b])} legs)",
        confidence=0.7,
        notes="2-leg structure doesn't match a standard pattern.",
    )


def _classify_vertical(a: Leg, b: Leg) -> ComboKind:
    """Classify a 2-leg same-type spread into Bull/Bear sub-label."""
    # Ensure a has the lower strike
    low, high = (a, b) if a.strike < b.strike else (b, a)
    opt = "Call" if low.option_type == "C" else "Put"

    if opt == "Call":
        if low.side == "buy" and high.side == "sell":
            return ComboKind(
                name="Vertical (Bull Call)",
                confidence=1.0,
                notes=f"Long {low.strike}C / Short {high.strike}C — debit spread.",
            )
        if low.side == "sell" and high.side == "buy":
            return ComboKind(
                name="Vertical (Bear Call)",
                confidence=1.0,
                notes=f"Short {low.strike}C / Long {high.strike}C — credit spread.",
            )
    else:  # Put
        if high.side == "buy" and low.side == "sell":
            return ComboKind(
                name="Vertical (Bear Put)",
                confidence=1.0,
                notes=f"Long {high.strike}P / Short {low.strike}P — debit spread.",
            )
        if high.side == "sell" and low.side == "buy":
            return ComboKind(
                name="Vertical (Bull Put)",
                confidence=1.0,
                notes=f"Short {high.strike}P / Long {low.strike}P — credit spread.",
            )

    # Same type, same direction (both long or both short) — Custom
    return ComboKind(
        name="Custom (2 legs)",
        confidence=0.7,
        notes="Same-type same-direction spread; no standard label.",
    )


def _classify_three_legs(legs: list[Leg]) -> ComboKind:
    """Detect Butterfly (1L-2S-1L at 3 strikes) or fall back to Custom."""
    # All same type required for a standard butterfly
    types = {leg.option_type for leg in legs}
    if len(types) != 1:
        return ComboKind(
            name="Custom (3 legs)",
            confidence=0.7,
            notes="3-leg mixed-type structure; not a standard butterfly.",
        )

    sorted_legs = sorted(legs, key=lambda x: x.strike)
    strikes = [leg.strike for leg in sorted_legs]
    sides = [leg.side for leg in sorted_legs]

    # Butterfly: outer legs long, middle leg short (or vice versa for short butterfly)
    # Pattern 1: buy-sell-buy (long butterfly)
    if sides == ["buy", "sell", "buy"] and len(set(strikes)) == 3:
            return ComboKind(
                name="Butterfly",
                confidence=1.0,
                notes=f"Long butterfly at {strikes[0]}/{strikes[1]}/{strikes[2]}.",
            )
    # Short butterfly: sell-buy-sell
    if sides == ["sell", "buy", "sell"] and len(set(strikes)) == 3:
        return ComboKind(
            name="Butterfly",
            confidence=1.0,
            notes=f"Short butterfly at {strikes[0]}/{strikes[1]}/{strikes[2]}.",
        )

    # Any 3-leg same-type spread at 3 distinct strikes with middle having 2x qty
    # (e.g. 1 long lower, 2 short middle, 1 long upper via qty — but here we check sides)
    # Ambiguous — return butterfly with lower confidence
    if len(set(strikes)) == 3:
        return ComboKind(
            name="Butterfly",
            confidence=0.7,
            notes="3-leg same-type spread at 3 strikes; possible butterfly variant.",
        )

    return ComboKind(
        name="Custom (3 legs)",
        confidence=0.7,
        notes="3-leg structure doesn't match a standard butterfly.",
    )


def _classify_four_legs(legs: list[Leg]) -> ComboKind:
    """Detect Iron Condor (2C + 2P, same expiry, balanced L/S) or fall back to Custom."""
    calls = [leg for leg in legs if leg.option_type == "C"]
    puts = [leg for leg in legs if leg.option_type == "P"]

    if len(calls) != 2 or len(puts) != 2:
        return ComboKind(
            name="Custom (4 legs)",
            confidence=0.7,
            notes="4-leg structure is not 2 calls + 2 puts.",
        )

    # Each pair must have one long and one short
    def _is_balanced(pair: list[Leg]) -> bool:
        return {leg.side for leg in pair} == {"buy", "sell"}

    if not _is_balanced(calls) or not _is_balanced(puts):
        return ComboKind(
            name="Custom (4 legs)",
            confidence=0.7,
            notes="4-leg 2C+2P structure but legs are not balanced long/short per side.",
        )

    # Iron Condor: short inner strikes, long outer strikes
    call_short = next(leg for leg in calls if leg.side == "sell")
    call_long = next(leg for leg in calls if leg.side == "buy")
    put_short = next(leg for leg in puts if leg.side == "sell")
    put_long = next(leg for leg in puts if leg.side == "buy")

    all_strikes = sorted({call_short.strike, call_long.strike, put_short.strike, put_long.strike})
    if len(all_strikes) < 4:
        return ComboKind(
            name="Custom (4 legs)",
            confidence=0.7,
            notes="4-leg 2C+2P structure but strikes are not all distinct.",
        )

    # Standard IC: put_long < put_short < call_short < call_long
    if (
        put_long.strike < put_short.strike
        and put_short.strike < call_short.strike
        and call_short.strike < call_long.strike
    ):
        return ComboKind(
            name="Iron Condor",
            confidence=1.0,
            notes=(
                f"Short {put_short.strike}P/{call_short.strike}C, "
                f"long {put_long.strike}P/{call_long.strike}C — net credit."
            ),
        )

    return ComboKind(
        name="Iron Condor",
        confidence=0.7,
        notes="4-leg 2C+2P balanced structure; strike ordering non-standard.",
    )
