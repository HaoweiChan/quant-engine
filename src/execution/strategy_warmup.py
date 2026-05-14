"""Strategy indicator warmup from historical bars at the strategy's native timeframe.

Cold-starting a `LiveStrategyRunner` with deep indicators (e.g. EMA-144)
emits garbage signals until ~3× the indicator period has elapsed. The
gap analysis in ``docs/live-trading-gap-analysis.md`` traces the
"faulty signals" reports directly to this cold-start window.

`StrategyWarmup.run()` replays historical bars from ``data/market.db``
through the runner's ``PositionEngine.on_snapshot(..., warmup_mode=True)``
so all indicator state, EMA history, and trailing-stop high-water marks
are populated before the first live bar arrives. Order emission is
suppressed inside the engine; the position ledger is never mutated.

Bars are aggregated to the strategy's ``bar_agg`` timeframe before being
fed to the engine so indicator state (Donchian channel width, RSI, VWAP)
is calibrated against the same resolution the live MultiTimeframeRouter
delivers. Feeding raw 1m bars to a 15m strategy would produce a Donchian
20-bar lookback spanning only 20 minutes instead of the correct 300 minutes,
causing spurious breakout signals for the first ~5 hours after every restart
until the live bars flushed out the stale warmup data.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog

from src.broker_gateway.live_bar_store import MinuteBar
from src.data.db import DEFAULT_DB_PATH, Database
from src.execution.live_strategy_runner import LiveStrategyRunner
from src.strategies.registry import get_warmup_bars

logger = structlog.get_logger(__name__)


def _aggregate_to_resampled(rows: list, tf_minutes: int) -> list[MinuteBar]:
    """Aggregate 1m DB bars into tf_minutes-minute bars.

    Uses the same session-relative bucket indexing as MultiTimeframeRouter
    so warmup bars align to the same window boundaries as live bars:

        bucket_index = minutes_into_session // tf_minutes
        bucket_ts    = session_open + bucket_index * tf_minutes

    Windows never span a session boundary — the session_id component of
    the key forces a flush when the session changes.

    Returns bars sorted ascending by bucket timestamp, ready to feed into
    ``engine.on_snapshot(warmup_mode=True)`` one-by-one.
    """
    from src.data.session_utils import session_id as get_sid
    from src.data.session_utils import session_open_dt

    # (session_id, bucket_index) → mutable OHLCV accumulator
    windows: dict[tuple[str, int], dict] = {}

    for row in rows:
        ts = row.timestamp
        # session_utils works with naive Taipei-local datetimes (matching the
        # ohlcv_bars storage convention). Strip tzinfo if present so the
        # subtraction below doesn't raise "can't subtract offset-naive and
        # offset-aware datetimes". Production DB rows are always naive.
        if getattr(ts, "tzinfo", None) is not None:
            ts = ts.replace(tzinfo=None)
        sid = get_sid(ts)
        open_dt = session_open_dt(sid)
        minutes_into_session = int((ts - open_dt).total_seconds() / 60)
        bucket_index = minutes_into_session // tf_minutes
        bucket_ts = open_dt + timedelta(minutes=bucket_index * tf_minutes)
        key = (sid, bucket_index)

        if key not in windows:
            windows[key] = {
                "ts": bucket_ts,
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": float(row.volume),
            }
        else:
            w = windows[key]
            w["high"] = max(w["high"], float(row.high))
            w["low"] = min(w["low"], float(row.low))
            w["close"] = float(row.close)
            w["volume"] += float(row.volume)

    return [
        MinuteBar(
            timestamp=w["ts"],
            open=w["open"],
            high=w["high"],
            low=w["low"],
            close=w["close"],
            volume=int(w["volume"]),
        )
        for w in sorted(windows.values(), key=lambda x: x["ts"])
    ]


class StrategyWarmup:
    """Hydrates a runner's PositionEngine from historical bars at the
    strategy's native aggregation timeframe.

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
        """Replay historical bars through the engine; return bars replayed.

        Fetches raw 1m bars from ``[end - lookback_minutes, end]``,
        aggregates them to the strategy's ``bar_agg`` timeframe (matching
        the live MultiTimeframeRouter cadence), then feeds each aggregated
        bar through ``engine.on_snapshot(warmup_mode=True)``.

        Returns the number of *aggregated* bars fed (not raw 1m bars).
        """
        if end is None:
            end = datetime.now(UTC)
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

        bar_agg: int = getattr(self._runner, "_bar_agg", 1)
        if bar_agg > 1:
            bars = _aggregate_to_resampled(rows, bar_agg)
        else:
            bars = [
                MinuteBar(
                    timestamp=row.timestamp,
                    open=float(row.open),
                    high=float(row.high),
                    low=float(row.low),
                    close=float(row.close),
                    volume=float(row.volume),
                )
                for row in rows
            ]

        engine = self._runner._engine  # pyright: ignore[reportPrivateUsage]
        bars_replayed = 0
        for bar in bars:
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
            bar_agg=bar_agg,
            bars_1m_fetched=len(rows),
            bars_replayed=bars_replayed,
            lookback_window_minutes=self._lookback_bars,
            window_start=rows[0].timestamp.isoformat(),
            window_end=rows[-1].timestamp.isoformat(),
        )
        return bars_replayed
