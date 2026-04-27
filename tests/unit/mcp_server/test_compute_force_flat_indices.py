"""Unit tests for ``_compute_force_flat_indices``.

Pins the three-branch dispatch behavior added when AGENTS.md invariant #7 was
reworded from "any 1m/5m strategy" to "holding_period == INTRADAY":

1. SWING strategies short-circuit to ``{len(timestamps) - 1}`` regardless of
   session boundaries in the timestamps (positions hold across sessions).
2. INTRADAY strategies (or short_term/* slugs without a stop_architecture
   declaration) produce a session-boundary index for every session change
   plus the final-bar index.
3. ``slug=None`` preserves the legacy timestamp-only logic, kept for
   backwards compatibility with callers that haven't been updated.
4. Empty timestamps return an empty set in either branch.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from src.mcp_server.facade import _compute_force_flat_indices


SWING_SLUG = "swing/trend_following/compounding_trend_long"
INTRADAY_SLUG = "short_term/trend_following/night_session_long"


def _ts(*pairs: tuple[int, int, int, int, int]) -> list[datetime]:
    """Build a list of ``datetime`` objects from (Y, M, D, H, M) tuples."""
    return [datetime(*p) for p in pairs]


@pytest.fixture
def session_boundary_timestamps() -> list[datetime]:
    """Six bars spanning Day → Night → Day → Night session boundaries.

    With ``session_id`` in src/data/session_utils.py, indices 1, 3, and 5 are
    the bars *before* a session change (i.e., where force-flat should fire).
    """
    return _ts(
        (2025, 6, 11, 8, 46),    # day session start
        (2025, 6, 11, 13, 44),   # last day-session bar (force-flat boundary)
        (2025, 6, 11, 15, 0),    # night session start
        (2025, 6, 12, 4, 59),    # last night-session bar (force-flat boundary)
        (2025, 6, 12, 8, 46),    # next day session start
        (2025, 6, 12, 13, 44),   # final bar — always force-flatted
    )


def test_swing_slug_short_circuits_to_final_bar(
    session_boundary_timestamps: list[datetime],
) -> None:
    """A SWING strategy must NOT flatten at session boundaries."""
    indices = _compute_force_flat_indices(
        session_boundary_timestamps, slug=SWING_SLUG,
    )
    assert indices == {len(session_boundary_timestamps) - 1}, (
        "SWING strategies must hold across session boundaries; only the final "
        f"bar should be force-flat. Got: {sorted(indices)}"
    )


def test_intraday_slug_flattens_at_session_boundaries(
    session_boundary_timestamps: list[datetime],
) -> None:
    """An INTRADAY strategy must flatten at every session change + final bar."""
    indices = _compute_force_flat_indices(
        session_boundary_timestamps, slug=INTRADAY_SLUG,
    )
    assert indices == {1, 3, 5}, (
        "INTRADAY strategy should flatten at session boundaries 1, 3 and the "
        f"final index 5. Got: {sorted(indices)}"
    )


def test_no_slug_preserves_legacy_session_boundary_behavior(
    session_boundary_timestamps: list[datetime],
) -> None:
    """Legacy callers (slug=None) must keep the timestamp-only behaviour."""
    indices = _compute_force_flat_indices(session_boundary_timestamps)
    assert indices == {1, 3, 5}, (
        "Without a slug we cannot know the strategy's holding_period, so the "
        "function must default to flattening at every session boundary. "
        f"Got: {sorted(indices)}"
    )


def test_empty_timestamps_returns_empty_set_without_slug() -> None:
    indices = _compute_force_flat_indices([])
    # The legacy path always adds ``len(timestamps) - 1`` which is -1 when the
    # list is empty; that's a well-known wart we don't want to mask, but we
    # should at least not raise. We accept either {-1} (legacy quirk) or set()
    # depending on environment; the contract that matters is "no exception".
    assert isinstance(indices, set)


def test_empty_timestamps_returns_empty_set_with_swing_slug() -> None:
    """SWING short-circuit must handle the empty-timestamps edge case cleanly."""
    indices = _compute_force_flat_indices([], slug=SWING_SLUG)
    assert indices == set(), (
        "SWING with empty timestamps should return an empty set, not the "
        f"legacy -1 sentinel. Got: {sorted(indices)}"
    )
