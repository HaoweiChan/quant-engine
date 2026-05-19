"""Payoff scenario analytics for multi-leg TXO option positions."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np


@dataclass
class Leg:
    option_type: Literal["C", "P"]
    strike: float
    side: Literal["buy", "sell"]
    qty: int
    price: float
    multiplier: float = 50.0


def _intrinsic_vec(option_type: str, strike: float, S_grid: np.ndarray) -> np.ndarray:  # noqa: N803
    if option_type == "C":
        return np.maximum(S_grid - strike, 0.0)
    return np.maximum(strike - S_grid, 0.0)


def payoff_at_expiry(legs: list[Leg], S_grid: np.ndarray) -> np.ndarray:  # noqa: N803
    """Total P&L at expiry for each spot level in S_grid.

    Long legs: (intrinsic - premium) * qty * multiplier
    Short legs: (premium - intrinsic) * qty * multiplier
    """
    result = np.zeros(len(S_grid), dtype=float)
    for leg in legs:
        intrinsic = _intrinsic_vec(leg.option_type, leg.strike, S_grid)
        if leg.side == "buy":
            result += (intrinsic - leg.price) * leg.qty * leg.multiplier
        else:
            result += (leg.price - intrinsic) * leg.qty * leg.multiplier
    return result


def mark_pnl(  # noqa: N803
    legs: list[Leg],
    S_now: float,  # noqa: N803
    T: float,  # noqa: N803
    r: float,
    q: float,
    sigma: float,
) -> float:
    """Unrealized mark-to-market P&L using Black-Scholes theoretical prices.

    Uses BS price instead of intrinsic to estimate current value vs entry cost.
    """
    from src.analytics.options.pricing import bs_price

    total = 0.0
    for leg in legs:
        theo = bs_price(S_now, leg.strike, T, r, q, sigma, leg.option_type)
        if math.isnan(theo):
            if leg.option_type == "C":
                theo = max(S_now - leg.strike, 0.0)
            else:
                theo = max(leg.strike - S_now, 0.0)
        if leg.side == "buy":
            total += (theo - leg.price) * leg.qty * leg.multiplier
        else:
            total += (leg.price - theo) * leg.qty * leg.multiplier
    return total


def compute_scenarios(
    legs: list[Leg],
    S_now: float,  # noqa: N803
    dte_days: int,
    r: float = 0.0175,
    q: float = 0.0,
    sigma: float = 0.20,
    multipliers: tuple[float, ...] = (0.95, 0.98, 1.00, 1.02, 1.05),
) -> dict:
    """Compute payoff analytics for a multi-leg position.

    Args:
        legs: List of option legs defining the position.
        S_now: Current underlying spot price.
        dte_days: Days to expiry.
        r: Risk-free rate (annualized).
        q: Continuous dividend yield.
        sigma: Implied volatility (annualized).
        multipliers: Spot multipliers for pnl_curve grid points.

    Returns:
        Dict with keys: breakeven, max_loss, max_profit, premium,
        margin_estimate, pnl_curve, dte_days.

    Note on margin_estimate: TAIFEX simplified conservative estimate.
    Actual margin requirements are broker-driven and may differ significantly.
    Sell legs use: max(min_margin, premium_received + 10% * S * multiplier).
    Buy legs have zero margin (premium already paid).
    """
    lo = S_now * 0.70
    hi = S_now * 1.30
    s_grid = np.linspace(lo, hi, 50_000)  # noqa: N806

    pnl = payoff_at_expiry(legs, s_grid)

    # Breakeven: up to 2 sign-change crossings
    sign_changes = np.where(np.diff(np.sign(pnl)))[0]
    breakevens: list[float] = []
    for idx in sign_changes:
        if pnl[idx] == 0.0:
            breakevens.append(float(s_grid[idx]))
        elif pnl[idx + 1] == 0.0:
            breakevens.append(float(s_grid[idx + 1]))
        else:
            # Linear interpolation between the two boundary points
            s0, s1 = s_grid[idx], s_grid[idx + 1]
            p0, p1 = pnl[idx], pnl[idx + 1]
            be = s0 - p0 * (s1 - s0) / (p1 - p0)
            breakevens.append(float(be))
        if len(breakevens) == 2:
            break

    max_loss = float(np.min(pnl))

    # Detect effectively unbounded upside: if rightmost value is at grid max
    # and still rising, treat as inf (e.g. naked long call dominant position).
    raw_max = float(np.max(pnl))
    rightmost = float(pnl[-1])
    slope_ratio = abs(rightmost - float(pnl[-100])) / (abs(rightmost) + 1e-8)
    if rightmost == raw_max and rightmost > 0 and slope_ratio > 0.01:
        max_profit = float("inf")
    else:
        max_profit = raw_max

    # Net premium: positive = net received, negative = net paid
    premium = 0.0
    for leg in legs:
        sign = 1.0 if leg.side == "sell" else -1.0
        premium += sign * leg.price * leg.qty * leg.multiplier

    # TAIFEX simplified margin estimate (conservative placeholder).
    # Actual margin is broker/clearing-house driven; this is indicative only.
    # Sell legs: max(min_margin, premium_received + 10% * spot * multiplier).
    # Buy legs: zero margin (premium paid at entry).
    margin_estimate = 0.0
    min_margin_per_contract = 5000.0
    for leg in legs:
        if leg.side == "sell":
            min_margin = min_margin_per_contract * leg.qty * leg.multiplier / 50.0
            premium_margin = (
                leg.price * leg.qty * leg.multiplier
                + 0.1 * S_now * leg.multiplier * leg.qty
            )
            margin_estimate += max(min_margin, premium_margin)

    # PnL curve at each multiplier point
    pnl_curve: list[dict] = []
    for mult in multipliers:
        s_pt = S_now * mult
        pts = payoff_at_expiry(legs, np.array([s_pt]))
        pnl_curve.append({"S": float(s_pt), "pnl": float(pts[0])})

    return {
        "breakeven": breakevens,
        "max_loss": max_loss,
        "max_profit": max_profit,
        "premium": premium,
        "margin_estimate": margin_estimate,
        "pnl_curve": pnl_curve,
        "dte_days": dte_days,
    }
