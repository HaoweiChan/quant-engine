"""TAIFEX-specific feature plugin for institutional data and market indicators."""
from __future__ import annotations

from typing import Any, Protocol

import polars as pl

from src.data.feature_plugins.base import FeaturePlugin


class TaifexDataSource(Protocol):
    """Protocol for fetching TAIFEX-specific market data."""

    def get_institutional_net(self, dates: list[Any]) -> list[float]: ...
    def get_put_call_ratio(self, dates: list[Any]) -> list[float]: ...
    def get_volatility_index(self, dates: list[Any]) -> list[float]: ...
    def get_days_to_settlement(self, dates: list[Any]) -> list[int]: ...
    def get_margin_events(self, dates: list[Any]) -> list[int]: ...


class NullTaifexDataSource:
    """Default stub that returns zeros -- replace with real data source."""

    def get_institutional_net(self, dates: list[Any]) -> list[float]:
        return [0.0] * len(dates)

    def get_put_call_ratio(self, dates: list[Any]) -> list[float]:
        return [1.0] * len(dates)

    def get_volatility_index(self, dates: list[Any]) -> list[float]:
        return [15.0] * len(dates)

    def get_days_to_settlement(self, dates: list[Any]) -> list[int]:
        return [10] * len(dates)

    def get_margin_events(self, dates: list[Any]) -> list[int]:
        return [0] * len(dates)


class TaifexFeaturePlugin(FeaturePlugin):
    def __init__(self, data_source: TaifexDataSource | None = None) -> None:
        self._source: TaifexDataSource = data_source or NullTaifexDataSource()

    def required_columns(self) -> list[str]:
        return ["timestamp"]

    def compute(self, bars: pl.DataFrame) -> pl.DataFrame:
        dates = bars["timestamp"].to_list()
        return pl.DataFrame({
            "institutional_net": self._source.get_institutional_net(dates),
            "put_call_ratio": self._source.get_put_call_ratio(dates),
            "volatility_index": self._source.get_volatility_index(dates),
            "days_to_settlement": self._source.get_days_to_settlement(dates),
            "margin_events": self._source.get_margin_events(dates),
        })
