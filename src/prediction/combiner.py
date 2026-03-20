"""Signal combiner: merge sub-model outputs into MarketSignal with staleness validation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import structlog

from src.core.types import MarketSignal

logger = structlog.get_logger(__name__)

DEFAULT_STALENESS_WINDOW = timedelta(hours=24)
VOL_STOP_SCALE = 1.5
VOL_ADD_SCALE = 2.0
VOL_CONFIDENCE_THRESHOLD = 0.6


@dataclass
class SubModelOutput:
    name: str
    version: str
    updated_at: datetime
    freshness_window: timedelta = DEFAULT_STALENESS_WINDOW


@dataclass
class DirectionOutput(SubModelOutput):
    direction: float = 0.0
    confidence: float = 0.0


@dataclass
class RegimeOutput(SubModelOutput):
    regime: str = "uncertain"
    trend_strength: float = 0.0


@dataclass
class VolatilityOutput(SubModelOutput):
    vol_forecast: float = 0.0
    confidence: float = 0.0


class SignalCombiner:
    """Merge direction, regime, and volatility outputs into a single MarketSignal."""

    def __init__(
        self,
        direction_freshness: timedelta = DEFAULT_STALENESS_WINDOW,
        regime_freshness: timedelta = DEFAULT_STALENESS_WINDOW,
        volatility_freshness: timedelta = DEFAULT_STALENESS_WINDOW,
    ) -> None:
        self._direction_freshness = direction_freshness
        self._regime_freshness = regime_freshness
        self._volatility_freshness = volatility_freshness

    def combine(
        self,
        direction: DirectionOutput,
        regime: RegimeOutput,
        volatility: VolatilityOutput,
        now: datetime | None = None,
    ) -> MarketSignal:
        """Combine sub-model outputs into a MarketSignal."""
        now = now or datetime.now()
        confidence_valid = self._check_freshness(direction, regime, volatility, now)

        # Suggested parameter hints from vol forecast
        suggested_stop: float | None = None
        suggested_add: float | None = None
        if volatility.confidence >= VOL_CONFIDENCE_THRESHOLD and volatility.vol_forecast > 0:
            base_atr_mult = volatility.vol_forecast / 100.0
            suggested_stop = max(VOL_STOP_SCALE, base_atr_mult * VOL_STOP_SCALE)
            suggested_add = max(VOL_ADD_SCALE, base_atr_mult * VOL_ADD_SCALE)

        model_version = self._build_version(direction, regime, volatility)

        return MarketSignal(
            timestamp=now,
            direction=direction.direction,
            direction_conf=direction.confidence,
            regime=regime.regime,
            trend_strength=regime.trend_strength,
            vol_forecast=volatility.vol_forecast,
            suggested_stop_atr_mult=suggested_stop,
            suggested_add_atr_mult=suggested_add,
            model_version=model_version,
            confidence_valid=confidence_valid,
        )

    def _check_freshness(
        self,
        direction: DirectionOutput,
        regime: RegimeOutput,
        volatility: VolatilityOutput,
        now: datetime,
    ) -> bool:
        """If any sub-model hasn't updated within its freshness window, invalidate."""
        models: list[tuple[SubModelOutput, timedelta]] = [
            (direction, self._direction_freshness),
            (regime, self._regime_freshness),
            (volatility, self._volatility_freshness),
        ]
        for model, window in models:
            age = now - model.updated_at
            if age > window:
                logger.warning(
                    "Sub-model %s is stale (age=%s, window=%s)",
                    model.name, age, window,
                )
                return False
        return True

    @staticmethod
    def _build_version(
        direction: DirectionOutput,
        regime: RegimeOutput,
        volatility: VolatilityOutput,
    ) -> str:
        return f"dir:{direction.version}|reg:{regime.version}|vol:{volatility.version}"
