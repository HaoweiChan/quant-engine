import uuid
from enum import Enum
from datetime import datetime, timedelta, timezone

_TAIPEI_TZ = timezone(timedelta(hours=8))
from typing import Any, Literal
from dataclasses import dataclass, field


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

    @property
    def contract_type(self) -> str:
        """Primary lot type label (e.g. 'large', 'mini', 'micro')."""
        return next(iter(self.lot_types))


@dataclass
class MarketSnapshot:
    price: float
    atr: dict[str, float]
    timestamp: datetime
    margin_per_unit: float
    point_value: float
    min_lot: float
    contract_specs: ContractSpecs
    volume: float = 0.0
    bar_high: float | None = None
    bar_low: float | None = None

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
    reason: str  # "entry" | "add_level_2" | "stop_loss" | "trailing_stop" | "circuit_breaker" | "disaster_stop"
    metadata: dict[str, Any] = field(default_factory=dict)
    parent_position_id: str | None = None
    order_class: Literal["standard", "disaster_stop", "algo_exit"] = "standard"

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
    position_id: str = field(default_factory=lambda: str(uuid.uuid4()))

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
    lot_schedule: list[list[int]] = field(default_factory=lambda: [[3, 4], [2, 0], [1, 4], [1, 4]])
    stop_atr_mult: float = 1.5
    trail_atr_mult: float = 3.0
    trail_lookback: int = 22
    margin_limit: float = 0.50
    kelly_fraction: float = 0.25
    entry_conf_threshold: float = 0.65
    max_equity_risk_pct: float = 0.02
    long_only_compat_mode: bool = False
    # Generic pyramid support (intraday + swing)
    atr_key: str = "daily"
    gamma: float | None = None
    base_lots: float = 1.0
    internal_atr_len: int = 10

    def __post_init__(self) -> None:
        if self.max_loss <= 0:
            raise ValueError("max_loss must be positive")
        if not (0.0 < self.max_equity_risk_pct <= 1.0):
            raise ValueError("max_equity_risk_pct must be in (0.0, 1.0]")
        if self.gamma is None:
            if len(self.lot_schedule) != self.max_levels:
                n = len(self.lot_schedule)
                raise ValueError(f"lot_schedule length ({n}) must equal max_levels ({self.max_levels})")
        else:
            if not (0.0 < self.gamma < 1.0):
                raise ValueError("gamma must be in (0, 1)")
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
    disaster_atr_mult: float = 4.5
    disaster_stop_enabled: bool = False
    require_account_for_entry: bool = False
    min_hold_lots: float = 0.0

    def __post_init__(self) -> None:
        if self.max_loss <= 0:
            raise ValueError("max_loss must be positive")
        if not (0.0 < self.margin_limit <= 1.0):
            raise ValueError("margin_limit must be in (0.0, 1.0]")
        if self.disaster_atr_mult <= 0:
            raise ValueError("disaster_atr_mult must be positive")


class RiskAction(Enum):
    NORMAL = "normal"
    REDUCE_HALF = "reduce_half"
    HALT_NEW_ENTRIES = "halt_new_entries"
    CLOSE_ALL = "close_all"


class EventType(Enum):
    MARKET = "market"
    SIGNAL = "signal"
    ORDER = "order"
    FILL = "fill"
    RISK = "risk"
    AUDIT = "audit"


@dataclass
class Event:
    event_type: EventType
    timestamp: datetime
    data: Any


@dataclass
class MarketEvent(Event):
    symbol: str = ""
    open_price: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    atr: float = 0.0

    def __post_init__(self) -> None:
        self.event_type = EventType.MARKET


@dataclass
class SignalEvent(Event):
    signal: MarketSignal | None = None

    def __post_init__(self) -> None:
        self.event_type = EventType.SIGNAL


@dataclass
class OrderEvent(Event):
    order: Order | None = None

    def __post_init__(self) -> None:
        self.event_type = EventType.ORDER


@dataclass
class FillEvent(Event):
    fill_price: float = 0.0
    fill_lots: float = 0.0
    side: str = ""
    symbol: str = ""

    def __post_init__(self) -> None:
        self.event_type = EventType.FILL


@dataclass
class RiskEvent(Event):
    action: RiskAction = RiskAction.NORMAL
    reason: str = ""

    def __post_init__(self) -> None:
        self.event_type = EventType.RISK


@dataclass
class AuditRecord:
    sequence_id: int
    timestamp: datetime
    event_type: str
    engine_state_hash: str
    account_state: AccountState
    event_data: dict[str, Any]
    prev_hash: str
    record_hash: str
    git_commit: str | None = None


@dataclass
class AuditConfig:
    enabled: bool = True
    store_backend: str = "sqlite"
    db_path: str = "audit.db"
    retention_days: int = 365
    include_full_account_state: bool = True
    include_git_commit: bool = True


@dataclass
class EventEngineConfig:
    tick_drill_atr_mult: float = 2.0
    tick_drill_enabled: bool = True
    latency_delay_ms: float = 10.0
    max_events_per_bar: int = 1000
    audit_enabled: bool = True


@dataclass(frozen=True)
class InstrumentCostConfig:
    """Per-instrument default transaction cost configuration."""

    slippage_pct: float = 0.1  # 0.1% per side
    commission_per_contract: float = 100.0  # NT$ round-trip
    symbol: str = "TX"

    @property
    def slippage_bps(self) -> float:
        """Convert slippage percentage to basis points."""
        return self.slippage_pct * 10  # 0.1% -> 1.0 bps

    @property
    def commission_bps(self) -> float:
        """Return 0 since we use fixed per-contract commission."""
        return 0.0


INSTRUMENT_COSTS: dict[str, InstrumentCostConfig] = {
    "TX": InstrumentCostConfig(slippage_pct=0.1, commission_per_contract=100.0, symbol="TX"),
    "MTX": InstrumentCostConfig(slippage_pct=0.1, commission_per_contract=40.0, symbol="MTX"),
    "TMF": InstrumentCostConfig(slippage_pct=0.1, commission_per_contract=20.0, symbol="TMF"),
}


def get_instrument_cost_config(symbol: str = "TX") -> InstrumentCostConfig:
    """Look up cost config for a symbol, falling back to TX defaults."""
    if symbol not in INSTRUMENT_COSTS:
        import structlog
        structlog.get_logger().warning("unknown_instrument_cost", symbol=symbol, fallback="TX")
    return INSTRUMENT_COSTS.get(symbol, INSTRUMENT_COSTS["TX"])


@dataclass
class ImpactParams:
    """Parameters for the square-root market impact model."""

    k: float = 1.0
    sigma_source: str = "daily"
    adv_lookback: int = 20
    spread_bps: float = 1.0
    commission_bps: float = 0.0
    commission_fixed_per_contract: float = 0.0
    min_latency_ms: float = 5.0
    max_latency_ms: float = 50.0
    max_adv_participation: float = 0.10
    seed: int | None = None


@dataclass
class OMSConfig:
    """Order Management System configuration."""

    passthrough_threshold_pct: float = 0.01
    default_algorithm: str = "auto"
    twap_default_slices: int = 10
    vwap_lookback_days: int = 20
    pov_participation_rate: float = 0.05
    max_execution_window_minutes: int = 60
    enabled: bool = True


@dataclass
class PreTradeRiskConfig:
    """Pre-trade risk check thresholds."""

    max_gross_exposure_pct: float = 0.80
    max_adv_participation_pct: float = 0.05
    max_beta_absolute: float = 2.0
    max_concentration_pct: float = 0.50
    max_var_pct: float = 0.05
    enabled: bool = True


@dataclass
class PreTradeResult:
    """Result of a pre-trade risk evaluation."""

    approved: bool
    violations: list[str] = field(default_factory=list)
    risk_metrics: dict[str, float] = field(default_factory=dict)


@dataclass
class ChildOrder:
    """A single slice from an OMS decomposition."""

    order: Order
    scheduled_time: datetime
    slice_pct: float


@dataclass
class SlicedOrder:
    """Parent order decomposed into child orders by the OMS."""

    parent_order: Order
    child_orders: list[ChildOrder]
    algorithm: str
    estimated_impact: float
    schedule: list[datetime] = field(default_factory=list)


@dataclass
class PITRecord:
    """Bi-temporal record for point-in-time data integrity."""

    event_time: datetime
    knowledge_time: datetime
    valid_from: datetime
    valid_to: datetime | None = None
    source: str = "exchange"


@dataclass
class StitchedSeries:
    """Continuous futures series with roll-adjusted prices."""

    adjusted_prices: list[float]
    unadjusted_prices: list[float]
    timestamps: list[datetime]
    roll_dates: list[datetime]
    adjustment_factors: list[float]


@dataclass
class VaRResult:
    """Value-at-Risk computation results for 1-day and 10-day horizons."""

    var_99_1d: float
    var_95_1d: float
    var_99_10d: float
    var_95_10d: float
    expected_shortfall_99: float
    position_var: dict[str, float] = field(default_factory=dict)
    correlation_matrix: list[list[float]] | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(_TAIPEI_TZ))
    is_fallback: bool = False


@dataclass
class StressScenario:
    """Configurable stress test scenario for margin / volatility / correlation."""

    name: str
    margin_multiplier: float = 1.0
    volatility_multiplier: float = 1.0
    correlation_override: float | None = None


@dataclass
class StressResult:
    """Outcome of running a stress scenario against the portfolio."""

    scenario: StressScenario
    stressed_var: float
    margin_call: bool
    shortfall: float = 0.0
    details: dict[str, float] = field(default_factory=dict)
