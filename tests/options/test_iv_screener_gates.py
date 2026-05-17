"""Phase 0 — Acceptance gate tests for the TXO IV Screener.

These 6 gates define what "correct" means. They must all pass before
the screener can be considered ready for production use.

References:
- G1, G5: Hull, Options Futures and Other Derivatives, Ch. 13-15
- G2, G3: Standard IV metrics definitions
- G4: Volatility smile properties (Hull Ch. 20)
- G6: No look-ahead bias — temporal integrity
"""
from __future__ import annotations

import math

import numpy as np
import pytest


class TestG1_BSRoundTrip:
    """G1 — BS round-trip: price a 30D ATM call with sigma=0.20, recover IV via Newton."""

    def test_atm_call_round_trip(self):
        from src.analytics.options.pricing import bs_price, implied_vol
        S, K, T, r, q, sigma = 20000.0, 20000.0, 30 / 365.0, 0.0175, 0.0, 0.20
        price = bs_price(S, K, T, r, q, sigma, option_type="C")
        assert price > 0, "BS price must be positive"
        recovered = implied_vol(price, S, K, T, r, q, option_type="C")
        assert abs(recovered - sigma) < 1e-4, f"Round-trip failed: {sigma} vs {recovered}"

    def test_atm_put_round_trip(self):
        from src.analytics.options.pricing import bs_price, implied_vol
        S, K, T, r, q, sigma = 20000.0, 20000.0, 30 / 365.0, 0.0175, 0.0, 0.20
        price = bs_price(S, K, T, r, q, sigma, option_type="P")
        assert price > 0
        recovered = implied_vol(price, S, K, T, r, q, option_type="P")
        assert abs(recovered - sigma) < 1e-4

    def test_deep_otm_call_round_trip(self):
        from src.analytics.options.pricing import bs_price, implied_vol
        S, K, T, r, q, sigma = 20000.0, 22000.0, 60 / 365.0, 0.0175, 0.0, 0.25
        price = bs_price(S, K, T, r, q, sigma, option_type="C")
        if price < 0.5:
            pytest.skip("Price too small for reliable IV recovery")
        recovered = implied_vol(price, S, K, T, r, q, option_type="C")
        assert abs(recovered - sigma) < 1e-4


class TestG2_ParameterZeroVRP:
    """G2 — VRP must be zero when RV == IV."""

    def test_vrp_zero_when_rv_equals_iv(self):
        from src.analytics.options.metrics import variance_risk_premium
        vrp = variance_risk_premium(0.20, 0.20)
        assert abs(vrp) < 1e-10, f"VRP must be zero when RV == IV, got {vrp}"

    def test_vrp_positive_when_iv_gt_rv(self):
        from src.analytics.options.metrics import variance_risk_premium
        vrp = variance_risk_premium(0.25, 0.18)
        assert vrp > 0, "VRP should be positive when IV > RV"

    def test_vrp_negative_when_iv_lt_rv(self):
        from src.analytics.options.metrics import variance_risk_premium
        vrp = variance_risk_premium(0.15, 0.22)
        assert vrp < 0, "VRP should be negative when IV < RV"


class TestG3_IVRankMonotonicity:
    """G3 — IV Rank monotonicity: strictly increasing IV → rank = 1.0."""

    def test_monotonic_iv_rank(self):
        from src.analytics.options.metrics import iv_rank
        iv_history = np.linspace(0.10, 0.30, 252)
        current = 0.30
        rank = iv_rank(current, iv_history)
        assert abs(rank - 1.0) < 1e-6, f"Rank of max should be 1.0, got {rank}"

    def test_flat_iv_rank(self):
        from src.analytics.options.metrics import iv_rank
        iv_history = np.full(252, 0.20)
        rank = iv_rank(0.20, iv_history)
        assert rank == 0.5, f"Flat series rank should be 0.5, got {rank}"

    def test_iv_rank_minimum(self):
        from src.analytics.options.metrics import iv_rank
        iv_history = np.linspace(0.10, 0.30, 252)
        rank = iv_rank(0.10, iv_history)
        assert abs(rank) < 1e-6, f"Rank of min should be 0.0, got {rank}"


class TestG4_SmileSanity:
    """G4 — Smile sanity: ATM IV <= both wing IVs (or flag inverted)."""

    def test_normal_smile(self):
        from src.analytics.options.metrics import check_smile_sanity
        strikes = np.array([18000, 19000, 20000, 21000, 22000], dtype=float)
        ivs = np.array([0.25, 0.21, 0.18, 0.20, 0.24])
        result = check_smile_sanity(strikes, ivs, 20000.0)
        assert result["valid"], "Normal smile should be valid"
        assert not result["inverted"]

    def test_inverted_smile(self):
        from src.analytics.options.metrics import check_smile_sanity
        strikes = np.array([18000, 19000, 20000, 21000, 22000], dtype=float)
        ivs = np.array([0.15, 0.17, 0.22, 0.19, 0.14])
        result = check_smile_sanity(strikes, ivs, 20000.0)
        assert result["inverted"], "Inverted smile should be flagged"


class TestG5_PutCallParity:
    """G5 — Put-call parity: C - P - (F - K)*e^(-rT) < 0.5% of underlying."""

    def test_parity_holds(self):
        from src.analytics.options.pricing import bs_price
        S, K, T, r, q, sigma = 20000.0, 20000.0, 30 / 365.0, 0.0175, 0.0, 0.20
        call = bs_price(S, K, T, r, q, sigma, option_type="C")
        put = bs_price(S, K, T, r, q, sigma, option_type="P")
        F = S * math.exp((r - q) * T)
        parity_error = abs(call - put - (F - K) * math.exp(-r * T))
        assert parity_error < 0.005 * S, f"Parity violated: {parity_error:.2f}"

    def test_parity_otm(self):
        from src.analytics.options.pricing import bs_price
        S, K, T, r, q, sigma = 20000.0, 21000.0, 60 / 365.0, 0.0175, 0.0, 0.22
        call = bs_price(S, K, T, r, q, sigma, option_type="C")
        put = bs_price(S, K, T, r, q, sigma, option_type="P")
        F = S * math.exp((r - q) * T)
        parity_error = abs(call - put - (F - K) * math.exp(-r * T))
        assert parity_error < 0.005 * S


class TestG6_NoLookAheadIVRank:
    """G6 — No look-ahead in IV Rank: day-N rank from [0..N-1] only."""

    def test_temporal_integrity(self):
        from src.analytics.options.metrics import iv_rank
        rng = np.random.default_rng(42)
        full_series = 0.15 + 0.10 * rng.random(500)

        for day_n in [260, 350, 450]:
            window = full_series[day_n - 252:day_n]
            current = full_series[day_n]
            computed = iv_rank(current, window)
            lo, hi = window.min(), window.max()
            rng_val = hi - lo
            if rng_val < 1e-10:
                assert computed == 0.5
            else:
                expected = (current - lo) / rng_val
                assert abs(computed - expected) < 1e-6, (
                    f"Day {day_n}: rank={computed}, expected={expected}"
                )

    def test_iv_percentile_no_future_leak(self):
        from src.analytics.options.metrics import iv_percentile
        rng = np.random.default_rng(123)
        series = 0.15 + 0.10 * rng.random(300)
        # Percentile at day 200 should only use data up to day 199
        window = series[:200]
        current = series[200]
        pctile = iv_percentile(current, window)
        expected = np.mean(window < current)
        assert abs(pctile - expected) < 1e-6
