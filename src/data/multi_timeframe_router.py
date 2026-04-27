"""Centralized 1m → N-minute live bar aggregation.

Replaces the per-strategy ``_bar_buffer`` accumulator in
``LiveStrategyRunner``. Each (symbol, timeframe) has exactly one
aggregation window that fans out to all subscribers, so N strategies
on the same TF share state instead of each maintaining a separate
counter (which is fragile and a known source of intermittent "faulty
signals" when one strategy's counter falls out of sync).

Session boundaries are respected via :mod:`src.data.session_utils`:
windows that would span the 13:45-15:00 day/night gap or the
05:00-08:45 night/day gap are flushed and a fresh window starts in
the new session. This matches the semantics of
:mod:`src.broker_gateway.live_bar_store` and
:mod:`src.data.aggregator`.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field

import structlog

from src.broker_gateway.live_bar_store import MinuteBar
from src.data.session_utils import session_id, session_open_dt

logger = structlog.get_logger(__name__)

ResampledBarCallback = Callable[[str, "MinuteBar"], None]


@dataclass
class _ResampleWindow:
    """Per (symbol, tf) aggregation window."""

    timestamp: object  # datetime of first 1m bar in window
    session_id: str
    bucket_index: int
    bar_count: int
    open: float
    high: float
    low: float
    close: float
    volume: int

    def fold(self, bar: MinuteBar) -> None:
        self.high = max(self.high, bar.high)
        self.low = min(self.low, bar.low)
        self.close = bar.close
        self.volume += bar.volume
        self.bar_count += 1

    def emit(self) -> MinuteBar:
        return MinuteBar(
            timestamp=self.timestamp,  # type: ignore[arg-type]
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
        )


@dataclass
class _Subscription:
    symbol: str
    tf_minutes: int
    callback: ResampledBarCallback


class MultiTimeframeRouter:
    """Fan a single 1m bar stream into per-(symbol, tf) resampled streams.

    Thread-safe: ``on_minute_bar`` is called from the
    ``LiveMinuteBarStore`` callback thread, which may differ from the
    threads that registered subscriptions. All mutation of the window
    map happens under ``_lock``; callbacks fire outside the lock so a
    slow subscriber cannot stall the tick thread.
    """

    def __init__(self) -> None:
        self._subscriptions: list[_Subscription] = []
        self._windows: dict[tuple[str, int], _ResampleWindow] = {}
        self._lock = threading.Lock()

    def subscribe(
        self,
        symbol: str,
        tf_minutes: int,
        callback: ResampledBarCallback,
    ) -> None:
        """Register ``callback`` to receive ``tf_minutes``-resampled bars."""
        if tf_minutes <= 0:
            raise ValueError(f"tf_minutes must be positive, got {tf_minutes}")
        with self._lock:
            self._subscriptions.append(
                _Subscription(symbol=symbol, tf_minutes=tf_minutes, callback=callback)
            )

    def unsubscribe(self, callback: ResampledBarCallback) -> None:
        """Drop a previously registered callback."""
        with self._lock:
            self._subscriptions = [
                s for s in self._subscriptions if s.callback is not callback
            ]

    def reset(self, symbol: str | None = None) -> None:
        """Discard all open windows. Called on full pipeline restart.

        When ``symbol`` is None, every window is discarded; otherwise
        only that symbol's windows are reset.
        """
        with self._lock:
            if symbol is None:
                self._windows.clear()
            else:
                self._windows = {
                    k: v for k, v in self._windows.items() if k[0] != symbol
                }

    def on_minute_bar(self, symbol: str, bar: MinuteBar) -> None:
        """Ingest a closed 1m bar from ``LiveMinuteBarStore``.

        Folds into every active (symbol, tf) window and dispatches to
        subscribers when a window closes. Uses session-relative bucket
        indices (matching ``LiveMinuteBarStore._fold_into_higher_tfs_locked``)
        so live and playback paths emit at identical cadence.
        """
        ts = (
            bar.timestamp.replace(tzinfo=None)
            if bar.timestamp.tzinfo
            else bar.timestamp
        )
        sid = session_id(ts)
        if sid == "CLOSED":
            return

        emissions: list[tuple[ResampledBarCallback, str, MinuteBar]] = []
        with self._lock:
            tfs_for_symbol = {
                s.tf_minutes for s in self._subscriptions if s.symbol == symbol
            }
            for tf in tfs_for_symbol:
                if tf == 1:
                    # 1m subscribers get the bar verbatim, no folding.
                    for sub in self._subscriptions:
                        if sub.symbol == symbol and sub.tf_minutes == 1:
                            emissions.append((sub.callback, symbol, bar))
                    continue

                # Compute the bucket index for this bar. Buckets are
                # session-relative so a window never spans the day↔night
                # gap, matching the live store's invariant.
                sopen = session_open_dt(sid)
                offset_secs = int((ts - sopen).total_seconds())
                if offset_secs < 0:
                    continue
                bucket_secs = tf * 60
                bucket_index = offset_secs // bucket_secs
                # Left-aligned window timestamp for this bucket.
                from datetime import timedelta
                bar_ts = sopen + timedelta(seconds=bucket_index * bucket_secs)

                key = (symbol, tf)
                window = self._windows.get(key)
                # Session change OR new bucket → close & emit existing window.
                rolled_over = (
                    window is not None
                    and (
                        window.session_id != sid
                        or window.bucket_index != bucket_index
                    )
                )
                if rolled_over:
                    closed = window.emit()  # type: ignore[union-attr]
                    for sub in self._subscriptions:
                        if sub.symbol == symbol and sub.tf_minutes == tf:
                            emissions.append((sub.callback, symbol, closed))
                    window = None

                if window is None:
                    window = _ResampleWindow(
                        timestamp=bar_ts,
                        session_id=sid,
                        bucket_index=bucket_index,
                        bar_count=1,
                        open=bar.open,
                        high=bar.high,
                        low=bar.low,
                        close=bar.close,
                        volume=bar.volume,
                    )
                    self._windows[key] = window
                else:
                    window.fold(bar)

        for callback, sym, closed_bar in emissions:
            try:
                callback(sym, closed_bar)
            except Exception:
                logger.exception(
                    "multi_tf_router_callback_error",
                    symbol=sym,
                    bar_ts=str(closed_bar.timestamp),
                )

    def attach_to_store(self, bar_store) -> None:  # type: ignore[no-untyped-def]
        """Convenience: subscribe ``on_minute_bar`` to a bar store's 1m stream."""
        bar_store.register_bar_callback(self.on_minute_bar)
