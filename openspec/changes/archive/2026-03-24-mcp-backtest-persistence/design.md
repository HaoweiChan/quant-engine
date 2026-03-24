## Context

The quant-engine MCP server exposes backtest/simulation tools to AI agents. Three tools generate performance results: `run_backtest` (synthetic), `run_backtest_realdata` (historical DB), and `run_parameter_sweep` (grid/random search). Only `run_parameter_sweep` persists results to `param_registry.db`; the other two store results only in an in-memory `OptimizationHistory` object that is lost on process restart.

The dashboard Backtest page fetches active params via `GET /api/params/active/{strategy}` and can query run history via `GET /api/params/runs/{strategy}`, but the frontend never calls the latter — there is no UI for optimization progression.

Additionally, the `run_parameter_sweep` facade passes the raw `strategy` argument to `ParamRegistry.save_run()`. When agents use the `module:factory` format (e.g., `src.strategies.intraday.trend_following.ema_trend_pullback:create_ema_trend_pullback_engine`), that raw string is stored in the DB. The dashboard API queries by slug (`intraday/trend_following/ema_trend_pullback`), so the data is invisible.

## Goals / Non-Goals

**Goals:**
- Every MCP backtest/MC run leaves a durable record in `param_registry.db`
- Strategy identifiers are normalized to registry slugs before any DB write
- Dashboard shows optimization run history per strategy
- Existing mis-stored strategy names are migrated on first access

**Non-Goals:**
- Changing the in-memory `OptimizationHistory` behavior (it remains useful for within-session sorting)
- Adding persistence for `run_stress_test` (stress tests are validation, not optimization)
- Building a full optimization comparison UI (Optimizer page handles that separately)
- Modifying the `OptimizerResult` type or the sweep persistence flow (only adding a lighter path alongside it)

## Decisions

### 1. Lightweight `save_backtest_run()` method on `ParamRegistry`

**Decision**: Add a new method `save_backtest_run()` that accepts a flat metrics dict + params dict instead of requiring a full `OptimizerResult`.

**Rationale**: `run_backtest` and `run_backtest_realdata` produce a single result, not an `OptimizerResult` with trials DataFrame. Forcing them into `save_run()` would require constructing a synthetic `OptimizerResult` with a single-row DataFrame — awkward and fragile. A dedicated method is cleaner.

**Alternative considered**: Wrapping single results into a 1-trial `OptimizerResult`. Rejected because it adds coupling to the optimizer type system for a conceptually different operation (single eval vs. search).

**Implementation**:
```
save_backtest_run(
    strategy: str, symbol: str, params: dict,
    metrics: dict, source: str, tool: str, tag: str | None,
) -> int
```
Inserts one `param_runs` row (`search_type="single"`, `n_trials=1`) and one `param_trials` row. No candidate auto-creation (single runs aren't optimization results). Returns `run_id`.

### 2. Slug normalization via `resolve_strategy_slug()` helper

**Decision**: Add a `resolve_strategy_slug()` function in `facade.py` that converts any strategy identifier to its canonical registry slug. Call it before every DB write.

**Rationale**: Strategy identifiers arrive in three formats: slug (`intraday/trend_following/ema_trend_pullback`), legacy alias (`ta_orb`), or module:factory (`src.strategies.intraday.trend_following.ema_trend_pullback:create_ema_trend_pullback_engine`). The registry already resolves all three to run backtests — we just need the slug for storage.

```
Strategy input             →  resolve_strategy_slug()  →  DB value
─────────────────────────────────────────────────────────────────────
"intraday/trend_following/ema_trend_pullback"    →  same
"ta_orb"                                          →  "intraday/breakout/ta_orb"
"src.strategies...ema_trend_pullback:create_..."  →  "intraday/trend_following/ema_trend_pullback"
```

Resolution order: (1) check `get_info(strategy)` for exact slug/alias match, (2) parse module path to derive slug, (3) fall back to the raw string (shouldn't happen in practice).

### 3. Persist in facade, not in tools.py

**Decision**: Add persistence calls inside `run_backtest_for_mcp()` and `run_backtest_realdata_for_mcp()` in `facade.py`, not in the `tools.py` handler.

**Rationale**: The facade is the single source of truth for backtest execution. Both MCP tools and dashboard API call the same facade functions. Persisting at the facade level ensures all callers get persistence for free, and `tools.py` stays as a thin dispatch layer.

### 4. Migration of existing mis-stored strategy names

**Decision**: Add a one-time migration in `ParamRegistry.__init__()` that normalizes strategy names in existing rows using `resolve_strategy_slug()`.

**Rationale**: Run_id=3 already has data stored under `src.strategies.intraday.trend_following.ema_trend_pullback:create_ema_trend_pullback_engine`. Rather than leaving orphaned data, fix it in place. The migration is idempotent (running it twice is safe) and only touches rows where the strategy column contains `:` or `.` patterns.

### 5. Run history panel in Backtest page

**Decision**: Add a collapsible "Run History" panel below the results section in `Backtest.tsx`. Calls `fetchParamRuns(strategy)` when a strategy is selected.

**Rationale**: The API endpoint and client function already exist (`/api/params/runs/{strategy}` and `fetchParamRuns()`). The UI just needs to display them. A collapsible panel keeps the page clean when users don't need history.

**Alternative considered**: A separate page/tab for run history. Rejected because it fragments the backtest workflow — users want to see current + historical results in one place.

## Risks / Trade-offs

- **DB growth**: Persisting every individual backtest adds rows. Agents running 50+ backtests per session will create 50+ `param_runs` rows. → Mitigation: `search_type="single"` flag lets the UI filter/collapse these. Future: add retention policy or archival.

- **Performance of slug resolution**: `resolve_strategy_slug()` imports the strategy registry on each call. → Mitigation: The registry is cached after first scan; subsequent calls are dict lookups. Module-path parsing is pure string ops.

- **Migration safety**: Updating strategy names in `param_runs` and `param_candidates` changes the query key. → Mitigation: Migration is idempotent and only touches rows matching the module:factory pattern. A backup of the DB file before first migration run is recommended (documented in tasks).

- **No candidate auto-creation for single runs**: Single backtests don't create `param_candidates`. Users can't "activate" a single run's params directly. → Acceptable: Single runs are exploratory. To activate params, users should run a sweep or manually activate via the API.
