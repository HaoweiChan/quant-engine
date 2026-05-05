"""Realized volatility estimators for the underlying.

Estimators:
- Close-to-close (CC): std(log returns) * sqrt(252)
- Parkinson (HL):  sqrt(1/(4*n*ln2) * sum(ln(H/L)^2)) * sqrt(252)
"""
from __future__ import annotations

import math

import numpy as np


def rv_close_to_close(closes: np.ndarray, window: int = 30) -> float:
    """Close-to-close realized volatility over trailing window days.

    Returns annualized volatility.
    """
    if len(closes) < window + 1:
        return float("nan")
    tail = closes[-(window + 1):]
    log_returns = np.diff(np.log(tail))
    return float(np.std(log_returns, ddof=1) * math.sqrt(252))


def rv_parkinson(highs: np.ndarray, lows: np.ndarray, window: int = 30) -> float:
    """Parkinson (high-low) realized volatility.

    More efficient estimator than close-to-close; uses intraday range.
    Assumes zero drift and no overnight jumps.
    """
    if len(highs) < window or len(lows) < window:
        return float("nan")
    h = highs[-window:]
    l = lows[-window:]
    if np.any(l <= 0):
        return float("nan")
    log_hl_sq = np.log(h / l) ** 2
    return float(math.sqrt(np.mean(log_hl_sq) / (4 * math.log(2))) * math.sqrt(252))


def rv_series(
    closes: np.ndarray,
    highs: np.ndarray | None = None,
    lows: np.ndarray | None = None,
    window: int = 30,
    estimator: str = "parkinson",
) -> np.ndarray:
    """Rolling realized vol series over the full array.

    Returns an array of the same length as closes, with NaN for the
    first `window` elements where there isn't enough data.
    """
    n = len(closes)
    result = np.full(n, float("nan"))
    for i in range(window, n):
        if estimator == "parkinson" and highs is not None and lows is not None:
            result[i] = rv_parkinson(highs[:i + 1], lows[:i + 1], window)
        else:
            result[i] = rv_close_to_close(closes[:i + 1], window)
    return result
