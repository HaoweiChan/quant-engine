## Why

Optimization results are almost entirely thrown away. `save_strategy_params()` writes a single TOML with only the `best_params` dict, overwriting on every re-run. The full `OptimizerResult` — all trial metrics, IS/OOS backtest results, equity curves, and warnings — is discarded. The MCP server's `OptimizationHistory` is session-scoped in-memory and lost on restart. The dashboard optimizer CLI writes complete results to a temp JSON that is never archived. There is no shared persistence between the MCP server and the dashboard, so optimization done via MCP cannot be reproduced or reviewed in the dashboard Backtest page, and vice versa. This makes parameter version management, multi-objective comparison, and historical analysis impossible.

## What Changes

- A new SQLite database (`param_registry.db`) replaces per-strategy TOML files as the canonical store for optimization runs, trials, and active parameter sets.
- Every optimizer run (grid search, random search, walk-forward) persists all trials with full metrics, IS/OOS results, and run metadata (strategy, symbol, date range, objective, tag, notes).
- Pareto frontier extraction automatically identifies non-dominated parameter sets across multiple objectives (e.g. Sharpe vs Calmar) and stores them as named candidates.
- An explicit `is_active` flag marks which parameter set is currently used by live trading and backtests, replacing the overwrite-based TOML approach with append-only versioning.
- The MCP backtest-engine server gains tools to save runs, query run history, list/activate candidates, and compare runs across time — persistent across sessions.
- The dashboard Backtest page loads the active optimized params (from the registry) as defaults, and the Optimizer page saves results to the registry instead of TOML.
- `registry.get_active_params()` reads from the SQLite registry instead of TOML files.

## Capabilities

### New Capabilities
- `param-run-registry`: SQLite-backed persistence layer for optimization runs, trials, Pareto candidates, and active parameter selection. Provides `ParamRegistry` class with save/query/activate/compare APIs.

### Modified Capabilities
- `strategy-param-persistence`: TOML single-file persistence is replaced by SQLite registry. `save_strategy_params()` and `load_strategy_params()` become thin wrappers that delegate to `ParamRegistry`. Backward-compatible API maintained.
- `strategy-registry`: `get_active_params()` reads the active candidate from SQLite instead of merging TOML overrides.
- `backtest-mcp-server`: New MCP tools (`save_optimization_run`, `get_run_history`, `get_active_params`, `activate_candidate`) replace session-scoped in-memory history with persistent SQLite storage. Existing `get_optimization_history` returns persistent data.
- `dashboard`: Backtest page sidebar loads active optimized params from the registry as defaults. Optimizer sub-tab saves full results to the registry and shows Pareto candidates.

## Impact

- **New files**: `src/strategies/param_registry.py` (~200 lines), migration for `param_registry.db`
- **Modified files**: `src/strategies/param_loader.py` (delegate to registry), `src/strategies/registry.py` (read from registry), `src/mcp_server/facade.py` (save sweep results), `src/mcp_server/tools.py` (new MCP tools), `src/mcp_server/history.py` (delegate to registry), `src/dashboard/helpers.py` (save optimizer results to registry), `src/simulator/optimizer_cli.py` (save results to registry), `frontend/src/pages/Backtest.tsx` (load active params), `frontend/src/lib/api.ts` (new API endpoints)
- **New API routes**: `GET /api/params/active/{strategy}`, `GET /api/params/runs/{strategy}`, `POST /api/params/activate/{candidate_id}`
- **Database**: New `param_registry.db` alongside existing `taifex_data.db`
- **Dependencies**: None new (SQLite is stdlib)
- **Breaking**: None — existing `save_strategy_params()` / `load_strategy_params()` signatures maintained as wrappers. TOML files become optional fallback during migration.
