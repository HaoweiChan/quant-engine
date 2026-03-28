## Context

The current data layer stores OHLCV bars and margin snapshots without temporal versioning. When the `TaifexAdapter` constructs a `MarketSnapshot`, it reads margin requirements from the latest DB record or falls back to static TOML config. In a backtest running at simulated date T, this means the engine sees today's margin requirements — not the requirements that were in effect at T. This is a form of look-ahead bias that inflates risk-adjusted returns.

For futures like TAIFEX TX, contract rolls happen monthly (3rd Wednesday). Our OHLCV data is stored as a single continuous symbol (`TX`) with no awareness of which specific contract month was traded. This prevents proper back-adjustment and introduces roll-yield artifacts.

## Goals / Non-Goals

**Goals:**
- Add bi-temporal `knowledge_time` / `event_time` to mutable data (margins, contract specs)
- Implement `AS_OF` query semantics for look-ahead-safe backtesting
- Build contract stitching with ratio/panama/backward methods
- Store per-contract OHLCV data alongside generic symbol data
- Provide PIT-safe ADV computation for the impact model (Phase A)

**Non-Goals:**
- Full bi-temporal database engine (we add columns, not change engines)
- Real-time tick data storage (tick data is a separate concern)
- Multi-exchange roll coordination (TAIFEX only for now)

## Decisions

### D1: Additive Schema Migration over New Database

**Decision**: Add `knowledge_time`, `valid_from`, `valid_to` columns to existing mutable tables. OHLCV remains unchanged (immutable data, single `event_time`).

**Rationale**: Existing queries that don't use `AS_OF` continue to work — they implicitly get the latest version. No data migration needed for OHLCV. Only the margin_snapshots and contract_specs tables gain new columns.

### D2: Ratio-Adjusted as Default Stitching

**Decision**: Default to ratio-adjusted stitching. Store both adjusted and unadjusted prices in `StitchedSeries`.

**Rationale**: Ratio adjustment preserves percentage returns across rolls — correct for PnL-based backtesting. The impact model (Phase A) needs unadjusted prices for accurate impact calculation, so both must be available.

### D3: Roll Detection via Volume Crossover + Calendar

**Decision**: Primary roll detection: when next-month contract volume exceeds front-month volume for 2 consecutive days near expiration week. Fallback: 3rd Wednesday of each month (TAIFEX expiration calendar).

**Rationale**: Volume crossover is the industry standard for futures roll detection. The calendar fallback handles thin markets where volume crossover may not be reliable.

### D4: Separate SQLite for Contract Data (Phase 1)

**Decision**: Per-contract OHLCV data shares the same database. Contract rolls stored in a new `contract_rolls` table.

**Rationale**: Keeping everything in one DB simplifies transactions. The data volume for TAIFEX is manageable (<100MB for 10 years of minute bars × 12 contract months/year).

## Risks / Trade-offs

**[Risk: PIT columns add write overhead]** → Only mutable data (margin snapshots, ~1 write/day) gains columns. OHLCV writes are unchanged.

**[Risk: Stitching adjustment factors accumulate rounding errors]** → Use `float64` precision. For ratio stitching, compound multiplication preserves accuracy better than additive Panama.

**[Risk: Roll detection false positives]** → Volume crossover requires 2 consecutive days to confirm. Calendar fallback prevents missing actual rolls.
