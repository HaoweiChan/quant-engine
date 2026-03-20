"""Tests for signal combiner: assembly, staleness invalidation, version tagging."""
from __future__ import annotations

from datetime import datetime, timedelta

from src.prediction.combiner import (
    DirectionOutput,
    RegimeOutput,
    SignalCombiner,
    VolatilityOutput,
)


def _make_outputs(
    now: datetime | None = None,
    direction: float = 0.8,
    confidence: float = 0.75,
    regime: str = "trending",
    trend_strength: float = 0.7,
    vol_forecast: float = 150.0,
    vol_confidence: float = 0.8,
) -> tuple[DirectionOutput, RegimeOutput, VolatilityOutput, datetime]:
    now = now or datetime(2024, 6, 1, 12, 0)
    d = DirectionOutput(
        name="direction", version="d-v1", updated_at=now,
        direction=direction, confidence=confidence,
    )
    r = RegimeOutput(
        name="regime", version="r-v1", updated_at=now,
        regime=regime, trend_strength=trend_strength,
    )
    v = VolatilityOutput(
        name="volatility", version="v-v1", updated_at=now,
        vol_forecast=vol_forecast, confidence=vol_confidence,
    )
    return d, r, v, now


class TestSignalCombiner:
    def test_basic_combination(self) -> None:
        combiner = SignalCombiner()
        d, r, v, now = _make_outputs()
        signal = combiner.combine(d, r, v, now=now)
        assert signal.direction == 0.8
        assert signal.direction_conf == 0.75
        assert signal.regime == "trending"
        assert signal.trend_strength == 0.7
        assert signal.vol_forecast == 150.0
        assert signal.confidence_valid is True

    def test_stale_direction_invalidates(self) -> None:
        combiner = SignalCombiner(direction_freshness=timedelta(hours=1))
        now = datetime(2024, 6, 1, 12, 0)
        stale = now - timedelta(hours=2)
        d = DirectionOutput(
            name="direction", version="d-v1", updated_at=stale,
            direction=0.8, confidence=0.75,
        )
        r = RegimeOutput(name="regime", version="r-v1", updated_at=now, regime="trending")
        v = VolatilityOutput(name="volatility", version="v-v1", updated_at=now)
        signal = combiner.combine(d, r, v, now=now)
        assert signal.confidence_valid is False

    def test_stale_regime_invalidates(self) -> None:
        combiner = SignalCombiner(regime_freshness=timedelta(hours=1))
        now = datetime(2024, 6, 1, 12, 0)
        stale = now - timedelta(hours=2)
        d = DirectionOutput(name="direction", version="d-v1", updated_at=now)
        r = RegimeOutput(name="regime", version="r-v1", updated_at=stale, regime="choppy")
        v = VolatilityOutput(name="volatility", version="v-v1", updated_at=now)
        signal = combiner.combine(d, r, v, now=now)
        assert signal.confidence_valid is False

    def test_stale_volatility_invalidates(self) -> None:
        combiner = SignalCombiner(volatility_freshness=timedelta(hours=1))
        now = datetime(2024, 6, 1, 12, 0)
        stale = now - timedelta(hours=2)
        d = DirectionOutput(name="direction", version="d-v1", updated_at=now)
        r = RegimeOutput(name="regime", version="r-v1", updated_at=now, regime="trending")
        v = VolatilityOutput(name="volatility", version="v-v1", updated_at=stale)
        signal = combiner.combine(d, r, v, now=now)
        assert signal.confidence_valid is False

    def test_version_tagging(self) -> None:
        combiner = SignalCombiner()
        d, r, v, now = _make_outputs()
        signal = combiner.combine(d, r, v, now=now)
        assert "d-v1" in signal.model_version
        assert "r-v1" in signal.model_version
        assert "v-v1" in signal.model_version

    def test_suggested_hints_with_confident_vol(self) -> None:
        combiner = SignalCombiner()
        d, r, v, now = _make_outputs(vol_forecast=200.0, vol_confidence=0.8)
        signal = combiner.combine(d, r, v, now=now)
        assert signal.suggested_stop_atr_mult is not None
        assert signal.suggested_add_atr_mult is not None
        assert signal.suggested_stop_atr_mult > 0
        assert signal.suggested_add_atr_mult > 0

    def test_no_hints_with_low_confidence_vol(self) -> None:
        combiner = SignalCombiner()
        d, r, v, now = _make_outputs(vol_confidence=0.3)
        signal = combiner.combine(d, r, v, now=now)
        assert signal.suggested_stop_atr_mult is None
        assert signal.suggested_add_atr_mult is None

    def test_all_fresh_models_valid(self) -> None:
        combiner = SignalCombiner(
            direction_freshness=timedelta(hours=24),
            regime_freshness=timedelta(hours=24),
            volatility_freshness=timedelta(hours=24),
        )
        d, r, v, now = _make_outputs()
        signal = combiner.combine(d, r, v, now=now)
        assert signal.confidence_valid is True
