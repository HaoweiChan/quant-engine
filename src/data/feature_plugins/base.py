from abc import ABC, abstractmethod

import polars as pl


class FeaturePlugin(ABC):
    @abstractmethod
    def compute(self, bars: pl.DataFrame) -> pl.DataFrame: ...

    @abstractmethod
    def required_columns(self) -> list[str]: ...
