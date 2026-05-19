"""Tests for scenarios.py and portfolio.py analytics."""
from __future__ import annotations

from src.analytics.options.portfolio import aggregate_greeks
from src.analytics.options.scenarios import Leg, compute_scenarios

# ---------------------------------------------------------------------------
# scenarios.py tests
# ---------------------------------------------------------------------------

def test_long_call_breakeven():
    """1 long call at K=20000, premium=200, mult=50 → breakeven ≈ 20200."""
    legs = [Leg(option_type="C", strike=20000, side="buy", qty=1, price=200, multiplier=50.0)]
    result = compute_scenarios(legs, S_now=20000, dte_days=10)
    bes = result["breakeven"]
    assert len(bes) == 1, f"Expected 1 breakeven, got {bes}"
    # Grid step for ±30% around 20000 over 50k points ≈ 0.24 pts; allow 1 step tolerance
    grid_step = 20000 * 0.60 / 50_000
    assert abs(bes[0] - 20200) <= grid_step + 1, f"Breakeven {bes[0]} not near 20200"


def test_put_credit_spread_max_loss():
    """Sell K=19500 put @100, buy K=19000 put @50, qty=1, mult=50.

    Width=500, credit=50 per index point → net credit = 50*50 = 2500 NTD.
    Max loss = -(500 - 50) * 50 = -22500 NTD.
    """
    legs = [
        Leg(option_type="P", strike=19500, side="sell", qty=1, price=100, multiplier=50.0),
        Leg(option_type="P", strike=19000, side="buy",  qty=1, price=50,  multiplier=50.0),
    ]
    result = compute_scenarios(legs, S_now=20000, dte_days=10)
    expected_max_loss = -(500 - 50) * 50  # -22500
    # Allow ±100 NTD tolerance from grid discretization
    assert abs(result["max_loss"] - expected_max_loss) <= 100, (
        f"max_loss {result['max_loss']} not close to {expected_max_loss}"
    )


def test_premium_sign():
    """Short put → net premium > 0 (received); long call → net premium < 0 (paid)."""
    short_put = [Leg(option_type="P", strike=19000, side="sell", qty=1, price=100, multiplier=50.0)]
    long_call = [Leg(option_type="C", strike=20000, side="buy",  qty=1, price=150, multiplier=50.0)]

    r_short = compute_scenarios(short_put, S_now=19500, dte_days=5)
    r_long  = compute_scenarios(long_call, S_now=19500, dte_days=5)

    assert r_short["premium"] > 0, "Short put should have positive (received) premium"
    assert r_long["premium"] < 0,  "Long call should have negative (paid) premium"


# ---------------------------------------------------------------------------
# portfolio.py tests
# ---------------------------------------------------------------------------

_CHAIN_PAYLOAD = [
    {
        "contract_code": "TXO20000C202506",
        "strike": 20000.0,
        "option_type": "C",
        "delta": 0.50,
        "gamma": 0.002,
        "theta": -5.0,
        "vega": 10.0,
        "iv": 0.20,
    },
    {
        "contract_code": "TXO19500P202506",
        "strike": 19500.0,
        "option_type": "P",
        "delta": -0.40,
        "gamma": 0.0015,
        "theta": -4.0,
        "vega": 8.0,
        "iv": 0.22,
    },
]


def test_portfolio_greeks_aggregates_correctly():
    """Long 1 call + short 1 put → greeks signed and summed correctly."""
    positions = [
        {
            "contract_code": "TXO20000C202506",
            "strike": 20000.0,
            "option_type": "C",
            "expiry": "2025-06-20",
            "side": "Buy",
            "quantity": 1,
            "avg_price": 200.0,
        },
        {
            "contract_code": "TXO19500P202506",
            "strike": 19500.0,
            "option_type": "P",
            "expiry": "2025-06-20",
            "side": "Sell",
            "quantity": 1,
            "avg_price": 100.0,
        },
    ]
    result = aggregate_greeks(positions, _CHAIN_PAYLOAD)

    # Long call: sign=+1, qty=1, mult=50 → delta contribution = +1 * 1 * 50 * 0.50 = +25.0
    # Short put: sign=-1, qty=1, mult=50 → delta contribution = -1 * 1 * 50 * (-0.40) = +20.0
    expected_delta = 1 * 1 * 50 * 0.50 + (-1) * 1 * 50 * (-0.40)
    assert abs(result["net_delta"] - expected_delta) < 1e-9, (
        f"net_delta {result['net_delta']} != {expected_delta}"
    )

    # Long call gamma: +1 * 1 * 50 * 0.002 = 0.10
    # Short put gamma: -1 * 1 * 50 * 0.0015 = -0.075
    expected_gamma = 1 * 1 * 50 * 0.002 + (-1) * 1 * 50 * 0.0015
    assert abs(result["net_gamma"] - expected_gamma) < 1e-9, (
        f"net_gamma {result['net_gamma']} != {expected_gamma}"
    )

    assert result["n_legs"] == 2
    assert result["missing_codes"] == []


def test_portfolio_greeks_handles_missing_codes():
    """Position whose contract_code is NOT in chain_payload appears in missing_codes."""
    positions = [
        {
            "contract_code": "TXO99999C202599",
            "strike": 99999.0,
            "option_type": "C",
            "expiry": "2025-12-31",
            "side": "Buy",
            "quantity": 2,
            "avg_price": 50.0,
        },
    ]
    result = aggregate_greeks(positions, _CHAIN_PAYLOAD)

    assert "TXO99999C202599" in result["missing_codes"]
    assert result["net_delta"] == 0.0
    assert result["net_gamma"] == 0.0
    assert result["n_legs"] == 1
