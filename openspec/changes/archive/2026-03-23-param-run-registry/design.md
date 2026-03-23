## Context

Strategy parameter persistence is currently a single-layer TOML system: `param_loader.py` writes `configs/<slug>.toml` with only `best_params`, overwriting on every optimizer run. The full `OptimizerResult` (all trials, IS/OOS backtest results, warnings) is available in-memory during optimization but discarded after save. The MCP server tracks session history in an ephemeral `OptimizationHistory` object that resets on server restart. The dashboard optimizer CLI writes a comprehensive `result.json` to a temp directory that is never archived.

Three independent consumers need optimization data:
1. **MCP backtest-engine** — AI agent uses `run_parameter_sweep` and expects to recall previous runs
2. **Dashboard Optimizer** — user runs grid search and wants to review/compare past runs
3. **Dashboard Backtest page** — needs to load the currently active optimized params as sidebar defaults
4. **Live trading** — `registry.get_active_params()` needs to know which params are in production

All four currently read from different sources with different completeness levels.

## Goals / Non-Goals

**Goals:**
- Every optimization run is append-only persisted with full trial data, IS/OOS metrics, and run metadata
- Multiple parameter candidates (best per objective, Pareto frontier) coexist without overwriting
- A single `is_active` flag marks which candidate is used for production/backtesting
- MCP server and dashboard share the same persistent store and can reproduce each other's results
- Existing `save_strategy_params()` / `load_strategy_params()` API stays backward-compatible
- `registry.get_active_params()` transparently reads from the new store

**Non-Goals:**
- Storing equity curve time series in the DB (too large; only summary metrics stored)
- Building a UI for Pareto frontier visualization (future change)
- Changing how the optimizer itself runs (grid_search/random_search/walk_forward APIs untouched)
- Multi-user access control or concurrent write safety (single-user desktop application)
- Regime detection or automatic param switching (param candidates can be tagged by regime but switching is manual)

## Decisions

### D1: SQLite `param_registry.db` as the single persistence layer

```
param_registry.db
├── param_runs        ← one row per optimizer invocation
├── param_trials      ← one row per trial (all combinations)
└── param_candidates  ← promoted params (best, Pareto, manual)
                        with is_active flag
```

**Why SQLite over alternatives:**
- **vs. JSON files**: No query capability, no transactional safety, hard to compare across runs
- **vs. PostgreSQL**: Overkill for single-user desktop; adds deployment dependency
- **vs. extending TOML**: TOML is flat key-value; can't express relational trial data or multiple candidates
- **vs. Polars/Parquet**: Good for analytics but no atomic write, no foreign keys, no `is_active` flag

SQLite is stdlib, file-based (portable), supports concurrent reads, and the existing data layer (`src/data/db.py`) already uses SQLite via `Database` class, so the pattern is established.

**Location:** Same directory as `taifex_data.db` (project root), configurable via `PARAM_REGISTRY_DB` env var.

### D2: Three-table schema

```sql
CREATE TABLE param_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at       TEXT NOT NULL,       -- ISO 8601 timestamp
    strategy     TEXT NOT NULL,       -- "atr_mean_reversion", "pyramid"
    symbol       TEXT NOT NULL,       -- "TX", "TXAM" etc.
    train_start  TEXT,                -- ISO date of IS period start
    train_end    TEXT,                -- ISO date of IS period end
    test_start   TEXT,                -- ISO date of OOS period start (nullable)
    test_end     TEXT,                -- ISO date of OOS period end (nullable)
    objective    TEXT NOT NULL,       -- "sharpe", "calmar", etc.
    is_fraction  REAL,                -- 0.8 default
    n_trials     INTEGER NOT NULL,    -- total trial count
    search_type  TEXT NOT NULL,       -- "grid", "random", "walk_forward"
    source       TEXT NOT NULL,       -- "mcp", "dashboard", "cli"
    tag          TEXT,                -- user-defined label
    notes        TEXT
);

CREATE TABLE param_trials (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER NOT NULL REFERENCES param_runs(id),
    params       TEXT NOT NULL,       -- JSON dict of param values
    sharpe       REAL,
    calmar       REAL,
    sortino      REAL,
    profit_factor REAL,
    win_rate     REAL,
    max_drawdown_pct REAL,
    trade_count  INTEGER,
    total_pnl    REAL,
    is_oos       INTEGER NOT NULL DEFAULT 0  -- 0=IS, 1=OOS
);

CREATE TABLE param_candidates (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER NOT NULL REFERENCES param_runs(id),
    trial_id     INTEGER REFERENCES param_trials(id),
    strategy     TEXT NOT NULL,       -- denormalized for fast lookup
    params       TEXT NOT NULL,       -- JSON dict
    label        TEXT NOT NULL,       -- "best_sharpe", "pareto_sharpe1.2_calmar0.8"
    regime       TEXT,                -- "trending", "ranging", null=any
    is_active    INTEGER NOT NULL DEFAULT 0,
    activated_at TEXT,
    notes        TEXT
);

CREATE INDEX idx_runs_strategy ON param_runs(strategy);
CREATE INDEX idx_trials_run ON param_trials(run_id);
CREATE INDEX idx_candidates_strategy ON param_candidates(strategy);
CREATE INDEX idx_candidates_active ON param_candidates(strategy, is_active);
```

**Why `params` as JSON text, not individual columns:**
Strategies have different parameter sets. A JSON column is flexible across strategies while still queryable via `json_extract()` in SQLite. Metrics are explicit columns because they're standardized across all strategies and need efficient sorting/filtering.

**Why `strategy` is denormalized on `param_candidates`:**
`get_active(strategy)` is the hottest query (called on every backtest/live run). Denormalizing avoids a join.

### D3: `ParamRegistry` class as the API

```
                  ┌────────────────────────┐
                  │   ParamRegistry        │
                  │                        │
                  │  save_run()            │ ← optimizer_cli, facade, helpers
                  │  save_candidate()      │
                  │  activate()            │ ← MCP tool, dashboard button
                  │  get_active()          │ ← registry.get_active_params()
                  │  get_pareto_frontier() │ ← auto-called after save_run
                  │  get_run_history()     │ ← MCP tool, dashboard
                  │  compare_runs()        │ ← MCP tool
                  └───────────┬────────────┘
                              │ reads/writes
                  ┌───────────▼────────────┐
                  │   param_registry.db    │
                  └────────────────────────┘
```

Singleton instance created lazily, same pattern as the strategy registry. The class owns connection management and schema migration.

### D4: Pareto frontier extraction

After every `save_run()`, the registry automatically extracts Pareto-optimal trials across a default objective pair (`["sharpe", "calmar"]`) and saves them as candidates with label `pareto_sharpe{x}_calmar{y}`. The objective pair is configurable per call.

**Algorithm:** O(n²) pairwise dominance check on the trials DataFrame. For typical grid sizes (< 1000 trials), this is sub-second.

A trial `a` is dominated if there exists a trial `b` where `b[obj] >= a[obj]` for ALL objectives and `b[obj] > a[obj]` for AT LEAST ONE objective. Non-dominated trials form the Pareto frontier.

### D5: Integration points — who calls what

| Caller | Action | Registry method |
|---|---|---|
| `optimizer_cli.py` | After grid_search completes | `save_run()` → auto Pareto → `activate()` best |
| `facade.run_sweep_for_mcp` | After sweep completes | `save_run()` → auto Pareto |
| MCP `save_optimization_run` | Explicit save from agent | `save_run()` |
| MCP `get_run_history` | Query past runs | `get_run_history()` |
| MCP `activate_candidate` | Set active params | `activate()` |
| MCP `get_active_params` | Read active for backtest | `get_active()` |
| `registry.get_active_params()` | Read active for any consumer | `get_active()` → fallback to PARAM_SCHEMA defaults |
| Dashboard Backtest page | Load sidebar defaults | `GET /api/params/active/{strategy}` → `get_active()` |
| Dashboard Optimizer save | After user clicks save | `POST /api/params/save` → `activate()` |

### D6: MCP tool changes

**New tools:**
- `save_optimization_run` — persist a run with trials to the registry (for MCP-initiated sweeps that want explicit save)
- `get_run_history` — query persisted runs by strategy, date range, objective
- `activate_candidate` — mark a candidate as active
- `get_active_params` — return currently active params for a strategy (replaces schema-only default)

**Modified tools:**
- `get_optimization_history` — reads from persistent DB instead of in-memory list. Session history is a filtered view (runs from current session timestamp).
- `run_parameter_sweep` — automatically persists results to registry after completion.

### D7: Dashboard API routes

Three new endpoints under `/api/params/`:
- `GET /api/params/active/{strategy}` → returns active candidate params or PARAM_SCHEMA defaults
- `GET /api/params/runs/{strategy}` → returns run history (paginated, most recent first)
- `POST /api/params/activate/{candidate_id}` → marks a candidate as active

The Backtest page calls `GET /api/params/active/{strategy}` on strategy select to populate sidebar defaults.

### D8: Migration from TOML to SQLite

1. `ParamRegistry.__init__` creates tables if not exist (no separate migration tool needed)
2. On first `get_active()` call, if no active candidate exists in DB, falls back to TOML via `load_strategy_params()`, then falls back to PARAM_SCHEMA defaults
3. TOML files remain as readonly fallback — not deleted
4. `save_strategy_params()` is updated to also write to the registry (dual-write during transition)

## Risks / Trade-offs

**[DB file location]** — `param_registry.db` in project root works for development but may need relocation for production. Mitigation: support `PARAM_REGISTRY_DB` env var override.

**[JSON column query performance]** — `json_extract()` is slower than native columns for param filtering. Mitigation: acceptable for desktop-scale data (< 10k trials per run, < 100 runs). If needed, add materialized views later.

**[Pareto computation on large trial sets]** — O(n²) dominance check could be slow for > 5000 trials. Mitigation: random search is typically capped at 500 trials; grid search rarely exceeds 1000 combinations. Add a warning if n_trials > 5000.

**[Schema evolution]** — Adding columns to the DB later requires migration. Mitigation: use `CREATE TABLE IF NOT EXISTS` with `ALTER TABLE ADD COLUMN` checks at init time, matching the pattern used by `src/data/db.py`.

**[Backward compatibility]** — Code that imports `load_strategy_params` directly must keep working. Mitigation: the function signature is unchanged; it reads from DB first, falls back to TOML, then returns `None`.
