from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal


@dataclass
class TradingHours:
    open_time: str
    close_time: str
    timezone: str
    break_start: str | None = None
    break_end: str | None = None


@dataclass
class ContractSpecs:
    symbol: str
    exchange: str
    currency: str
    point_value: float
    margin_initial: float
    margin_maintenance: float
    min_tick: float
    trading_hours: TradingHours
    fee_per_contract: float
    tax_rate: float
    lot_types: dict[str, float]

    def __post_init__(self) -> None:
        if self.margin_initial <= 0:
            raise ValueError("margin_initial must be positive")
        if self.margin_maintenance <= 0:
            raise ValueError("margin_maintenance must be positive")
        if not self.lot_types:
            raise ValueError("lot_types must contain at least one entry")


@dataclass
class MarketSnapshot:
    price: float
    atr: dict[str, float]
    timestamp: datetime
    margin_per_unit: float
    point_value: float
    min_lot: float
    contract_specs: ContractSpecs

    def __post_init__(self) -> None:
        if self.price <= 0:
            raise ValueError("price must be positive")
        if "daily" not in self.atr:
            raise ValueError("atr must contain a 'daily' key")


VALID_REGIMES = frozenset({"trending", "choppy", "volatile", "uncertain"})


@dataclass
class MarketSignal:
    timestamp: datetime
    direction: float
    direction_conf: float
    regime: str
    trend_strength: float
    vol_forecast: float
    suggested_stop_atr_mult: float | None
    suggested_add_atr_mult: float | None
    model_version: str
    confidence_valid: bool

    def __post_init__(self) -> None:
        if not (-1.0 <= self.direction <= 1.0):
            raise ValueError("direction must be in [-1, 1]")
        if not (0.0 <= self.direction_conf <= 1.0):
            raise ValueError("direction_conf must be in [0, 1]")
        if self.regime not in VALID_REGIMES:
            raise ValueError(f"regime must be one of {VALID_REGIMES}")
        if not (0.0 <= self.trend_strength <= 1.0):
            raise ValueError("trend_strength must be in [0, 1]")


@dataclass
class Order:
    order_type: str
    side: str
    symbol: str
    contract_type: str
    lots: float
    price: float | None
    stop_price: float | None
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.lots <= 0:
            raise ValueError("lots must be positive")
        if self.order_type == "stop" and self.stop_price is None:
            raise ValueError("stop_price is required for stop orders")
        if self.order_type == "market" and self.price is not None:
            raise ValueError("price must be None for market orders")


@dataclass
class Position:
    entry_price: float
    lots: float
    contract_type: str
    stop_level: float
    pyramid_level: int
    entry_timestamp: datetime
    direction: Literal["long", "short"] = "long"

    def __post_init__(self) -> None:
        if self.stop_level is None:
            raise ValueError("stop_level must not be None")
        if self.direction not in ("long", "short"):
            raise ValueError("direction must be 'long' or 'short'")


@dataclass
class EngineState:
    positions: tuple[Position, ...]
    pyramid_level: int
    mode: str
    total_unrealized_pnl: float


@dataclass
class AccountState:
    equity: float
    unrealized_pnl: float
    realized_pnl: float
    margin_used: float
    margin_available: float
    margin_ratio: float
    drawdown_pct: float
    positions: list[Position]
    timestamp: datetime

    def __post_init__(self) -> None:
        if not (0.0 <= self.drawdown_pct <= 1.0):
            raise ValueError("drawdown_pct must be in [0, 1]")


@dataclass
class PyramidConfig:
    max_loss: float
    max_levels: int = 4
    add_trigger_atr: list[float] = field(default_factory=lambda: [4.0, 8.0, 12.0])
    lot_schedule: list[list[int]] = field(
        default_factory=lambda: [[3, 4], [2, 0], [1, 4], [1, 4]]
    )
    stop_atr_mult: float = 1.5
    trail_atr_mult: float = 3.0
    trail_lookback: int = 22
    margin_limit: float = 0.50
    kelly_fraction: float = 0.25
    entry_conf_threshold: float = 0.65

    def __post_init__(self) -> None:
        if self.max_loss <= 0:
            raise ValueError("max_loss must be positive")
        if len(self.lot_schedule) != self.max_levels:
            n = len(self.lot_schedule)
            raise ValueError(
                f"lot_schedule length ({n}) must equal max_levels ({self.max_levels})"
            )
        if len(self.add_trigger_atr) != self.max_levels - 1:
            n = len(self.add_trigger_atr)
            raise ValueError(
                f"add_trigger_atr length ({n}) must equal max_levels - 1 ({self.max_levels - 1})"
            )


@dataclass
class EntryDecision:
    lots: float
    contract_type: str
    initial_stop: float
    direction: Literal["long", "short"]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.lots <= 0:
            raise ValueError("lots must be positive")
        if self.direction not in ("long", "short"):
            raise ValueError("direction must be 'long' or 'short'")


@dataclass
class AddDecision:
    lots: float
    contract_type: str
    move_existing_to_breakeven: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.lots <= 0:
            raise ValueError("lots must be positive")


@dataclass
class EngineConfig:
    max_loss: float
    margin_limit: float = 0.50
    trail_lookback: int = 22

    def __post_init__(self) -> None:
        if self.max_loss <= 0:
            raise ValueError("max_loss must be positive")
        if not (0.0 < self.margin_limit <= 1.0):
            raise ValueError("margin_limit must be in (0.0, 1.0]")


class RiskAction(Enum):
    NORMAL = "normal"
    REDUCE_HALF = "reduce_half"
    HALT_NEW_ENTRIES = "halt_new_entries"
    CLOSE_ALL = "close_all"
