"""Strategy indicator warmup from historical 1m bars.

Cold-starting a `LiveStrategyRunner` with deep indicators (e.g. EMA-144)
emits garbage signals until ~3× the indicator period has elapsed. The
gap analysis in ``docs/live-trading-gap-analysis.md`` traces the
"faulty signals" reports directly to this cold-start window.

`StrategyWarmup.run()` replays historical 1m bars from ``data/market.db``
through the runner's ``PositionEngine.on_snapshot(..., warmup_mode=True)``
so all indicator state, EMA history, and trailing-stop high-water marks
are populated before the first live bar arrives. Order emission is
suppressed inside the engine; the position ledger is never mutated.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog

from src.broker_gateway.live_bar_store import MinuteBar
from src.data.db import DEFAULT_DB_PATH, Database
from src.execution.live_strategy_runner import LiveStrategyRunner
from src.strategies.registry import get_warmup_bars

logger = structlog.get_logger(__name__)


class StrategyWarmup:
    """Hydrates a runner's PositionEngine from historical 1m bars.

    Designed to run synchronously immediately before the first live bar
    is dispatched. Cheap because it reuses the runner's own snapshot
    builder and the engine short-circuits in warmup mode.
    """

    def __init__(
        self,
        runner: LiveStrategyRunner,
        db: Database | None = None,
        lookback_bars: int | None = None,
    ) -> None:
        self._runner = runner
        self._db = db if db is not None else Database(f"sqlite:///{DEFAULT_DB_PATH}")
        if lookback_bars is None:
            lookback_bars = get_warmup_bars(runner.strategy_slug)
        # 1.5x slack to account for session gaps inside the lookback window
        # so we still hit the target number of usable bars after gap-skipping.
        self._lookback_bars = int(max(lookback_bars, 1) * 1.5)

    def run(self, end: datetime | None = None) -> int:
        """Replay historical 1m bars through the engine; return bars replayed.

        ``end`` defaults to ``datetime.now(UTC)``. Bars are pulled from
        ``[end - lookback_minutes, end]``, sorted ascending, and fed
        one-by-one through ``engine.on_snapshot(warmup_mode=True)``.
        """
        if end is None:
            end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=self._lookback_bars)
        try:
            rows = self._db.get_ohlcv(self._runner.symbol, start, end)
        except Exception:
            logger.exception(
                "strategy_warmup_db_read_failed",
                slug=self._runner.strategy_slug,
                symbol=self._runner.symbol,
            )
            return 0
        if not rows:
            logger.warning(
                "strategy_warmup_no_bars",
                slug=self._runner.strategy_slug,
                symbol=self._runner.symbol,
                start=start.isoformat(),
                end=end.isoformat(),
            )
            return 0

        engine = self._runner._engine  # pyright: ignore[reportPrivateUsage]
        bars_replayed = 0
        for row in rows:
            bar = MinuteBar(
                timestamp=row.timestamp,
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=float(row.volume),
            )
            snapshot = self._runner._bar_to_snapshot(bar)  # pyright: ignore[reportPrivateUsage]
            try:
                engine.on_snapshot(snapshot, signal=None, account=None, warmup_mode=True)
            except Exception:
                logger.exception(
                    "strategy_warmup_bar_failed",
                    slug=self._runner.strategy_slug,
                    bar_ts=bar.timestamp.isoformat(),
                )
                continue
            bars_replayed += 1

        logger.info(
            "strategy_warmup_complete",
            slug=self._runner.strategy_slug,
            symbol=self._runner.symbol,
            session_id=self._runner.session_id,
            bars_replayed=bars_replayed,
            lookback_window_minutes=self._lookback_bars,
            window_start=rows[0].timestamp.isoformat(),
            window_end=rows[-1].timestamp.isoformat(),
        )
        return bars_replayed
