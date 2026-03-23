from abc import ABC, abstractmethod
from typing import Any

from src.core.types import ContractSpecs, MarketSnapshot, Order, TradingHours


class BaseAdapter(ABC):
    @abstractmethod
    def to_snapshot(self, raw_data: Any) -> MarketSnapshot: ...

    @abstractmethod
    def calc_margin(self, contract_type: str, lots: float) -> float: ...

    @abstractmethod
    def calc_liquidation_price(
        self, entry: float, leverage: float, direction: str
    ) -> float | None: ...

    @abstractmethod
    def get_trading_hours(self) -> TradingHours: ...

    @abstractmethod
    def get_contract_specs(self, symbol: str) -> ContractSpecs: ...

    @abstractmethod
    def estimate_fee(self, order: Order) -> float: ...

    @abstractmethod
    def translate_lots(
        self, abstract_lots: list[tuple[str, float]]
    ) -> list[tuple[str, float]]: ...

    def account_info(self) -> dict[str, Any] | None:
        """Return broker-specific account metadata. Override in subclass."""
        return None
