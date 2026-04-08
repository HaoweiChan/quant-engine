"""Streaming Volume Profile with POC / Value Area.

Translated from the TradingView "Multi Timeframe Volume Profiles [TradingIQ]"
Pine Script by KioseffTrading (MPL-2.0).

Algorithm
---------
1. Divide the price range [low, high] into ``rows`` equal bins.
2. For each bar fed in, determine which bins the bar spans (using its
   high/low). Distribute its volume equally across those bins, signed
   by direction (close > open → buy, close < open → sell).
3. After all bars are fed, compute:
   - **POC** (Point of Control): price level of the bin with maximum
     total volume.
   - **Value Area**: expand outward from POC until 70% of total volume
     is captured. VAH = top of value area, VAL = bottom.
   - Per-bin buy/sell/total/delta volumes.

This indicator is session-aware: call ``new_session()`` to reset and
start a fresh profile for a new HTF period.

Usage
-----
::

    vp = VolumeProfile(rows=20)
    vp.new_session(session_high=20500.0, session_low=20200.0)
    for bar in bars:
        vp.add_bar(bar.high, bar.low, bar.close, bar.open, bar.volume)
    result = vp.compute()
    print(result.poc, result.vah, result.val)

For streaming use where the session range expands as new bars arrive,
call ``update_range()`` before ``add_bar()`` to widen the profile range.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProfileBin:
    """One row of the volume profile histogram."""

    level: float       # lower edge of the bin
    buy_vol: float     # volume from up-bars
    sell_vol: float    # volume from down-bars
    total_vol: float   # buy_vol + sell_vol
    delta: float       # signed: +buy - sell


@dataclass(frozen=True)
class ProfileResult:
    """Computed volume profile output."""

    poc: float                     # price level of Point of Control
    poc_index: int                 # bin index of POC
    vah: float                     # Value Area High
    val: float                     # Value Area Low
    va_pct: float                  # actual % of volume captured by VA
    total_volume: float            # sum of all volume
    bins: tuple[ProfileBin, ...]   # per-bin breakdown, low to high
    bin_width: float               # price height of each bin


@dataclass
class _Bar:
    """Lightweight storage for bars fed into the profile."""

    high: float
    low: float
    volume: float
    direction: float  # +1 buy, -1 sell


class VolumeProfile:
    """Streaming volume profile with POC and Value Area.

    Parameters
    ----------
    rows : int
        Number of price bins (5-200). Default 20.
    va_threshold : float
        Fraction of total volume to capture for Value Area. Default 0.7.
    """

    __slots__ = (
        "_rows", "_va_threshold",
        "_session_high", "_session_low",
        "_bars", "_result",
    )

    def __init__(self, rows: int = 20, va_threshold: float = 0.7) -> None:
        if not 5 <= rows <= 500:
            raise ValueError(f"rows must be 5-500, got {rows}")
        if not 0.0 < va_threshold <= 1.0:
            raise ValueError(f"va_threshold must be (0, 1], got {va_threshold}")
        self._rows = rows
        self._va_threshold = va_threshold
        self._session_high: float | None = None
        self._session_low: float | None = None
        self._bars: list[_Bar] = []
        self._result: ProfileResult | None = None

    def new_session(
        self,
        session_high: float | None = None,
        session_low: float | None = None,
    ) -> None:
        """Reset profile for a new session/period.

        If high/low are not known yet (streaming), pass None and call
        ``update_range()`` as new bars arrive before computing.
        """
        self._session_high = session_high
        self._session_low = session_low
        self._bars.clear()
        self._result = None

    def update_range(self, high: float, low: float) -> None:
        """Expand the session range (streaming mode).

        Call before ``add_bar()`` each time a new bar may extend the
        session high/low.
        """
        if self._session_high is None or high > self._session_high:
            self._session_high = high
        if self._session_low is None or low < self._session_low:
            self._session_low = low
        self._result = None  # invalidate cached result

    def add_bar(
        self,
        high: float,
        low: float,
        close: float,
        open_: float,
        volume: float,
    ) -> None:
        """Feed one bar into the profile.

        Direction is inferred from close vs open (matching Pine Script):
        close >= open → buy volume (+1), close < open → sell volume (-1).
        """
        direction = 1.0 if close >= open_ else -1.0
        self._bars.append(_Bar(
            high=high,
            low=low,
            volume=abs(volume),
            direction=direction,
        ))
        self._result = None  # invalidate cached result

    def add_bar_with_direction(
        self,
        high: float,
        low: float,
        volume: float,
        direction: float,
    ) -> None:
        """Feed one bar with explicit direction sign.

        Use when you already know direction from tick data (bid/ask)
        instead of inferring from open/close.
        """
        self._bars.append(_Bar(
            high=high,
            low=low,
            volume=abs(volume),
            direction=math.copysign(1.0, direction) if direction != 0 else 1.0,
        ))
        self._result = None

    def compute(self) -> ProfileResult | None:
        """Compute the volume profile from accumulated bars.

        Returns None if no bars have been added or range is zero.
        Uses cached result if nothing changed since last compute.
        """
        if self._result is not None:
            return self._result

        if not self._bars:
            return None

        h = self._session_high
        lo = self._session_low
        if h is None or lo is None:
            return None
        if h <= lo:
            return None

        rows = self._rows
        bin_width = (h - lo) / rows

        # Build level edges
        levels = [lo + bin_width * i for i in range(rows)]

        # Accumulate volume into bins
        buy_vol = [0.0] * rows
        sell_vol = [0.0] * rows
        delta = [0.0] * rows
        total_vol = [0.0] * rows

        for bar in self._bars:
            # Which bins does this bar span?
            dn_lev = _bin_index(bar.low, lo, bin_width, rows)
            up_lev = _bin_index(bar.high, lo, bin_width, rows)

            # Distribute volume equally across spanned bins
            span = abs(up_lev - dn_lev) + 1
            vol_per_bin = bar.volume / span
            signed_vol = vol_per_bin * bar.direction

            for idx in range(dn_lev, up_lev + 1):
                delta[idx] += signed_vol
                total_vol[idx] += vol_per_bin
                if bar.direction > 0:
                    buy_vol[idx] += vol_per_bin
                else:
                    sell_vol[idx] += vol_per_bin

        # POC: bin with max total volume
        poc_index = 0
        max_vol = total_vol[0]
        for i in range(1, rows):
            if total_vol[i] > max_vol:
                max_vol = total_vol[i]
                poc_index = i

        # Value Area: expand outward from POC until threshold is met
        total = sum(total_vol)
        target = total * self._va_threshold
        idx_up = poc_index
        idx_dn = poc_index
        va_sum = 0.0

        if total > 0:
            # Start with POC bin
            va_sum += total_vol[poc_index]
            idx_up += 1
            idx_dn -= 1

            while va_sum < target:
                vol_up = total_vol[idx_up] if idx_up < rows else 0.0
                vol_dn = total_vol[idx_dn] if idx_dn >= 0 else 0.0

                if vol_up == 0.0 and vol_dn == 0.0:
                    break

                if idx_up < rows:
                    va_sum += vol_up
                    idx_up += 1
                    if va_sum >= target:
                        break

                if idx_dn >= 0:
                    va_sum += vol_dn
                    idx_dn -= 1
                    if va_sum >= target:
                        break

        vah_index = min(idx_up, rows - 1)
        val_index = max(idx_dn, 0)

        bins = tuple(
            ProfileBin(
                level=levels[i],
                buy_vol=buy_vol[i],
                sell_vol=sell_vol[i],
                total_vol=total_vol[i],
                delta=delta[i],
            )
            for i in range(rows)
        )

        self._result = ProfileResult(
            poc=levels[poc_index],
            poc_index=poc_index,
            vah=levels[vah_index],
            val=levels[val_index],
            va_pct=(va_sum / total * 100.0) if total > 0 else 0.0,
            total_volume=total,
            bins=bins,
            bin_width=bin_width,
        )
        return self._result

    @property
    def result(self) -> ProfileResult | None:
        """Last computed result (None if not yet computed)."""
        return self._result

    @property
    def ready(self) -> bool:
        return self._result is not None

    def reset(self) -> None:
        """Clear all state."""
        self._session_high = None
        self._session_low = None
        self._bars.clear()
        self._result = None


def _bin_index(price: float, low: float, bin_width: float, rows: int) -> int:
    """Map a price to the appropriate bin index (clamped to [0, rows-1])."""
    idx = int((price - low) / bin_width)
    return max(0, min(idx, rows - 1))
