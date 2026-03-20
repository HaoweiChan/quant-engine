## 1. Sinopac Connector (`quant_engine/data/connector.py`)

- [x] 1.1 Implement shioaji wrapper class with credential loading from environment variables — acceptance: login succeeds with valid creds, clear error on invalid
- [x] 1.2 Implement session management: auto-reconnect on expiry, configurable retry with backoff — acceptance: session recovers after simulated disconnect
- [x] 1.3 Implement historical daily OHLCV fetch for configurable symbols — acceptance: returns polars DataFrame with correct schema (timestamp, open, high, low, close, volume)
- [x] 1.4 Implement historical minute OHLCV fetch — acceptance: returns minute-level data with same schema
- [x] 1.5 Implement data validation: detect gaps, nulls, outliers — acceptance: validation report flags known issues in test data
- [x] 1.6 Implement rate limit handling: backoff and retry without crashing — acceptance: connector survives simulated rate limit response

## 2. Bar Builder (`quant_engine/data/bar_builder.py`)

- [x] 2.1 Implement minute → 5m bar aggregation — acceptance: correct OHLCV aggregation verified against known data
- [x] 2.2 Implement minute → 1H bar aggregation — acceptance: correct OHLCV aggregation
- [x] 2.3 Implement minute → 4H bar aggregation — acceptance: correct OHLCV aggregation
- [x] 2.4 Implement minute → daily bar aggregation — acceptance: correct OHLCV aggregation
- [x] 2.5 Implement multi-timeframe ATR(14) computation: compute ATR at each timeframe simultaneously — acceptance: ATR dict contains keys for all configured timeframes
- [x] 2.6 Implement session gap handling: use adapter trading hours to correctly bound bar aggregation windows — acceptance: no spurious bars produced across session gaps with TAIFEX test data

## 3. Feature Store (`quant_engine/data/feature_store.py`)

- [x] 3.1 Implement standard indicator computation via pandas-ta: RSI(14), MACD(12,26,9), Bollinger(20,2), SMA(20,50,200), ATR(14), ADX(14), Stochastic(14,3) — acceptance: values match pandas-ta output on reference data
- [x] 3.2 Implement feature plugin interface (`FeaturePlugin` ABC) with `compute()` and `required_columns()` — acceptance: ABC enforces method implementation
- [x] 3.3 Implement plugin registration and invocation: feature store accepts plugins and calls `compute()` during feature generation — acceptance: custom plugin output merged with standard indicators
- [x] 3.4 Implement plugin error isolation: exception in plugin logged, standard features still produced — acceptance: graceful degradation on plugin failure
- [x] 3.5 Implement parquet storage: write/read historical features with date-range partitioning — acceptance: round-trip preserves all values, predicate pushdown works for date filtering
- [x] 3.6 Implement incremental feature update: append new features without recomputing history — acceptance: only new bars trigger computation
- [x] 3.7 Implement in-memory LRU cache: cache recently computed features, invalidate on new bar data — acceptance: cache hit avoids disk I/O, cache miss falls through to parquet

## 4. TAIFEX Feature Plugin (`quant_engine/data/feature_plugins/taifex.py`)

- [x] 4.1 Implement TAIFEX feature plugin: institutional futures net position, put/call ratio, volatility index, days to settlement, margin adjustment events — acceptance: plugin produces all 5 feature columns
- [x] 4.2 Implement data source integration for TAIFEX-specific features (TWSE/TAIFEX open data or shioaji) — acceptance: features populated from real or mock data source

## 5. TaifexAdapter (`quant_engine/adapters/taifex.py`)

- [x] 5.1 Create `config/taifex.toml` with contract specs (TX, MTX, TMF), margins, tick sizes, fees, tax rates, trading hours — acceptance: all values loadable by adapter
- [x] 5.2 Implement TaifexAdapter extending BaseAdapter with config loading from TOML — acceptance: all abstract methods implemented, adapter constructs successfully
- [x] 5.3 Implement `get_contract_specs()`: load from TOML config — acceptance: returns correct ContractSpecs for TX, MTX, TMF
- [x] 5.4 Implement `to_snapshot()`: raw shioaji bar → MarketSnapshot with ATR from bar builder — acceptance: valid snapshot with all fields populated
- [x] 5.5 Implement `translate_lots()`: abstract lot types → concrete contract codes from config — acceptance: mapping matches config
- [x] 5.6 Implement `get_trading_hours()`: session definitions from config — acceptance: returns correct day + night session times
- [x] 5.7 Implement `estimate_fee()`: commission + tax from config values — acceptance: fee matches manual calculation
- [x] 5.8 Implement `calc_margin()` and `calc_liquidation_price()` — acceptance: margin calculation matches exchange rules
- [x] 5.9 Register TAIFEX feature plugin with feature store on adapter construction — acceptance: plugin registered and callable

## 6. Database Layer (`quant_engine/data/db.py`)

- [x] 6.1 Define SQLAlchemy models for trades, signals, positions, account snapshots — acceptance: models create tables successfully
- [x] 6.2 Implement SQLite backend for development — acceptance: CRUD operations work with zero-config SQLite
- [x] 6.3 Implement PostgreSQL backend support via connection string swap — acceptance: same operations work against PostgreSQL

## 7. Tests

- [x] 7.1 Connector tests with mock shioaji responses: login, fetch, error handling, rate limiting — acceptance: all connector behaviors verified without real API
- [x] 7.2 Bar builder tests: verify aggregation correctness on known minute data, verify session gap handling — acceptance: output matches hand-computed expected bars
- [x] 7.3 Feature store tests: verify standard indicators against pandas-ta reference, verify plugin integration, verify parquet round-trip, verify cache behavior — acceptance: all feature paths tested
- [x] 7.4 TaifexAdapter tests: verify config loading, snapshot conversion, lot translation, fee calculation — acceptance: adapter produces correct output for all methods
- [x] 7.5 Database tests: verify CRUD operations for all models — acceptance: round-trip persistence works

## 8. Quality Gates

- [x] 8.1 `ruff check` passes with zero errors
- [x] 8.2 `mypy --strict` passes with zero errors
- [x] 8.3 All pytest tests pass
