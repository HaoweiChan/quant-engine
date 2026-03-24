## 1. ParamRegistry: Slug Validation & Migration

- [x] 1.1 Add `_validate_strategy_slug(strategy: str)` private method to `ParamRegistry` that raises `ValueError` if the string contains `:` or starts with `src.`. Call it at the top of `save_run()`, `save_backtest_run()`, and `save_candidate()`. **Acceptance**: `save_run(strategy="src.foo:bar")` raises `ValueError`; `save_run(strategy="intraday/trend_following/ema_trend_pullback")` succeeds.

- [x] 1.2 Add `_migrate_strategy_names()` private method to `ParamRegistry.__init__()`. Query `param_runs` and `param_candidates` where `strategy LIKE '%:%'`. For each row, attempt to resolve the module path to a slug by extracting the path between `src.strategies.` and the `:` separator, replacing `.` with `/`. Update both tables in a single transaction. Log via structlog. **Acceptance**: After instantiation, run_id=3 in the DB has `strategy="intraday/trend_following/ema_trend_pullback"` instead of the module:factory string. Running migration twice changes nothing.

## 2. ParamRegistry: save_backtest_run Method

- [x] 2.1 Add `save_backtest_run()` method to `ParamRegistry`. Insert one `param_runs` row with `search_type="single"`, `n_trials=1`, `source` param, and `tag="tool:{tool}"`. Insert one `param_trials` row with metrics mapped to the standard columns (`sharpe`, `calmar`, `sortino`, `profit_factor`, `win_rate`, `max_drawdown_pct`, `trade_count`, `total_pnl`). Return `run_id` on success, `-1` on error (caught and logged). **Acceptance**: After calling `save_backtest_run(strategy="ema_trend_pullback", symbol="TX", params={"lots": 4}, metrics={"sharpe": 1.5, "total_pnl": 1520000}, tool="run_backtest_realdata")`, a new row exists in `param_runs` with `search_type="single"` and a corresponding `param_trials` row.

## 3. ParamRegistry: get_run_history Filter

- [x] 3.1 Add optional `search_type: str | None = None` parameter to `get_run_history()`. When provided, add `AND r.search_type = ?` to the SQL WHERE clause. **Acceptance**: `get_run_history("ema_trend_pullback", search_type="single")` returns only individual backtest runs; `get_run_history("ema_trend_pullback")` returns all runs.

## 4. Facade: resolve_strategy_slug Helper

- [x] 4.1 Add `resolve_strategy_slug(strategy: str) -> str` function to `src/mcp_server/facade.py`. Resolution order: (1) try `get_info(strategy)` from the strategy registry — if found, return its slug; (2) if `strategy` contains `:`, extract the module path between `src.strategies.` and `:`, replace `.` with `/`; (3) fall back to returning the input unchanged. **Acceptance**: `resolve_strategy_slug("ta_orb")` returns `"intraday/breakout/ta_orb"`; `resolve_strategy_slug("src.strategies.intraday.trend_following.ema_trend_pullback:create_ema_trend_pullback_engine")` returns `"intraday/trend_following/ema_trend_pullback"`.

## 5. Facade: Persist run_backtest Results

- [x] 5.1 In `run_backtest_for_mcp()`, after computing the result, call `ParamRegistry.save_backtest_run()` with `strategy=resolve_strategy_slug(strategy)`, `symbol=f"synthetic:{scenario}"`, `params=strategy_params or {}`, `metrics=result["metrics"]`, `source="mcp"`, `tool="run_backtest"`. Wrap in try/except — on failure, set `run_id=None`. Add `run_id` to the returned dict. **Acceptance**: After calling `run_backtest_for_mcp(scenario="strong_bull", strategy="ema_trend_pullback")`, a new row exists in `param_runs` with the correct slug and the response includes `"run_id"`.

## 6. Facade: Persist run_backtest_realdata Results

- [x] 6.1 In `run_backtest_realdata_for_mcp()`, after computing the result and before stripping arrays, call `ParamRegistry.save_backtest_run()` with `strategy=resolve_strategy_slug(strategy)`, `symbol=symbol`, `params=strategy_params or {}`, `metrics=result["metrics"]`, `source="mcp"`, `tool="run_backtest_realdata"`. Wrap in try/except. Add `run_id` to the returned dict. **Acceptance**: After calling `run_backtest_realdata_for_mcp(symbol="TX", start="2025-08-01", end="2026-03-14", strategy="intraday/trend_following/ema_trend_pullback")`, a new row exists in `param_runs` with `symbol="TX"` and `search_type="single"`.

## 7. Facade: Normalize Slug in run_sweep_for_mcp

- [x] 7.1 In `run_sweep_for_mcp()`, replace the raw `strategy` argument with `resolve_strategy_slug(strategy)` before passing to `registry.save_run()`. **Acceptance**: Calling `run_sweep_for_mcp(..., strategy="src.strategies.intraday.trend_following.ema_trend_pullback:create_ema_trend_pullback_engine")` stores `strategy="intraday/trend_following/ema_trend_pullback"` in the DB.

## 8. Frontend: Run History Panel

- [x] 8.1 In `Backtest.tsx`, add state for `paramRuns` (array of `ParamRun`) and a `historyOpen` boolean (default `false`). On strategy change, call `fetchParamRuns(strategy)` and store the result. **Acceptance**: Selecting a strategy triggers the API call and stores the response.

- [x] 8.2 Below the result charts section, render a collapsible "Run History" panel. When expanded, display a table/list of runs with columns: Date, Source, Type (`search_type`), Trials, Best Sharpe, Best PnL. Each sweep run with candidates shows an "Activate" button. When collapsed, show only the header with run count. Empty state shows "No optimization history for this strategy." **Acceptance**: After selecting a strategy with past runs, the panel shows the run history. Clicking "Activate" calls `activateCandidate()` and refreshes active params.

## 9. Testing

- [x] 9.1 Add unit tests for `resolve_strategy_slug()`: slug passthrough, legacy alias resolution, module:factory resolution, unknown strategy fallback.

- [x] 9.2 Add unit tests for `save_backtest_run()`: successful persistence, correct `search_type="single"`, no candidate creation, error handling returns `-1`.

- [x] 9.3 Add unit test for strategy name migration: create a DB with module:factory names, instantiate `ParamRegistry`, verify names are normalized. Run twice to verify idempotency.
