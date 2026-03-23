## Purpose

Implement market-specific adapters that translate broker-specific details (margin rules, contract specs, trading hours, fees) into the standardized types the core engine understands. One adapter per market: TaifexAdapter (TW futures), CryptoAdapter (Binance perpetuals), USEquityAdapter (Schwab equities).

## Requirements

### Requirement: BaseAdapter interface
The system SHALL define an abstract `BaseAdapter` class that all market adapters must implement.

```python
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
```

#### Scenario: All methods required
- **WHEN** a class extends `BaseAdapter` without implementing all abstract methods
- **THEN** instantiation SHALL raise `TypeError`

#### Scenario: Adapter only imports core types
- **WHEN** an adapter module is loaded
- **THEN** it SHALL only import from `core.types` — never from `position_engine`, `prediction/`, or `execution/`

#### Scenario: Default implementation returns None
- **WHEN** `account_info()` is called on a `BaseAdapter` subclass that does not override it
- **THEN** it SHALL return `None`

### Requirement: TaifexAdapter
The system SHALL provide a `TaifexAdapter` for TW Futures (TAIFEX) via Sinopac (shioaji). All contract specs, margins, fees, and trading hours SHALL be loaded from adapter configuration (TOML), not hardcoded in source. **Margin values SHALL additionally be resolvable from the database (latest MarginSnapshot), with static TOML config as fallback.**

The `TaifexAdapter` SHALL also implement `account_info()` returning TAIFEX-specific metadata, and SHALL provide a `get_point_value(symbol: str) -> float` method for broker gateway P&L calculations.

#### Scenario: Contract specs from config
- **WHEN** `get_contract_specs()` is called for any supported symbol
- **THEN** it SHALL return `ContractSpecs` with values loaded from the adapter's TOML config file

#### Scenario: Margin resolution with DB priority
- **WHEN** `get_contract_specs()` is called and a MarginSnapshot exists in the database for the symbol
- **THEN** `margin_initial` and `margin_maintenance` SHALL use the latest DB values instead of static config

#### Scenario: Margin fallback to static config
- **WHEN** `get_contract_specs()` is called but no MarginSnapshot exists in the database
- **THEN** `margin_initial` and `margin_maintenance` SHALL use values from `config/taifex.toml`

#### Scenario: Lot translation from config
- **WHEN** `translate_lots()` is called with abstract lot types
- **THEN** it SHALL map abstract types to concrete contract codes using mappings from config

#### Scenario: Snapshot conversion
- **WHEN** `to_snapshot()` is called with raw shioaji bar data
- **THEN** it SHALL return a valid `MarketSnapshot` with daily ATR computed and contract specs populated (using DB margins when available)

#### Scenario: Trading hours from config
- **WHEN** `get_trading_hours()` is called
- **THEN** it SHALL return session definitions loaded from config (day session + night session in local timezone)

#### Scenario: Fee estimation from config
- **WHEN** `estimate_fee()` is called
- **THEN** it SHALL calculate fees using commission and tax rate values from config

#### Scenario: Feature plugin registration
- **WHEN** TaifexAdapter is constructed
- **THEN** it SHALL register a TAIFEX feature plugin with the Feature Store for computing market-specific features (institutional net position, P/C ratio, volatility index, days to settlement, margin adjustment events)

#### Scenario: TaifexAdapter returns TAIFEX account info
- **WHEN** `account_info()` is called on `TaifexAdapter`
- **THEN** it SHALL return a dict with keys: `exchange` ("TAIFEX"), `currency` ("TWD"), `session_type` ("futures"), and `contract_multipliers` mapping contract symbols to their point values

#### Scenario: TX contract point value
- **WHEN** `get_point_value("TX")` is called
- **THEN** it SHALL return `200.0` (TWD 200 per index point for TAIEX futures)

#### Scenario: MTX contract point value
- **WHEN** `get_point_value("MTX")` is called
- **THEN** it SHALL return `50.0` (TWD 50 per index point for Mini-TAIEX)

#### Scenario: Unknown symbol returns default
- **WHEN** `get_point_value("UNKNOWN")` is called
- **THEN** it SHALL return `1.0` as a safe default and log a warning

### Requirement: CryptoAdapter
The system SHALL provide a `CryptoAdapter` for crypto perpetuals via Binance (python-binance). (Phase 3)

#### Scenario: Dynamic margin calculation
- **WHEN** `calc_margin()` is called for BTC perpetual
- **THEN** it SHALL compute margin based on current price, leverage, and position size (margin is dynamic, not fixed)

#### Scenario: Liquidation price computation
- **WHEN** `calc_liquidation_price()` is called with entry, leverage, and direction
- **THEN** it SHALL return the exact liquidation price accounting for maintenance margin requirements

#### Scenario: Funding rate tracking
- **WHEN** the adapter is active on a perpetual contract
- **THEN** it SHALL track and expose the current and historical funding rates for cost estimation

#### Scenario: 24/7 trading hours
- **WHEN** `get_trading_hours()` is called
- **THEN** it SHALL indicate continuous 24/7 trading with no session boundaries

#### Scenario: Lot translation for crypto
- **WHEN** `translate_lots()` is called
- **THEN** it SHALL map abstract lot types to fractional BTC/ETH quantities (e.g., `min_lot=0.001`)

### Requirement: USEquityAdapter
The system SHALL provide a `USEquityAdapter` for US equities via Schwab (schwab-py). (Phase 4)

#### Scenario: RegT margin rules
- **WHEN** `calc_margin()` is called
- **THEN** it SHALL apply Regulation T margin rules (50% initial margin for margin accounts, 100% for cash accounts)

#### Scenario: PDT rule handling
- **WHEN** account equity is below $25,000
- **THEN** the adapter SHALL enforce Pattern Day Trader restrictions (max 3 day trades per 5 business days)

#### Scenario: Market hours
- **WHEN** `get_trading_hours()` is called
- **THEN** it SHALL return 09:30–16:00 ET for regular session, with optional pre-market (04:00–09:30) and after-hours (16:00–20:00)

#### Scenario: Share-based lots
- **WHEN** `translate_lots()` is called for equities
- **THEN** it SHALL map to share quantities directly (no "large/small" contract split — just share lots with lower leverage)

### Requirement: Liquidation price abstraction
Each adapter SHALL implement `calc_liquidation_price()` returning `None` for markets without forced liquidation (e.g., equities in cash accounts) or the exact liquidation price for leveraged products.

#### Scenario: No liquidation for cash equities
- **WHEN** `calc_liquidation_price()` is called on a cash equity position
- **THEN** it SHALL return `None`

#### Scenario: Liquidation for futures
- **WHEN** `calc_liquidation_price()` is called on a futures position
- **THEN** it SHALL return the price at which maintenance margin is breached
