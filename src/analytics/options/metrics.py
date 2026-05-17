"""IV Rank, IV Percentile, Variance Risk Premium, and 25-delta skew.

All functions operate on arrays/scalars and are stateless — no DB access.
"""
from __future__ import annotations

import math

import numpy as np

from src.analytics.options.pricing import bs_delta, implied_vol


def iv_rank(current_iv: float, iv_history: np.ndarray) -> float:
    """IV Rank: (current - min) / (max - min) over trailing window.

    Returns value in [0, 1] or NaN if range is zero.
    """
    if len(iv_history) == 0 or np.all(np.isnan(iv_history)):
        return float("nan")
    clean = iv_history[~np.isnan(iv_history)]
    if len(clean) == 0:
        return float("nan")
    lo, hi = float(np.min(clean)), float(np.max(clean))
    if hi - lo < 1e-10:
        return 0.5
    return float((current_iv - lo) / (hi - lo))


def iv_percentile(current_iv: float, iv_history: np.ndarray) -> float:
    """IV Percentile: fraction of historical days where IV < current.

    Returns value in [0, 1].
    """
    if len(iv_history) == 0:
        return float("nan")
    clean = iv_history[~np.isnan(iv_history)]
    if len(clean) == 0:
        return float("nan")
    return float(np.mean(clean < current_iv))


def variance_risk_premium(iv: float, rv: float) -> float:
    """VRP = IV - RV.

    Positive VRP means options are "expensive" relative to realized vol.
    VRP should be zero in a risk-neutral world with no risk premium.
    """
    if math.isnan(iv) or math.isnan(rv):
        return float("nan")
    return iv - rv


def find_25_delta_strike(
    S: float,
    T: float,
    r: float,
    q: float,
    strikes: np.ndarray,
    ivs: np.ndarray,
    option_type: str = "C",
    target_delta: float = 0.25,
) -> float:
    """Find the strike closest to target delta magnitude.

    For calls: find strike where |delta| ~ target_delta.
    For puts: find strike where |delta| ~ target_delta.
    """
    best_strike = float("nan")
    best_diff = float("inf")
    for k, iv in zip(strikes, ivs):
        if math.isnan(iv) or iv <= 0:
            continue
        d = bs_delta(S, float(k), T, r, q, iv, option_type)
        diff = abs(abs(d) - target_delta)
        if diff < best_diff:
            best_diff = diff
            best_strike = float(k)
    return best_strike


def skew_25_delta(
    S: float,
    T: float,
    r: float,
    q: float,
    put_strikes: np.ndarray,
    put_ivs: np.ndarray,
    call_strikes: np.ndarray,
    call_ivs: np.ndarray,
) -> float:
    """25-delta skew: IV(25d put) - IV(25d call).

    Positive skew = downside protection is expensive (demand for puts).
    """
    k_put = find_25_delta_strike(S, T, r, q, put_strikes, put_ivs, "P", 0.25)
    k_call = find_25_delta_strike(S, T, r, q, call_strikes, call_ivs, "C", 0.25)
    if math.isnan(k_put) or math.isnan(k_call):
        return float("nan")

    # Get the IV at those strikes
    iv_put = float("nan")
    for k, iv in zip(put_strikes, put_ivs):
        if float(k) == k_put:
            iv_put = float(iv)
            break
    iv_call = float("nan")
    for k, iv in zip(call_strikes, call_ivs):
        if float(k) == k_call:
            iv_call = float(iv)
            break

    if math.isnan(iv_put) or math.isnan(iv_call):
        return float("nan")
    return iv_put - iv_call


def check_smile_sanity(
    strikes: np.ndarray,
    ivs: np.ndarray,
    atm_strike: float,
) -> dict:
    """Check whether the volatility smile has a normal U-shape.

    Returns dict with keys: valid (bool), inverted (bool), details (str).
    Normal smile: ATM IV <= both wing IVs.
    Inverted: ATM IV > both wing IVs.
    """
    if len(strikes) < 3 or len(ivs) < 3:
        return {"valid": False, "inverted": False, "details": "Not enough strikes"}
    # Find ATM index
    atm_idx = int(np.argmin(np.abs(strikes - atm_strike)))
    atm_vol = ivs[atm_idx]
    # Wings: leftmost and rightmost
    left_vol = ivs[0]
    right_vol = ivs[-1]
    inverted = atm_vol > left_vol and atm_vol > right_vol
    valid = not inverted
    return {"valid": valid, "inverted": inverted, "details": f"ATM={atm_vol:.4f} L={left_vol:.4f} R={right_vol:.4f}"}


def atm_iv(
    S: float,
    T: float,
    r: float,
    q: float,
    strikes: np.ndarray,
    market_prices: np.ndarray,
    option_types: np.ndarray,
) -> float:
    """ATM implied volatility: IV of the strike closest to spot."""
    if len(strikes) == 0:
        return float("nan")
    idx = int(np.argmin(np.abs(strikes - S)))
    price = float(market_prices[idx])
    return implied_vol(price, S, float(strikes[idx]), T, r, q, str(option_types[idx]))
