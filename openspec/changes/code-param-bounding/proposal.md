## Why

Strategy parameter sets stored in the registry are disconnected from the code they were optimized against — if the agent modifies strategy logic and replays historical params, results are unreproducible and stored metrics become misleading. Additionally, parameters pass directly to engine factories without validation against `PARAM_SCHEMA` bounds, allowing out-of-range values to silently reach the engine.

## What Changes

- Add `strategy_hash` (SHA-256) and `strategy_code` (full source snapshot) columns to `param_runs` DB table
- Compute and store code hash + source on every backtest save (single run, sweep, real-data)
- Auto-deactivate stale candidates when `write_strategy_file` detects a code hash change
- Add `validate_and_clamp()` to the strategy registry — enforces `PARAM_SCHEMA` min/max/type on all param dicts before engine factory calls
- Expose `code_changed` boolean and `strategy_hash` in the active params API response
- Show warning banner in dashboard when active candidate was optimized against different code

## Capabilities

### New Capabilities

- `code-param-bounding`: Binds each optimization run to the exact strategy code it was tested against — stores hash + source snapshot, detects drift, auto-invalidates stale candidates, and surfaces warnings to API and dashboard consumers.
- `param-validation`: Runtime enforcement of `PARAM_SCHEMA` bounds and type coercion before any engine factory call — returns clamped params and a list of modification warnings.

### Modified Capabilities

- `strategy-param-persistence`: `param_runs` schema gains `strategy_hash` and `strategy_code` columns; `save_backtest_run()` and `save_run()` accept and persist these; `get_active_detail()` and `get_run_history()` return hash metadata.
- `backtest-mcp-server`: `write_strategy_file` triggers auto-invalidation; all backtest tools apply `validate_and_clamp()` and surface `param_warnings` in responses.

## Impact

- **`src/strategies/param_registry.py`** — schema migration, save signatures, deactivation method, hash queries
- **`src/strategies/registry.py`** — new `validate_and_clamp()` function
- **`src/mcp_server/facade.py`** — clamping before factory calls, hash computation before saves
- **`src/mcp_server/tools.py`** — auto-invalidation hook in `write_strategy_file`
- **`src/api/routes/params.py`** — `code_changed` boolean and hash in responses
- **`frontend/src/lib/api.ts`**, **`Backtest.tsx`**, **`Optimizer.tsx`**, **`Trading.tsx`** — warning banners and hash display
- **`data/param_registry.db`** — backward-compatible schema migration (NULL for old rows)
