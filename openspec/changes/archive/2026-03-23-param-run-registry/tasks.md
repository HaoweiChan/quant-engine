## 1. ParamRegistry core module

- [x] 1.1 Create `src/strategies/param_registry.py` with `ParamRegistry` class. Implement `__init__` that accepts optional `db_path` (defaulting to `PARAM_REGISTRY_DB` env var or `<project_root>/param_registry.db`), creates the SQLite connection, and runs `_ensure_tables()` to create `param_runs`, `param_trials`, `param_candidates` tables with indexes if they don't exist. Acceptance: `ParamRegistry()` creates the DB file and all three tables.

- [x] 1.2 Implement `save_run(result, strategy, symbol, objective, ...)` that inserts one `param_runs` row and one `param_trials` row per trial from `result.trials`. Store each trial's params as JSON text. Extract standard metrics (`sharpe`, `calmar`, `sortino`, `profit_factor`, `win_rate`, `max_drawdown_pct`, `trade_count`, `total_pnl`) from each trial row. If `best_oos_result` exists, insert a separate `param_trials` row with `is_oos=1` and the OOS metrics. Auto-create a `param_candidates` row with `label=f"best_{objective}"` using the best trial's params. Return the `run_id`. Acceptance: after `save_run()`, the DB contains correct run metadata, all trial rows, and the best candidate.

- [x] 1.3 Implement `get_pareto_frontier(run_id, objectives=None)` that queries all IS trials for the given run and computes the Pareto-optimal set using pairwise dominance checking. Default objectives `["sharpe", "calmar"]`. Return a list of dicts with trial params and metric values. Log a warning via structlog if n_trials > 5000. Acceptance: returns non-dominated trials; single-objective returns best-only; all-equal returns all.

- [x] 1.4 Implement auto-Pareto in `save_run()`: after saving trials, call `get_pareto_frontier()` and save each Pareto point as a candidate with label `f"pareto_sharpe{s:.2f}_calmar{c:.2f}"`. Acceptance: `save_run()` creates Pareto candidate rows in addition to the best candidate.

- [x] 1.5 Implement `save_candidate(run_id, trial_id, params, label, regime, notes)` for manual candidate creation. Acceptance: inserts a row into `param_candidates` with correct foreign keys.

- [x] 1.6 Implement `activate(candidate_id)` that sets `is_active=1` and `activated_at=now()` on the target candidate, and `is_active=0` on all other candidates for the same strategy. Raise `ValueError` if candidate_id doesn't exist. Acceptance: only one candidate per strategy has `is_active=1` at any time.

- [x] 1.7 Implement `get_active(strategy)` that queries the active candidate and returns its `params` dict (JSON-parsed), or `None` if no active candidate exists. Acceptance: returns correct params after activation; returns `None` for strategies with no active candidate.

- [x] 1.8 Implement `get_run_history(strategy, limit=20)` that returns runs sorted by `run_at` desc, each with run metadata, best trial metrics, and candidate count. Acceptance: returns most recent runs; empty list for unknown strategies.

- [x] 1.9 Implement `compare_runs(run_ids)` that returns best trial metrics for each requested run for side-by-side comparison. Skip non-existent run IDs. Acceptance: returns correct data for valid runs; silently skips invalid IDs.

## 2. Migrate param_loader and strategy registry

- [x] 2.1 Update `src/strategies/param_loader.py`: modify `load_strategy_params(name)` to first try `ParamRegistry().get_active(name)`, then fall back to TOML file read. Modify `save_strategy_params(name, params, metadata)` to also save to the registry as a candidate and activate it (dual-write). Keep the existing TOML write for backward compatibility. Acceptance: `load_strategy_params` reads from DB first; `save_strategy_params` writes to both DB and TOML.

- [x] 2.2 Update `src/strategies/registry.py`: modify `get_active_params(slug)` to read from `ParamRegistry` via `param_loader.load_strategy_params()` (which now checks DB first). Wrap the DB read in a try/except that logs a warning and falls back to TOML → PARAM_SCHEMA defaults. Acceptance: `get_active_params()` returns DB-stored params when available; falls back gracefully on DB errors.

## 3. Integrate with optimizer CLI

- [x] 3.1 Update `src/simulator/optimizer_cli.py`: after `opt.grid_search()` returns, call `ParamRegistry().save_run()` with the result, strategy name, symbol, date range, objective, is_fraction, `search_type="grid"`, and `source="dashboard"`. Acceptance: every dashboard optimizer run is persisted to `param_registry.db` with full trials.

## 4. Integrate with MCP facade

- [x] 4.1 Update `src/mcp_server/facade.py`: modify `run_sweep_for_mcp()` to persist the `OptimizerResult` to the registry via `ParamRegistry().save_run()` with `source="mcp"`. Include the `run_id` in the returned dict. Acceptance: every MCP sweep is auto-persisted; response includes `run_id`.

- [x] 4.2 Create facade functions for new MCP tools: `save_optimization_run_for_mcp(strategy, symbol, objective, tag, notes)` that saves the most recent sweep result from the session. `get_run_history_for_mcp(strategy, limit)` that queries `ParamRegistry.get_run_history()`. `activate_candidate_for_mcp(candidate_id)` that calls `ParamRegistry.activate()`. `get_active_params_for_mcp(strategy)` that calls `ParamRegistry.get_active()` with fallback to registry defaults. Acceptance: each function returns a JSON-serializable dict.

## 5. Add MCP tools

- [x] 5.1 Register 4 new MCP tools in `src/mcp_server/tools.py`: `save_optimization_run`, `get_run_history`, `activate_candidate`, `get_active_params`. Each tool calls the corresponding facade function. Update tool descriptors in the MCP tools folder. Acceptance: MCP client can discover and call all 4 new tools.

- [x] 5.2 Update `get_optimization_history` tool to read from `ParamRegistry.get_run_history()` instead of the in-memory `OptimizationHistory` object. Keep the in-memory history as a session-local fast cache for deduplication. Acceptance: `get_optimization_history` returns persisted runs across sessions.

## 6. Dashboard API routes

- [x] 6.1 Create `src/api/routes/params.py` with three endpoints: `GET /api/params/active/{strategy}` returns active candidate params or PARAM_SCHEMA defaults. `GET /api/params/runs/{strategy}` returns run history. `POST /api/params/activate/{candidate_id}` activates a candidate. Register the router in the main app. Acceptance: all three endpoints return correct JSON responses; invalid candidate_id returns 404.

- [x] 6.2 Update `src/api/routes/optimizer.py` or `src/dashboard/helpers.py`: modify `start_optimizer_run` / `get_optimizer_state` to call `ParamRegistry.save_run()` when the optimizer subprocess completes with `status="ok"`. Acceptance: dashboard optimizer results are persisted to the registry on completion.

## 7. Frontend integration

- [x] 7.1 Add API functions to `frontend/src/lib/api.ts`: `fetchActiveParams(strategy: string)` calling `GET /api/params/active/{strategy}`. `fetchParamRuns(strategy: string)` calling `GET /api/params/runs/{strategy}`. `activateCandidate(candidateId: number)` calling `POST /api/params/activate/{candidateId}`. Acceptance: TypeScript functions compile and return typed responses.

- [x] 7.2 Update `frontend/src/pages/Backtest.tsx`: on strategy selection, call `fetchActiveParams(strategy)` and populate sidebar inputs with the returned params. If the response indicates optimized params (not defaults), show a label like "Optimized (sharpe, 2026-03-22)" next to the strategy name. Fall back to param_grid defaults if the API call fails. Acceptance: Backtest sidebar shows optimized params when available; shows defaults otherwise; visual indicator distinguishes optimized from default params.

## 8. Tests

- [x] 8.1 Add `tests/test_param_registry.py`: test DB creation, `save_run()` with mock OptimizerResult, `get_active()`, `activate()`, `get_run_history()`, `compare_runs()`, Pareto frontier extraction (2-objective, single-objective, all-equal cases), and TOML fallback. Use a temp DB path for isolation. Acceptance: all tests pass with `pytest tests/test_param_registry.py`.

- [x] 8.2 Add integration test verifying the full flow: save_run → auto Pareto → activate best → get_active returns correct params → load_strategy_params returns same params. Acceptance: end-to-end flow works correctly.

- [x] 8.3 Verify existing tests still pass (`pytest tests/`). Acceptance: all existing tests green, no regressions from param_loader and registry changes.
