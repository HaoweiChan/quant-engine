"""Periodic cleanup of old activity logs (30-day retention)."""
from __future__ import annotations

import structlog
from pathlib import Path

logger = structlog.get_logger(__name__)


async def cleanup_old_activities(
    days: int = 30,
    db_path: Path | None = None,
) -> dict[str, int]:
    """Clean up activity logs older than N days.

    Returns stats: {"old_logs_deleted": int, "inactive_strategies_deleted": int}
    """
    from src.trading_session.store import ActivityLogger

    logger.info(
        "activity_cleanup_start",
        days=days,
    )

    activity_logger = ActivityLogger(db_path=db_path)

    # Delete logs older than retention period
    old_count = activity_logger.cleanup_old_logs(days=days)
    logger.info("activity_cleanup_old_logs", deleted=old_count, days=days)

    # Delete logs for inactive strategies
    inactive_count = activity_logger.cleanup_inactive_strategies(days=days)
    logger.info("activity_cleanup_inactive_strategies", deleted=inactive_count, days=days)

    total = old_count + inactive_count
    logger.info(
        "activity_cleanup_complete",
        total_deleted=total,
        old_logs=old_count,
        inactive_strategies=inactive_count,
    )

    return {
        "old_logs_deleted": old_count,
        "inactive_strategies_deleted": inactive_count,
    }


def cleanup_old_activities_sync(
    days: int = 30,
    db_path: Path | None = None,
) -> dict[str, int]:
    """Synchronous version of cleanup (for cron jobs or simple scripts)."""
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(cleanup_old_activities(days=days, db_path=db_path))
    finally:
        loop.close()
