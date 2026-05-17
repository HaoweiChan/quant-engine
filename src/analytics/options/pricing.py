"""Black-Scholes pricing and Newton-Raphson implied volatility solver.

References:
- Hull, J.C., *Options, Futures, and Other Derivatives*, Ch. 13-15
- Forward price: F = S * exp((r - q) * T)
- d1 = (ln(F/K) + 0.5 * sigma^2 * T) / (sigma * sqrt(T))
- d2 = d1 - sigma * sqrt(T)
"""
from __future__ import annotations

import math

import numpy as np
from scipy.stats import norm


def bs_price(
    S: float,
    K: float,
    T: float,
    r: float,
    q: float,
    sigma: float,
    option_type: str = "C",
) -> float:
    """Black-Scholes price for a European option.

    Args:
        S: Spot (underlying) price.
        K: Strike price.
        T: Time to expiry in years.
        r: Risk-free rate (annualized).
        q: Continuous dividend yield.
        sigma: Volatility (annualized).
        option_type: "C" for call, "P" for put.
    """
    if T <= 0 or sigma <= 0:
        intrinsic = max(S - K, 0.0) if option_type == "C" else max(K - S, 0.0)
        return intrinsic
    F = S * math.exp((r - q) * T)
    sqrt_T = math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sigma ** 2 * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    discount = math.exp(-r * T)
    if option_type == "C":
        return discount * (F * norm.cdf(d1) - K * norm.cdf(d2))
    return discount * (K * norm.cdf(-d2) - F * norm.cdf(-d1))


def bs_vega(S: float, K: float, T: float, r: float, q: float, sigma: float) -> float:
    """BS vega: dPrice/dSigma."""
    if T <= 0 or sigma <= 0:
        return 0.0
    F = S * math.exp((r - q) * T)
    sqrt_T = math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sigma ** 2 * T) / (sigma * sqrt_T)
    return S * math.exp(-q * T) * norm.pdf(d1) * sqrt_T


def bs_delta(
    S: float,
    K: float,
    T: float,
    r: float,
    q: float,
    sigma: float,
    option_type: str = "C",
) -> float:
    """BS delta for a European option."""
    if T <= 0 or sigma <= 0:
        if option_type == "C":
            return 1.0 if S > K else 0.0
        return -1.0 if S < K else 0.0
    F = S * math.exp((r - q) * T)
    sqrt_T = math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sigma ** 2 * T) / (sigma * sqrt_T)
    if option_type == "C":
        return math.exp(-q * T) * norm.cdf(d1)
    return math.exp(-q * T) * (norm.cdf(d1) - 1.0)


def implied_vol(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    q: float,
    option_type: str = "C",
    max_iter: int = 50,
    tol: float = 1e-5,
) -> float:
    """Newton-Raphson implied volatility solver with Brent fallback.

    Returns NaN if solver fails to converge or vega is too small.
    """
    if market_price <= 0 or T <= 0:
        return float("nan")

    # Newton-Raphson
    sigma = 0.3  # initial guess
    for _ in range(max_iter):
        price = bs_price(S, K, T, r, q, sigma, option_type)
        vega = bs_vega(S, K, T, r, q, sigma)
        if vega < 1e-8:
            break
        diff = price - market_price
        if abs(diff) < tol:
            return sigma
        sigma -= diff / vega
        if sigma <= 0.001:
            sigma = 0.001
        if sigma > 5.0:
            break

    # Brent fallback
    return _brent_iv(market_price, S, K, T, r, q, option_type, tol)


def _brent_iv(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    q: float,
    option_type: str,
    tol: float,
) -> float:
    """Brent's method fallback for IV when Newton diverges."""
    lo, hi = 0.001, 5.0
    f_lo = bs_price(S, K, T, r, q, lo, option_type) - market_price
    f_hi = bs_price(S, K, T, r, q, hi, option_type) - market_price
    if f_lo * f_hi > 0:
        return float("nan")
    for _ in range(100):
        mid = (lo + hi) / 2.0
        f_mid = bs_price(S, K, T, r, q, mid, option_type) - market_price
        if abs(f_mid) < tol:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
            f_hi = f_mid
        else:
            lo = mid
            f_lo = f_mid
    return (lo + hi) / 2.0


def bs_price_vec(
    S: float,
    K: np.ndarray,
    T: float,
    r: float,
    q: float,
    sigma: np.ndarray,
    option_type: np.ndarray,
) -> np.ndarray:
    """Vectorized BS price over arrays of strikes and sigmas."""
    F = S * np.exp((r - q) * T)
    sqrt_T = np.sqrt(T) if T > 0 else 0.0
    if sqrt_T == 0:
        intrinsic_c = np.maximum(S - K, 0.0)
        intrinsic_p = np.maximum(K - S, 0.0)
        is_call = np.char.equal(option_type, "C")
        return np.where(is_call, intrinsic_c, intrinsic_p)
    d1 = (np.log(F / K) + 0.5 * sigma ** 2 * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    discount = np.exp(-r * T)
    is_call = np.char.equal(option_type, "C")
    call_price = discount * (F * norm.cdf(d1) - K * norm.cdf(d2))
    put_price = discount * (K * norm.cdf(-d2) - F * norm.cdf(-d1))
    return np.where(is_call, call_price, put_price)


def implied_vol_vec(
    prices: np.ndarray,
    S: float,
    K: np.ndarray,
    T: float,
    r: float,
    q: float,
    option_types: np.ndarray,
    max_iter: int = 50,
    tol: float = 1e-5,
) -> np.ndarray:
    """Vectorized IV solver — calls scalar implied_vol per element."""
    result = np.empty(len(prices))
    for i in range(len(prices)):
        result[i] = implied_vol(
            float(prices[i]), S, float(K[i]), T, r, q,
            str(option_types[i]), max_iter, tol,
        )
    return result
