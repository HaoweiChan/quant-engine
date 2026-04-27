"""Unit tests for ``_compute_force_flat_indices`` slug-aware short-circuit.

Locks the three documented branches so future refactors of either the function
or ``is_intraday_strategy`` cannot silently regress the behavior:

* ``slug=`` for a SWING strategy: returns only the final-bar index, so the
  position is closed at end-of-window but never at intraday session boundaries.
* ``slug=`` for an INTRADAY strategy: returns every session-boundary index
  plus the final index (legacy session-close behavior).
* ``slug=None``: preserves legacy session-boundary behavior so any caller
  that has not been migrated still gets the conservative over-flatten path.

See docs/risk-auditor-signoff-holding-period-dispatch.md.
"""

from __future__ import annotations

from datetime import datetime

from src.mcp_server.facade import _compute_force_flat_indices

# Day session bar (~08:45-13:45) followed by a CLOSED gap then night session
# (~15:00 - 04:59 next day). _compute_force_flat_indices keys on the
# session_id transition between consecutive bars.
TIMESTAMPS = [
    datetime(2025, 6, 11, 8, 46),   # 0  day session start
    datetime(2025, 6, 11, 13, 44),  # 1  day session last bar  -> session boundary
    datetime(2025, 6, 11, 15, 0),   # 2  night session start
    datetime(2025, 6, 12, 4, 59),   # 3  night session last bar -> session boundary
    datetime(2025, 6, 12, 8, 46),   # 4  next day session start
    datetime(2025, 6, 12, 13, 44),  # 5  next day session last bar (final index)
]

SWING_SLUG = "swing/trend_following/compounding_trend_long"
INTRADAY_SLUG = "short_term/trend_following/night_session_long"


def test_swing_strategy_short_circuits_to_final_bar_only() -> None:
    """SWING strategies hold across sessions; only the end-of-window flat fires."""
    result = _compute_force_flat_indices(TIMESTAMPS, slug=SWING_SLUG)
    assert result == {len(TIMESTAMPS) - 1}


def test_intraday_strategy_produces_session_boundaries() -> None:
    """INTRADAY strategies must flatten at every session-close bar plus end-of-window."""
    result = _compute_force_flat_indices(TIMESTAMPS, slug=INTRADAY_SLUG)
    assert result == {1, 3, 5}


def test_no_slug_preserves_legacy_session_boundary_behavior() -> None:
    """Backward compatibility: callers that never pass slug still get session boundaries."""
    result = _compute_force_flat_indices(TIMESTAMPS)
    assert result == {1, 3, 5}


def test_empty_timestamps_returns_empty_set() -> None:
    """Defensive: zero-length input yields no indices regardless of slug."""
    assert _compute_force_flat_indices([], slug=SWING_SLUG) == set()
    assert _compute_force_flat_indices([], slug=INTRADAY_SLUG) == set()
    assert _compute_force_flat_indices([]) == set()


def test_swing_with_single_bar_returns_just_that_bar() -> None:
    """Single-bar window: SWING short-circuit still emits the closing flat at index 0."""
    one_bar = [datetime(2025, 6, 11, 8, 46)]
    assert _compute_force_flat_indices(one_bar, slug=SWING_SLUG) == {0}
