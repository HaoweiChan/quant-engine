## Why

Individual backtest runs submitted via MCP (`run_backtest`, `run_backtest_realdata`) are never persisted to `param_registry.db` — only `run_parameter_sweep` writes to the DB. This means agents can run dozens of optimization experiments through backtest/MC tools, but the results vanish when the MCP session ends. Additionally, even the sweep data that IS persisted uses raw module:factory strings as strategy names instead of normalized slugs, making it invisible to the dashboard API which queries by slug. Finally, `fetchParamRuns()` exists in the frontend API client but no page actually uses it, so there's no UI to view optimization progression.

## What Changes

- Persist individual `run_backtest` and `run_backtest_realdata` results to `param_registry.db` so agent optimization sessions leave a durable trail
- Add a lightweight `save_backtest_run()` method to `ParamRegistry` for single-run persistence (no full `OptimizerResult` needed)
- Normalize strategy identifiers to registry slugs before writing to the DB, so `src.strategies.intraday.trend_following.ema_trend_pullback:create_ema_trend_pullback_engine` becomes `intraday/trend_following/ema_trend_pullback`
- Fix existing mis-stored strategy names in `run_sweep_for_mcp` by normalizing before `save_run()`
- Wire `fetchParamRuns()` into the Backtest dashboard page so users can see the optimization run history for any strategy

## Capabilities

### New Capabilities

(none — all changes modify existing capabilities)

### Modified Capabilities

- `param-run-registry`: Add `save_backtest_run()` for single-run persistence and require strategy name normalization before any DB write
- `backtest-mcp-server`: `run_backtest` and `run_backtest_realdata` SHALL persist results to the param registry; facade functions SHALL normalize strategy identifiers to slugs
- `react-frontend`: Backtest page SHALL display param run history panel using the existing `/api/params/runs/{strategy}` endpoint

## Impact

- **Backend**: `src/strategies/param_registry.py` — new method; `src/mcp_server/facade.py` — normalization + persistence calls in two existing functions; `src/mcp_server/tools.py` — no changes needed (facade handles persistence)
- **Frontend**: `frontend/src/pages/Backtest.tsx` — new run history panel using already-available `fetchParamRuns` API function
- **Database**: `param_registry.db` gets a new `search_type` value (`"single"`) for individual backtests; existing data with wrong strategy names should be migrated
- **Breaking**: None — additive changes only
