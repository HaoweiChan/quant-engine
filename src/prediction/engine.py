"""PredictionEngine facade: orchestrates feature pipeline, sub-models, and combiner."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
import numpy.typing as npt
import polars as pl
import structlog

from src.core.types import MarketSignal
from src.prediction.combiner import (
    DirectionOutput,
    RegimeOutput,
    SignalCombiner,
    VolatilityOutput,
)
from src.prediction.direction import DirectionClassifier
from src.prediction.features import clean_features
from src.prediction.regime import RegimeClassifier
from src.prediction.volatility import VolatilityForecaster, VolForecast

logger = structlog.get_logger(__name__)

DEFAULT_REGIME_FEATURES = ("returns", "volatility_20", "volume_ratio")


class PredictionEngine:
    """Orchestrates feature pipeline -> sub-models -> combiner to produce MarketSignal."""

    def __init__(
        self,
        direction: DirectionClassifier,
        regime: RegimeClassifier,
        volatility: VolatilityForecaster,
        combiner: SignalCombiner | None = None,
        feature_cols: list[str] | None = None,
        regime_feature_cols: list[str] | None = None,
    ) -> None:
        self._direction = direction
        self._regime = regime
        self._volatility = volatility
        self._combiner = combiner or SignalCombiner()
        self._feature_cols = feature_cols or []
        self._regime_feature_cols = regime_feature_cols or list(DEFAULT_REGIME_FEATURES)
        self._dir_version = "dir-v1"
        self._reg_version = "reg-v1"
        self._vol_version = "vol-v1"
        self._training_date: str | None = None
        self._training_metrics: dict[str, Any] = {}

    def predict(
        self,
        features: pl.DataFrame,
        current_price: float,
        atr_daily: float | None = None,
        now: datetime | None = None,
    ) -> MarketSignal:
        """Produce a single MarketSignal from the latest feature row."""
        now = now or datetime.now()
        cleaned, _ = clean_features(features)
        if cleaned.is_empty():
            return self._fallback_signal(now)

        last_row = cleaned.tail(1)

        dir_x = self._extract_direction_features(last_row)
        dirs, confs = self._direction.predict_direction(dir_x)
        direction_out = DirectionOutput(
            name="direction", version=self._dir_version,
            updated_at=now, direction=float(dirs[0]), confidence=float(confs[0]),
        )

        regime_x = self._extract_regime_features(last_row)
        regimes = self._regime.predict_regimes(regime_x)
        strengths = self._regime.trend_strength(regime_x)
        regime_out = RegimeOutput(
            name="regime", version=self._reg_version,
            updated_at=now, regime=regimes[0], trend_strength=float(strengths[0]),
        )

        vol_fcast = self._run_vol_forecast(current_price, atr_daily)
        volatility_out = VolatilityOutput(
            name="volatility", version=self._vol_version,
            updated_at=now, vol_forecast=vol_fcast.price_point_vol,
            confidence=0.8 if vol_fcast.is_valid else 0.0,
        )

        return self._combiner.combine(direction_out, regime_out, volatility_out, now=now)

    def predict_batch(
        self,
        features: pl.DataFrame,
        prices: pl.Series,
        atr_daily: pl.Series | None = None,
        timestamps: pl.Series | None = None,
    ) -> list[MarketSignal]:
        """Efficient batch prediction for backtesting. Returns N signals for N rows."""
        cleaned, _ = clean_features(features)
        n = len(cleaned)
        if n == 0:
            return []

        dir_x = self._extract_direction_features(cleaned)
        dirs, confs = self._direction.predict_direction(dir_x)

        regime_x = self._extract_regime_features(cleaned)
        regimes = self._regime.predict_regimes(regime_x)
        strengths = self._regime.trend_strength(regime_x)

        signals: list[MarketSignal] = []
        for i in range(n):
            ts: Any = (
                timestamps[i] if timestamps is not None
                else cleaned["timestamp"][i] if "timestamp" in cleaned.columns
                else datetime.now()
            )
            now_ts: datetime = ts if isinstance(ts, datetime) else datetime.now()
            price = float(prices[i])
            atr = float(atr_daily[i]) if atr_daily is not None else None

            vol_fcast = self._run_vol_forecast(price, atr)

            direction_out = DirectionOutput(
                name="direction", version=self._dir_version,
                updated_at=now_ts, direction=float(dirs[i]), confidence=float(confs[i]),
            )
            regime_out = RegimeOutput(
                name="regime", version=self._reg_version,
                updated_at=now_ts, regime=regimes[i], trend_strength=float(strengths[i]),
            )
            volatility_out = VolatilityOutput(
                name="volatility", version=self._vol_version,
                updated_at=now_ts, vol_forecast=vol_fcast.price_point_vol,
                confidence=0.8 if vol_fcast.is_valid else 0.0,
            )
            signals.append(
                self._combiner.combine(direction_out, regime_out, volatility_out, now=now_ts)
            )
        return signals

    def get_model_info(self) -> dict[str, Any]:
        return {
            "direction_version": self._dir_version,
            "regime_version": self._reg_version,
            "volatility_version": self._vol_version,
            "training_date": self._training_date,
            "metrics": dict(self._training_metrics),
            "feature_cols": list(self._feature_cols),
            "regime_feature_cols": list(self._regime_feature_cols),
        }

    def set_versions(
        self, direction: str = "dir-v1", regime: str = "reg-v1", volatility: str = "vol-v1",
    ) -> None:
        self._dir_version = direction
        self._reg_version = regime
        self._vol_version = volatility

    def set_training_info(self, date: str, metrics: dict[str, Any]) -> None:
        self._training_date = date
        self._training_metrics = metrics

    def _extract_direction_features(self, df: pl.DataFrame) -> npt.NDArray[np.float64]:
        cols = self._feature_cols or [
            c for c in df.columns
            if c not in ("timestamp", "label", "forward_return")
            and df[c].dtype in (pl.Float64, pl.Float32, pl.Int64, pl.Int32)
        ]
        return df.select(cols).to_numpy().astype(np.float64)

    def _extract_regime_features(self, df: pl.DataFrame) -> npt.NDArray[np.float64]:
        available = [c for c in self._regime_feature_cols if c in df.columns]
        if not available:
            numeric = [
                c for c in df.columns
                if df[c].dtype in (pl.Float64, pl.Float32) and c != "timestamp"
            ]
            available = numeric[:3]
        if not available:
            return np.zeros((len(df), 1), dtype=np.float64)
        return df.select(available).to_numpy().astype(np.float64)

    def _run_vol_forecast(self, price: float, atr_daily: float | None) -> VolForecast:
        try:
            return self._volatility.forecast(price, atr_daily)
        except Exception:
            logger.warning("Volatility forecast failed, using fallback")
            return VolForecast(
                annualized_vol=0.0, n_day_vol=0.0, price_point_vol=0.0,
                horizon=self._volatility.horizon,
            )

    @staticmethod
    def _fallback_signal(now: datetime) -> MarketSignal:
        return MarketSignal(
            timestamp=now, direction=0.0, direction_conf=0.0,
            regime="uncertain", trend_strength=0.0, vol_forecast=0.0,
            suggested_stop_atr_mult=None, suggested_add_atr_mult=None,
            model_version="fallback", confidence_valid=False,
        )
