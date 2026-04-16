"""Streaming rolling z-score indicator.

Tracks the rolling mean and population standard deviation of a series over
a fixed window, and emits the z-score ``(x - mean) / std`` of the most
recent observation.

Supports an optional ``jump_threshold`` that clears the window whenever the
incoming observation gaps by more than the threshold — useful for futures
calendar spreads (contract rolls cause abrupt level shifts that otherwise
poison the rolling statistics).
"""
from __future__ import annotations

from collections import deque
from datetime import datetime

PARAM_SPEC: dict[str, dict] = {
    "period": {
        "type": "int",
        "default": 60,
        "min": 10,
        "max": 500,
        "description": "Rolling window size (bars) for z-score computation.",
    },
    "min_std": {
        "type": "float",
        "default": 1.0,
        "min": 0.01,
        "max": 10.0,
        "description": "Minimum std dev below which z-score is suppressed (None).",
    },
    "jump_threshold": {
        "type": "float",
        "default": 0.0,
        "min": 0.0,
        "max": 1000.0,
        "description": (
            "If > 0, reset the window when |x_t - x_{t-1}| exceeds this "
            "threshold (contract-roll gap handling). 0 disables."
        ),
    },
}


class RollingZScore:
    """Rolling z-score with optional gap-based buffer reset.

    Parameters
    ----------
    period : int
        Rolling window length (must be >= 2).
    min_std : float
        Minimum std dev to emit a z-score; below this the window is treated
        as flat and ``value`` returns ``None``.
    jump_threshold : float
        If positive, a jump greater than this between consecutive inputs
        clears the window and suppresses the z-score for one bar. Use 0.0
        to disable gap handling.
    """

    __slots__ = (
        "_period",
        "_min_std",
        "_jump_threshold",
        "_buf",
        "_last_value",
        "_last_ts",
        "_mean",
        "_std",
        "_z",
    )

    def __init__(
        self,
        period: int = 60,
        min_std: float = 1.0,
        jump_threshold: float = 0.0,
    ) -> None:
        if period < 2:
            raise ValueError(f"period must be >= 2, got {period}")
        if min_std <= 0:
            raise ValueError(f"min_std must be > 0, got {min_std}")
        if jump_threshold < 0:
            raise ValueError(f"jump_threshold must be >= 0, got {jump_threshold}")
        self._period = period
        self._min_std = min_std
        self._jump_threshold = jump_threshold
        self._buf: deque[float] = deque(maxlen=period)
        self._last_value: float | None = None
        self._last_ts: datetime | None = None
        self._mean: float = 0.0
        self._std: float = 0.0
        self._z: float | None = None

    def update(
        self, value: float, timestamp: datetime | None = None
    ) -> float | None:
        """Feed one observation, return current z-score (or None).

        Parameters
        ----------
        value : float
            The raw observation (e.g. spread price).
        timestamp : datetime, optional
            If provided and equal to the previously seen timestamp, the
            update is treated as idempotent and state is not advanced —
            useful when both entry and stop policies feed the same bar.
        """
        if timestamp is not None and timestamp == self._last_ts:
            return self._z
        self._last_ts = timestamp

        if (
            self._jump_threshold > 0
            and self._last_value is not None
            and abs(value - self._last_value) > self._jump_threshold
        ):
            # Clear window AND rolling stats so downstream readers of .mean/.std
            # do not pick up pre-jump values during post-jump warmup.
            self._buf.clear()
            self._mean = 0.0
            self._std = 0.0
            self._z = None
        self._last_value = value
        self._buf.append(value)

        if len(self._buf) < self._period:
            self._z = None
            return None

        n = len(self._buf)
        mean = sum(self._buf) / n
        var = sum((x - mean) ** 2 for x in self._buf) / n
        std = var ** 0.5
        self._mean = mean
        self._std = std
        if std < self._min_std:
            self._z = None
            return None
        self._z = (value - mean) / std
        return self._z

    @property
    def value(self) -> float | None:
        """Current z-score, or None during warmup / after a jump / low std."""
        return self._z

    @property
    def mean(self) -> float:
        """Rolling mean of the current window (0.0 before warmup)."""
        return self._mean

    @property
    def std(self) -> float:
        """Rolling population std dev of the current window (0.0 before warmup)."""
        return self._std

    @property
    def ready(self) -> bool:
        """True once the window is full and std >= min_std."""
        return self._z is not None

    def reset(self) -> None:
        """Clear all accumulated state for session boundary resets."""
        self._buf.clear()
        self._last_value = None
        self._last_ts = None
        self._mean = 0.0
        self._std = 0.0
        self._z = None
