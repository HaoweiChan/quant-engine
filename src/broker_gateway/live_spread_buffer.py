"""Live synthetic spread bar builder (Phase C1).

Backtests run spread strategies on synthetic OHLCV bars built from R1 and
R2 leg closes (see ``facade._build_spread_bars``). The live pipeline did
not have an equivalent: ``LiveStrategyRunner._matches_symbol`` accepted
the R1 leg's tick stream as the strategy's price feed, ignored the R2
leg entirely, and the strategy ran on single-leg prices instead of the
intended spread.

``LiveSpreadBarBuilder`` closes that gap. It subscribes to per-symbol
bar callbacks on a ``LiveMinuteBarStore``, buffers the most recently
completed bar per leg, and emits a synthetic spread ``MinuteBar`` via
its own callback list when both legs report the same ``minute_ts``.

The synthetic OHLCV is constructed leg-wise:

    open   = leg1.open  - leg2.open  + offset
    high   = leg1.high  - leg2.high  + offset   # not strictly bar-correct
    low    = leg1.low   - leg2.low   + offset
    close  = leg1.close - leg2.close + offset
    volume = min(leg1.volume, leg2.volume)      # paired-leg liquidity

The offset is the same convention as ``facade._build_spread_bars``:
``max(-min_spread + 100.0, 0.0)`` over a warmup window so the synthetic
price stays positive (a ``MarketSnapshot`` requirement). The first
``warmup_bars`` paired bars accumulate the offset; subsequent bars use
the locked offset.

Order routing is intentionally NOT inside this module. The builder
emits bars; turning a spread engine's order into two child leg orders
on ``SinopacGateway`` happens in a separate adapter (see plan C1
follow-up). Keeping the bar pipeline isolated makes both pieces
testable without a live broker.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from src.broker_gateway.live_bar_store import MinuteBar

if TYPE_CHECKING:
    from src.broker_gateway.live_bar_store import LiveMinuteBarStore

logger = structlog.get_logger(__name__)

SpreadBarCallback = Callable[[str, MinuteBar], None]


@dataclass
class _LegState:
    """Most recent bar received for one leg of a spread."""
    bar: MinuteBar | None = None


class LiveSpreadBarBuilder:
    """Pair R1 + R2 minute bars into a synthetic spread MinuteBar stream.

    Args:
        spread_symbol: Strategy-facing symbol the synthetic bars are
            attributed to (typically ``"TX"`` / ``"MTX"`` — the leg-1
            symbol). The runner subscribes to bars under this key.
        leg1_symbol: Concrete leg-1 underlying (e.g. ``"TX"``,
            ``"MTX"``). Must match the symbol the bar store reports.
        leg2_symbol: Concrete leg-2 underlying (e.g. ``"TX_R2"``).
        warmup_bars: Number of paired bars to observe before locking
            the offset. Defaults to 60 (≈1 hour of 1m bars during a
            TAIFEX session).
    """

    def __init__(
        self,
        spread_symbol: str,
        leg1_symbol: str,
        leg2_symbol: str,
        warmup_bars: int = 60,
    ) -> None:
        if leg1_symbol == leg2_symbol:
            raise ValueError(
                f"leg1_symbol == leg2_symbol ({leg1_symbol!r}); "
                f"a spread requires two distinct legs",
            )
        self._spread_symbol = spread_symbol
        self._leg1 = leg1_symbol
        self._leg2 = leg2_symbol
        self._warmup_bars = warmup_bars
        self._states: dict[str, _LegState] = {
            leg1_symbol: _LegState(),
            leg2_symbol: _LegState(),
        }
        self._spread_history: list[float] = []
        self._offset: float | None = None
        self._lock = threading.Lock()
        self._callbacks: list[SpreadBarCallback] = []

    @property
    def spread_symbol(self) -> str:
        return self._spread_symbol

    @property
    def leg_symbols(self) -> tuple[str, str]:
        return (self._leg1, self._leg2)

    @property
    def offset(self) -> float | None:
        """Locked offset (``None`` until warmup completes)."""
        return self._offset

    def register_callback(self, cb: SpreadBarCallback) -> None:
        """Register a function called as ``cb(spread_symbol, synthetic_bar)``
        whenever both legs have reported a bar at the same ``minute_ts``.
        Callbacks fire OUTSIDE the internal lock so a slow consumer
        cannot block another leg's bar from being recorded.
        """
        self._callbacks.append(cb)

    def attach_to_store(self, store: LiveMinuteBarStore) -> None:
        """Subscribe to the bar store's per-symbol completion callbacks
        so this builder receives leg bars without the caller wiring
        anything per-leg.
        """
        store.register_bar_callback(self._on_leg_bar)

    # ----------------------------------------------------------------- input
    def _on_leg_bar(self, symbol: str, bar: MinuteBar) -> None:
        """LiveMinuteBarStore callback. Filters to our two legs and
        attempts to pair on the bar's minute timestamp.
        """
        if symbol not in self._states:
            return
        spread_bar: MinuteBar | None = None
        with self._lock:
            self._states[symbol].bar = bar
            other_sym = self._leg2 if symbol == self._leg1 else self._leg1
            other = self._states[other_sym].bar
            if other is not None and other.timestamp == bar.timestamp:
                leg1_bar = self._states[self._leg1].bar
                leg2_bar = self._states[self._leg2].bar
                if leg1_bar is None or leg2_bar is None:
                    return  # defensive — both must be present
                spread_bar = self._build_spread_bar(leg1_bar, leg2_bar)
                # Consume both — never re-emit the same paired ts.
                self._states[self._leg1].bar = None
                self._states[self._leg2].bar = None
        if spread_bar is None:
            return
        for cb in self._callbacks:
            try:
                cb(self._spread_symbol, spread_bar)
            except Exception:
                logger.exception(
                    "live_spread_bar_callback_error",
                    spread=self._spread_symbol,
                )

    # -------------------------------------------------------------- spread bar
    def _build_spread_bar(self, leg1: MinuteBar, leg2: MinuteBar) -> MinuteBar:
        """Construct one synthetic spread MinuteBar from two paired leg bars.

        Offset locks after ``warmup_bars`` paired observations; until
        then the synthetic OHLCV uses a running offset re-derived each
        bar from the spread history. The lock-after-warmup behaviour
        matches the backtest convention so live and backtest produce
        the same z-score interpretation.
        """
        raw_close_spread = leg1.close - leg2.close
        self._spread_history.append(raw_close_spread)
        if len(self._spread_history) > self._warmup_bars * 2:
            self._spread_history = self._spread_history[-self._warmup_bars:]

        if self._offset is None and len(self._spread_history) >= self._warmup_bars:
            min_spread = min(self._spread_history[: self._warmup_bars])
            self._offset = max(0.0, -min_spread + 100.0)

        offset = (
            self._offset
            if self._offset is not None
            else max(0.0, -min(self._spread_history) + 100.0)
        )

        return MinuteBar(
            timestamp=leg1.timestamp,
            open=leg1.open - leg2.open + offset,
            high=leg1.high - leg2.high + offset,
            low=leg1.low - leg2.low + offset,
            close=leg1.close - leg2.close + offset,
            volume=min(leg1.volume, leg2.volume),
        )
