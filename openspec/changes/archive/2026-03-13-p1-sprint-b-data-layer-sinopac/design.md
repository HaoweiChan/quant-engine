## Context

Sprint A established the core types and Position Engine. Sprint B connects the engine to real market data via Sinopac (shioaji) and builds the data pipeline that feeds both the Position Engine (via `MarketSnapshot`) and the Prediction Engine (via the Feature Store).

The data layer sits at the top of the architecture diagram — every other module consumes its output. Getting the abstractions right here determines how cleanly the platform extends to crypto and US equities later.

## Goals / Non-Goals

**Goals:**
- Working Sinopac connector that fetches historical OHLCV data reliably
- Bar Builder that handles TAIFEX session gaps correctly
- Feature Store with standard indicators and market-specific feature plugins
- TaifexAdapter as the first concrete `BaseAdapter` implementation
- Parquet-based feature persistence and LRU cache for live serving
- Database layer for trade/signal/account persistence

**Non-Goals:**
- Real-time streaming (live tick-by-tick feed) — not needed until Sprint E paper trading
- CryptoAdapter or USEquityAdapter — deferred to Phase 3/4
- Volume-weighted or range bars — deferred to Phase 3
- Prediction model training — Sprint D

## Decisions

### Package layout

```
quant_engine/
├── core/                       # from Sprint A
├── data/
│   ├── __init__.py
│   ├── connector.py            # Sinopac connector (shioaji wrapper)
│   ├── bar_builder.py          # Minute → multi-timeframe aggregation
│   ├── feature_store.py        # Indicator computation + caching
│   ├── feature_plugins/
│   │   ├── __init__.py
│   │   ├── base.py             # FeaturePlugin ABC
│   │   └── taifex.py           # TW-specific features
│   └── db.py                   # SQLAlchemy-based persistence
├── adapters/
│   ├── __init__.py
│   └── taifex.py               # TaifexAdapter
└── config/
    └── taifex.toml              # Contract specs, margins, fees, trading hours
```

**Rationale:** Pluggable feature plugins allow Sprint D to add new features without modifying the store. Adapter config is in TOML to keep hardcoded market values out of code.

### DataFrames: polars for internal, pandas for pandas-ta compatibility

Bar Builder and Feature Store use polars internally for performance. When calling pandas-ta (which requires pandas), a thin conversion layer is used. The Feature Store exposes both polars and pandas output for flexibility.

**Rationale:** polars is significantly faster for the aggregation and filtering we do. pandas-ta has no polars equivalent, and reimplementing 7+ indicators is not worthwhile.

### Feature plugin architecture

Market-specific features are implemented as plugins extending a `FeaturePlugin` ABC:

```
class FeaturePlugin(ABC):
    @abstractmethod
    def compute(self, bars: pl.DataFrame) -> pl.DataFrame: ...
    @abstractmethod
    def required_columns(self) -> list[str]: ...
```

TaifexAdapter registers its plugin at construction. Future adapters register theirs.

**Rationale:** Keeps the core feature store market-agnostic while allowing each adapter to inject its own features.

### Adapter config from TOML

TaifexAdapter loads contract specs, margins, fees, and trading hours from `config/taifex.toml` rather than hardcoding values.

**Rationale:** Contract specs change (e.g., margin adjustments by the exchange). TOML is human-readable and easy to update without code changes.

### Database: SQLAlchemy with SQLite default

Use SQLAlchemy ORM with SQLite as the default backend. PostgreSQL support via connection string swap for production multi-process use.

**Rationale:** SQLite is zero-config for development and backtesting. SQLAlchemy abstracts the backend so PostgreSQL migration requires only a connection string change.

## Risks / Trade-offs

- **[Risk] shioaji API instability or breaking changes** → Mitigation: Wrap all shioaji calls in a connector class with retry logic. Pin shioaji version. Write integration tests that can run against a mock.
- **[Risk] TAIFEX session gap handling is tricky (day 08:45–13:45, night 15:00–05:00)** → Mitigation: Explicit session boundary detection in Bar Builder with configurable session definitions per adapter.
- **[Risk] pandas-ta computation is slow on large datasets** → Mitigation: Compute features incrementally (only new bars). Cache results in parquet.
- **[Risk] Sinopac credentials management** → Mitigation: Load from environment variables or a `.env` file, never commit to version control.
