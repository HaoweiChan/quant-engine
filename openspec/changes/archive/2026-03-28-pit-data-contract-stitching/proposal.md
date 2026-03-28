## Why

Gap analysis (docs/critics-gemini.md) identified that our `TaifexAdapter` pulls static TOML configurations for contracts and assumes static `daily_atr`. There is zero Point-in-Time (PIT) capability, meaning backtests are vulnerable to survivorship bias and restatement bias. For futures, failing to account for roll yields and calendar spreads guarantees artificially inflated PnL. This is Phase B of the institutional-grade upgrade, building on Phase A's realistic fill model (change: `institutional-grade-upgrade`).

## What Changes

- **Add bi-temporal timestamps** (`knowledge_time` / `event_time`) to all mutable data records (margin rates, contract specs)
- **Implement `AS_OF(knowledge_time)` query semantics** so backtests only see data known at the simulated time, preventing look-ahead bias
- **Build continuous contract stitching pipeline** with three methods: ratio-adjusted (default), Panama (additive), and backward-adjusted
- **Store per-contract OHLCV data** separately and auto-detect roll dates from expiration calendar + volume crossover
- **Preserve unadjusted prices** alongside adjusted for the fill model (which needs real prices for impact calculation)
- **Add ADV computation** from stored OHLCV, PIT-safe for backtesting
- **Update `TaifexAdapter`** to use PIT-aware margin lookups during backtesting

## Capabilities

### New Capabilities
- `pit-data-layer`: Bi-temporal point-in-time database with `knowledge_time`/`event_time`, survivorship-bias-safe `AS_OF` queries, and schema migration as additive columns

### Modified Capabilities
- `data-layer`: Extended with PIT-aware margin queries, per-contract OHLCV storage, ADV computation, continuous contract stitching pipeline, and `contract_rolls` table

## Impact

- **Core modules**: `src/data/db.py`, `src/adapters/taifex.py`
- **New modules**: `src/data/pit.py`, `src/data/stitcher.py`
- **Schema**: Additive columns (`knowledge_time`, `valid_from`, `valid_to`) on margin table; new `contract_rolls` table
- **Dependencies**: No new external deps
- **Tests**: PIT query tests, stitching correctness tests, roll detection tests
