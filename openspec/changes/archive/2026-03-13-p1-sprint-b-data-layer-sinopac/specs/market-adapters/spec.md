## MODIFIED Requirements

### Requirement: TaifexAdapter
The system SHALL provide a `TaifexAdapter` for TW Futures (TAIFEX) via Sinopac (shioaji). All contract specs, margins, fees, and trading hours SHALL be loaded from adapter configuration (TOML), not hardcoded in source.

#### Scenario: Contract specs from config
- **WHEN** `get_contract_specs()` is called for any supported symbol
- **THEN** it SHALL return `ContractSpecs` with values loaded from the adapter's TOML config file

#### Scenario: Lot translation from config
- **WHEN** `translate_lots()` is called with abstract lot types
- **THEN** it SHALL map abstract types to concrete contract codes using mappings from config

#### Scenario: Snapshot conversion
- **WHEN** `to_snapshot()` is called with raw shioaji bar data
- **THEN** it SHALL return a valid `MarketSnapshot` with daily ATR computed and contract specs populated from config

#### Scenario: Trading hours from config
- **WHEN** `get_trading_hours()` is called
- **THEN** it SHALL return session definitions loaded from config (day session + night session in local timezone)

#### Scenario: Fee estimation from config
- **WHEN** `estimate_fee()` is called
- **THEN** it SHALL calculate fees using commission and tax rate values from config

#### Scenario: Feature plugin registration
- **WHEN** TaifexAdapter is constructed
- **THEN** it SHALL register a TAIFEX feature plugin with the Feature Store for computing market-specific features (institutional net position, P/C ratio, volatility index, days to settlement, margin adjustment events)
