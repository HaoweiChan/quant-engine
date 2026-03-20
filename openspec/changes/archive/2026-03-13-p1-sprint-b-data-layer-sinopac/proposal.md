## Why

Sprint A delivers Core Types and Position Engine, but they operate on synthetic data only. To backtest against real history and eventually paper/live trade, the platform needs a data ingestion pipeline and a concrete market adapter. The Sinopac connector provides access to TAIFEX historical data, making the engine usable against real market conditions.

## What Changes

- Implement Sinopac connector (shioaji): login, session management, historical OHLCV fetch, error handling
- Implement Bar Builder: aggregate minute data to multi-timeframe bars (5m, 1H, 4H, daily), compute ATR per timeframe, handle TAIFEX session gaps
- Implement Feature Store: standard technical indicators (RSI, MACD, Bollinger, etc.), market-specific pluggable features, parquet storage, in-memory LRU cache
- Implement TaifexAdapter: concrete `BaseAdapter` for TAIFEX with contract specs loaded from config, snapshot conversion, lot translation, trading hours, fee calculation
- Implement database layer for persisting trades, signals, and account snapshots

## Capabilities

### New Capabilities

_(none — all capabilities already have specs)_

### Modified Capabilities

- `data-layer`: Implement from existing spec — connectors, bar builder, feature store, parquet storage, cache, database layer
- `market-adapters`: Implement TaifexAdapter from existing spec (CryptoAdapter and USEquityAdapter deferred to Phase 3/4)

## Impact

- **New packages**: `quant_engine.data.connector`, `quant_engine.data.bar_builder`, `quant_engine.data.feature_store`, `quant_engine.data.db`, `quant_engine.adapters.taifex`
- **Dependencies**: shioaji, pandas-ta, polars, pyarrow, sqlalchemy
- **External requirements**: Sinopac brokerage credentials for real data access
- **Downstream unblocked**: Sprint C (Backtester) can now run on real historical data; Sprint D (Prediction) has features to train on
