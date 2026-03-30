"""Fill model abstraction and market-impact-aware fill simulation."""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections import deque
from datetime import datetime
from random import Random

from src.core.types import ImpactParams, Order
from src.simulator.types import Fill


class FillModel(ABC):
    @abstractmethod
    def simulate(self, order: Order, bar: dict[str, float], timestamp: datetime) -> Fill: ...


class MarketImpactFillModel(FillModel):
    """Volume-aware fill simulation with square-root impact, spread crossing,
    latency delay, and partial fill support."""

    def __init__(self, params: ImpactParams | None = None) -> None:
        self._params = params or ImpactParams()
        self._rng = Random(self._params.seed)

    def simulate(self, order: Order, bar: dict[str, float], timestamp: datetime) -> Fill:
        close = bar["close"]
        volume = bar.get("volume", 0.0)
        sigma = bar.get("daily_atr", 0.0) / close if close > 0 else 0.0

        if volume <= 0:
            return Fill(
                order_type=order.order_type,
                side=order.side,
                symbol=order.symbol,
                lots=order.lots,
                fill_price=close,
                slippage=0.0,
                timestamp=timestamp,
                reason="no_liquidity",
                fill_qty=0.0,
                remaining_qty=order.lots,
                is_partial=True,
                commission_cost=0.0,
            )

        fill_qty = order.lots
        remaining = 0.0
        is_partial = False
        max_fill = self._params.max_adv_participation * volume
        if order.lots > max_fill > 0:
            fill_qty = max_fill
            remaining = order.lots - fill_qty
            is_partial = True

        impact = self.estimate_impact(fill_qty, sigma, volume)
        spread_cost = self._compute_spread(bar, close)
        latency_ms = self._rng.uniform(self._params.min_latency_ms, self._params.max_latency_ms)
        latency_price_shift = self._latency_price_shift(bar, latency_ms)
        commission_cost = self._compute_commission(close, fill_qty)

        sign = 1.0 if order.side == "buy" else -1.0
        total_slippage = sign * (impact + spread_cost) + latency_price_shift
        fill_price = close + total_slippage

        return Fill(
            order_type=order.order_type,
            side=order.side,
            symbol=order.symbol,
            lots=order.lots,
            fill_price=fill_price,
            slippage=abs(total_slippage),
            timestamp=timestamp,
            reason=order.reason,
            market_impact=impact,
            spread_cost=spread_cost,
            commission_cost=commission_cost,
            latency_ms=latency_ms,
            fill_qty=fill_qty,
            remaining_qty=remaining,
            is_partial=is_partial,
        )

    def estimate_impact(self, order_size: float, volatility: float, adv: float) -> float:
        """Square-root impact: k × σ × √(Q / V)."""
        if adv <= 0 or order_size <= 0:
            return 0.0
        return self._params.k * volatility * math.sqrt(order_size / adv)

    def _compute_spread(self, bar: dict[str, float], close: float) -> float:
        if "spread" in bar:
            return bar["spread"] / 2.0
        return self._params.spread_bps * close / 10_000.0

    def _compute_commission(self, close: float, fill_qty: float) -> float:
        bps_component = abs(close) * abs(fill_qty) * self._params.commission_bps / 10_000.0
        fixed_component = abs(fill_qty) * self._params.commission_fixed_per_contract
        return bps_component + fixed_component

    def _latency_price_shift(self, bar: dict[str, float], latency_ms: float) -> float:
        """Interpolate price shift from open→close proportional to latency."""
        open_price = bar.get("open", bar["close"])
        close = bar["close"]
        bar_range = close - open_price
        if bar_range == 0:
            return 0.0
        max_ms = self._params.max_latency_ms
        if max_ms <= 0:
            return 0.0
        fraction = min(latency_ms / max_ms, 1.0)
        return bar_range * fraction * 0.1


class ImpactCalibrator:
    """Tracks predicted vs actual impact and updates k via EMA."""

    def __init__(self, initial_k: float = 1.0, alpha: float = 0.1, min_samples: int = 50) -> None:
        self._k = initial_k
        self._alpha = alpha
        self._min_samples = min_samples
        self._samples: deque[tuple[float, float]] = deque(maxlen=1000)

    @property
    def k(self) -> float:
        return self._k

    def record(self, predicted_impact: float, actual_impact: float) -> None:
        self._samples.append((predicted_impact, actual_impact))
        if len(self._samples) >= self._min_samples and predicted_impact > 0:
            ratio = actual_impact / predicted_impact
            self._k = self._k * (1 - self._alpha) + (self._k * ratio) * self._alpha

    def get_stats(self) -> dict[str, float]:
        n = len(self._samples)
        if n == 0:
            return {"k": self._k, "samples": 0, "mae": 0.0}
        total_error = sum(abs(p - a) for p, a in self._samples)
        return {"k": self._k, "samples": float(n), "mae": total_error / n}
