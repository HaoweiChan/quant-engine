"""Drawdown circuit breaker with Faber TAA-style hysteresis.

Implements a state machine that trips when cumulative drawdown from peak
exceeds a threshold *and* price is below a trend filter (e.g. SMA), then
re-activates only after drawdown recovers to a lower re-entry threshold or
price crosses back above the trend filter.  The two-condition trip and
single-condition re-entry create hysteresis that prevents rapid oscillation
around the breaker boundary.

Reference: Mebane Faber, "A Quantitative Approach to Tactical Asset
Allocation" (2007) — monthly SMA-filter as a risk-off switch.
"""
from __future__ import annotations

PARAM_SPEC: dict[str, dict] = {
    "breaker_pct": {
        "type": "float",
        "default": 0.15,
        "min": 0.03,
        "max": 0.25,
        "description": (
            "Drawdown % at which circuit breaker trips "
            "(requires price below SMA)."
        ),
    },
    "reentry_pct": {
        "type": "float",
        "default": 0.05,
        "min": 0.01,
        "max": 0.15,
        "description": "Drawdown % threshold for circuit breaker reset.",
    },
}


class DDCircuitBreaker:
    """Faber TAA-style drawdown circuit breaker with hysteresis.

    State machine:
      ACTIVE  -> TRIPPED when dd >= breaker_pct AND price < SMA
      TRIPPED -> ACTIVE  when dd <= reentry_pct  OR  price >= SMA

    Parameters
    ----------
    breaker_pct : float
        Drawdown fraction (0–1) that triggers the breaker when price is
        also below the SMA.  Default 0.15 (15 %).
    reentry_pct : float
        Drawdown fraction at or below which the breaker resets.  Must be
        strictly less than ``breaker_pct``.  Default 0.05 (5 %).

    Raises
    ------
    ValueError
        If ``reentry_pct`` >= ``breaker_pct``.
    """

    __slots__ = (
        "_breaker_pct",
        "_reentry_pct",
        "_peak_price",
        "_current_dd",
        "_tripped",
    )

    def __init__(
        self,
        breaker_pct: float = 0.15,
        reentry_pct: float = 0.05,
    ) -> None:
        if reentry_pct >= breaker_pct:
            raise ValueError(
                f"reentry_pct ({reentry_pct}) must be < breaker_pct ({breaker_pct})"
            )
        self._breaker_pct = breaker_pct
        self._reentry_pct = reentry_pct
        self._peak_price: float = 0.0
        self._current_dd: float = 0.0
        self._tripped: bool = False

    def update(self, price: float, below_sma: bool) -> None:
        """Feed one price observation and update circuit-breaker state.

        Parameters
        ----------
        price : float
            Current price used to track the high-water mark and compute
            drawdown.
        below_sma : bool
            True when the current price is below the trend-filter SMA.
        """
        if price > self._peak_price:
            self._peak_price = price
        self._current_dd = (
            1.0 - price / self._peak_price if self._peak_price > 0 else 0.0
        )

        if not self._tripped:
            if (
                self._breaker_pct > 0
                and self._current_dd >= self._breaker_pct
                and below_sma
            ):
                self._tripped = True
        else:
            if self._current_dd <= self._reentry_pct or not below_sma:
                self._tripped = False

    @property
    def tripped(self) -> bool:
        """True when the circuit breaker is in the TRIPPED (risk-off) state."""
        return self._tripped

    @property
    def current_dd(self) -> float:
        """Current drawdown from peak as a fraction (0–1)."""
        return self._current_dd

    @property
    def peak_price(self) -> float:
        """Highest price observed since the last reset."""
        return self._peak_price

    def reset(self) -> None:
        """Clear all state; call at session boundaries."""
        self._peak_price = 0.0
        self._current_dd = 0.0
        self._tripped = False
