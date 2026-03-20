"""GARCH(1,1) volatility forecaster with t-distributed errors."""
from __future__ import annotations

import pickle
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class VolForecast:
    annualized_vol: float
    n_day_vol: float
    price_point_vol: float
    horizon: int

    @property
    def is_valid(self) -> bool:
        return self.price_point_vol > 0 and bool(np.isfinite(self.price_point_vol))


@dataclass
class ForecastValidation:
    mae: float
    rmse: float
    forecast_mean: float
    realized_mean: float
    n_samples: int


class VolatilityForecaster:
    """GARCH(1,1) with t-distributed errors for N-day ahead volatility forecasting."""

    def __init__(self, horizon: int = 5, p: int = 1, q: int = 1) -> None:
        self.horizon = horizon
        self.p = p
        self.q = q
        self._model_result: Any = None
        self._last_returns: npt.NDArray[np.float64] | None = None

    def train(self, returns: npt.NDArray[np.float64]) -> dict[str, float]:
        """Fit GARCH(p,q) on daily returns."""
        from arch import arch_model

        scaled: npt.NDArray[np.float64]
        if float(np.abs(returns).mean()) < 1:
            scaled = (returns * 100).astype(np.float64)
        else:
            scaled = returns.astype(np.float64)
        self._last_returns = scaled

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = arch_model(scaled, vol="GARCH", p=self.p, q=self.q, dist="t")
            self._model_result = model.fit(disp="off")

        result: dict[str, float] = {str(k): float(v) for k, v in self._model_result.params.items()}
        logger.info("garch_fitted", params=result)
        return result

    def forecast(self, current_price: float, atr_daily: float | None = None) -> VolForecast:
        """Produce N-day ahead volatility forecast in price points."""
        if self._model_result is None:
            raise RuntimeError("Model not trained")

        fcast: Any = self._model_result.forecast(horizon=self.horizon)
        variance_array: Any = fcast.variance.values[-1]
        mean_daily_var = float(np.mean(variance_array))
        daily_vol_decimal = np.sqrt(mean_daily_var) / 100.0
        annualized_vol = daily_vol_decimal * np.sqrt(252)
        n_day_vol = daily_vol_decimal * np.sqrt(self.horizon)

        price_point = current_price * n_day_vol
        if atr_daily is not None:
            atr_n_day = atr_daily * np.sqrt(self.horizon)
            price_point = 0.7 * price_point + 0.3 * atr_n_day

        return VolForecast(
            annualized_vol=float(annualized_vol),
            n_day_vol=float(n_day_vol),
            price_point_vol=float(price_point),
            horizon=self.horizon,
        )

    def validate(
        self,
        returns: npt.NDArray[np.float64],
        current_prices: npt.NDArray[np.float64],
    ) -> ForecastValidation:
        """Compare forecasted vs realized volatility on validation data."""
        from arch import arch_model

        n = len(returns)
        min_window = 100
        forecasts: list[float] = []
        realized: list[float] = []

        for t in range(min_window, n - self.horizon):
            raw = returns[:t]
            window: npt.NDArray[np.float64]
            if float(np.abs(raw).mean()) < 1:
                window = (raw * 100).astype(np.float64)
            else:
                window = raw.astype(np.float64)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try:
                    m = arch_model(window, vol="GARCH", p=self.p, q=self.q, dist="t")
                    res = m.fit(disp="off")
                    fc: Any = res.forecast(horizon=self.horizon)
                    var_arr: Any = fc.variance.values[-1]
                    daily_vol = float(np.sqrt(np.mean(var_arr))) / 100.0
                except Exception:
                    continue

            price = float(current_prices[t])
            fc_vol = price * daily_vol * np.sqrt(self.horizon)
            forecasts.append(float(fc_vol))

            future_ret = returns[t:t + self.horizon]
            rv = float(np.std(future_ret)) * np.sqrt(self.horizon) * price
            realized.append(float(rv))

        fc_arr = np.array(forecasts)
        rv_arr = np.array(realized)
        errors = fc_arr - rv_arr
        return ForecastValidation(
            mae=float(np.mean(np.abs(errors))),
            rmse=float(np.sqrt(np.mean(errors ** 2))),
            forecast_mean=float(np.mean(fc_arr)),
            realized_mean=float(np.mean(rv_arr)),
            n_samples=len(forecasts),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({
                "model_result": self._model_result,
                "last_returns": self._last_returns,
                "horizon": self.horizon, "p": self.p, "q": self.q,
            }, f)

    @classmethod
    def load(cls, path: Path) -> VolatilityForecaster:
        with open(path, "rb") as f:
            data: dict[str, Any] = pickle.load(f)  # noqa: S301
        obj = cls(horizon=data["horizon"], p=data["p"], q=data["q"])
        obj._model_result = data["model_result"]
        obj._last_returns = data["last_returns"]
        return obj
