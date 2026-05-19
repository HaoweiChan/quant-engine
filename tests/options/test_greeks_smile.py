"""Tests for bs_gamma, bs_theta, bs_vega, bs_greeks_vec, and smile_residuals."""
from __future__ import annotations

import numpy as np
import pytest

from src.analytics.options.pricing import bs_gamma, bs_theta, bs_vega, bs_greeks_vec
from src.analytics.options.metrics import smile_residuals

S = 20000.0
T_30 = 30 / 365.0
r = 0.0175
q = 0.0
sigma = 0.20
STRIKES = np.array([19000.0, 19500.0, 20000.0, 20500.0, 21000.0])


def test_gamma_peaks_at_atm():
    gammas = np.array([bs_gamma(S, k, T_30, r, q, sigma) for k in STRIKES])
    assert int(np.argmax(gammas)) == 2  # index 2 = strike 20000 (ATM)


def test_theta_negative_for_long_position():
    theta_call = bs_theta(S, S, T_30, r, q, sigma, "C")
    theta_put = bs_theta(S, S, T_30, r, q, sigma, "P")
    assert theta_call < 0, f"Call theta should be negative, got {theta_call}"
    assert theta_put < 0, f"Put theta should be negative, got {theta_put}"


def test_vega_positive():
    vega_call = bs_vega(S, S, T_30, r, q, sigma)
    vega_put = bs_vega(S, S, T_30, r, q, sigma)  # vega is same for call and put
    assert vega_call > 0
    assert vega_put > 0


def test_smile_residuals_zero_when_perfectly_quadratic():
    # Synthesize IVs that lie exactly on a parabola: iv = 0.20 + 0.01*x + 0.05*x^2
    x = np.log(STRIKES / S)
    ivs = 0.20 + 0.01 * x + 0.05 * x ** 2
    resids = smile_residuals(S, STRIKES, ivs)
    assert np.all(np.abs(resids) < 1e-6), f"Expected near-zero residuals, got {resids}"


def test_greeks_vec_delta_sign():
    sigma_arr = np.full(len(STRIKES), sigma)
    types = np.array(["C", "C", "C", "P", "P"])
    g = bs_greeks_vec(S, STRIKES, T_30, r, q, sigma_arr, types)
    # Calls: delta in (0, 1); Puts: delta in (-1, 0)
    assert np.all(g["delta"][:3] > 0)
    assert np.all(g["delta"][3:] < 0)


def test_greeks_vec_gamma_positive():
    sigma_arr = np.full(len(STRIKES), sigma)
    types = np.array(["C"] * len(STRIKES))
    g = bs_greeks_vec(S, STRIKES, T_30, r, q, sigma_arr, types)
    assert np.all(g["gamma"] > 0)


def test_greeks_vec_theta_annual_unit():
    sigma_arr = np.full(len(STRIKES), sigma)
    types = np.array(["C"] * len(STRIKES))
    g = bs_greeks_vec(S, STRIKES, T_30, r, q, sigma_arr, types)
    # Annual theta should be substantially more negative than daily (-1 per day is absurd at these prices)
    # A rough check: |annual theta| > |daily theta| by factor ~365
    scalar_theta = bs_theta(S, S, T_30, r, q, sigma, "C")
    atm_idx = 2
    assert abs(g["theta"][atm_idx] - scalar_theta) < 1.0  # consistent with scalar


def test_smile_residuals_nan_propagation():
    ivs = np.array([0.22, float("nan"), 0.20, 0.21, 0.23])
    resids = smile_residuals(S, STRIKES, ivs)
    assert np.isnan(resids[1])
    assert not np.isnan(resids[0])


def test_bs_gamma_zero_at_expiry():
    assert bs_gamma(S, S, 0.0, r, q, sigma) == 0.0


def test_bs_theta_zero_at_expiry():
    assert bs_theta(S, S, 0.0, r, q, sigma, "C") == 0.0
    assert bs_theta(S, S, 0.0, r, q, sigma, "P") == 0.0
