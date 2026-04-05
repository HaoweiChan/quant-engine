"""TAIFEX session boundary helpers shared across intraday strategies.

Day session:   08:45 – 13:45  (pre-TSE-open at 08:45, settlement 13:45)
Night session: 15:15 – 05:00+1 (spans midnight)
"""
from datetime import time


def in_day_session(t: time) -> bool:
    """08:45 <= t <= 13:15 (excluding settlement/wind-down)."""
    return time(8, 45) <= t <= time(13, 15)


def in_night_session(t: time) -> bool:
    """15:15 <= t <= 04:30+1 (spans midnight)."""
    return t >= time(15, 15) or t <= time(4, 30)


def in_or_window(t: time) -> bool:
    """08:45 <= t < 09:00 — the 15-minute Opening Range building window."""
    return time(8, 45) <= t < time(9, 0)


def in_night_or_window(t: time) -> bool:
    """15:15 <= t < 15:30 — the 15-minute night session Opening Range window."""
    return time(15, 15) <= t < time(15, 30)


def in_force_close(t: time, mode: str = "default") -> bool:
    """Check if the bar falls in a force-close window.

    mode="default"  : day 13:25-13:45, night 04:50-05:00
    mode="disabled"  : always False (strategy manages its own exit)
    """
    if mode == "disabled":
        return False
    return time(13, 25) <= t < time(13, 45) or time(4, 50) <= t <= time(5, 0)
