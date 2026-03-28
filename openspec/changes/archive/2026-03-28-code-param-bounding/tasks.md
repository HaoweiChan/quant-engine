## 1. Code Hash Utility

- [x] 1.1 Create `src/strategies/code_hash.py` with `strategy_file_path(slug)` and `compute_strategy_hash(slug)` functions
- [x] 1.2 Write unit tests in `tests/unit/test_code_hash.py`: deterministic hash, hash changes on edit, slug alias resolution, FileNotFoundError on missing file

## 2. DB Schema Migration

- [x] 2.1 Add `_migrate_add_code_hash()` to `ParamRegistry` — checks `PRAGMA table_info(param_runs)`, adds `strategy_hash TEXT` and `strategy_code TEXT` columns if absent
- [x] 2.2 Update `_SCHEMA_SQL` in `param_registry.py` to include `strategy_hash TEXT` and `strategy_code TEXT` for fresh databases
- [x] 2.3 Call `_migrate_add_code_hash()` from `_ensure_tables()` after the existing migration calls
- [x] 2.4 Write unit tests: migration adds columns to existing DB, fresh DB has columns, migration is idempotent

## 3. validate_and_clamp Function

- [x] 3.1 Add `validate_and_clamp(slug, params) -> tuple[dict, list[str]]` to `src/strategies/registry.py`
- [x] 3.2 Implement type coercion: `int()` for `"int"` schema type, `float()` for `"float"` schema type
- [x] 3.3 Implement min/max clamping with warning messages for out-of-range values
- [x] 3.4 Unknown params pass through with a warning; missing schema keys handled gracefully
- [x] 3.5 Write unit tests in `tests/unit/test_validate_and_clamp.py`: clamp below min, clamp above max, int coercion, float coercion, unknown param passthrough, no warnings when valid, input dict not mutated, empty params

## 4. Save Methods: Hash Parameters

- [x] 4.1 Add `strategy_hash: str | None = None` and `strategy_code: str | None = None` to `save_backtest_run()` signature and INSERT SQL
- [x] 4.2 Add `strategy_hash: str | None = None` and `strategy_code: str | None = None` to `save_run()` signature and INSERT SQL
- [x] 4.3 Write unit tests: save_backtest_run stores hash, save_run stores hash, save without hash stores NULL

## 5. Facade: Hash Computation and Clamping

- [x] 5.1 Import `compute_strategy_hash` from `code_hash` and `validate_and_clamp` from `registry` in `facade.py`
- [x] 5.2 Apply `validate_and_clamp()` before `_build_runner()` in `run_backtest_for_mcp()` and include `param_warnings` in response
- [x] 5.3 Apply `validate_and_clamp()` before `_build_runner()` in `run_backtest_realdata_for_mcp()` and include `param_warnings` in response
- [x] 5.4 Apply `validate_and_clamp()` before `_build_runner()` in `run_monte_carlo_for_mcp()` and include `param_warnings` in response
- [x] 5.5 Apply `validate_and_clamp()` in `run_stress_for_mcp()` before factory calls and include `param_warnings` in response
- [x] 5.6 Apply `validate_and_clamp()` in `_mc_single_path()` (ProcessPoolExecutor path) and `_run_mc_with_runner()` sequential branch
- [x] 5.7 Compute `(strategy_hash, strategy_code)` before save in `run_backtest_for_mcp()` — wrap in try/except, default to None on FileNotFoundError
- [x] 5.8 Compute and pass hash to save in `run_backtest_realdata_for_mcp()` and `run_sweep_for_mcp()` — same try/except pattern
- [x] 5.9 Include `strategy_hash` in responses for `run_backtest`, `run_backtest_realdata`

## 6. Auto-Invalidation on Code Change

- [x] 6.1 Add `deactivate_stale_candidates(strategy, current_hash) -> int` to `ParamRegistry` — deactivates active candidates where `param_runs.strategy_hash != current_hash AND strategy_hash IS NOT NULL`
- [x] 6.2 Add `check_code_hash_match(strategy, current_hash) -> bool | None` to `ParamRegistry`
- [x] 6.3 In `src/mcp_server/tools.py` `write_strategy_file` handler: after successful write, compute new hash, call `deactivate_stale_candidates()`, include `stale_candidates_deactivated` in response
- [x] 6.4 Wrap invalidation block in try/except — file write must never fail due to invalidation error
- [x] 6.5 Write unit tests: deactivate_stale_candidates deactivates mismatched hash, skips matching hash, skips NULL hash rows; stale count returned correctly

## 7. Hash Metadata in Registry Queries

- [x] 7.1 Add `r.strategy_hash` to the SELECT in `get_active_detail()` and include in return dict
- [x] 7.2 Add `r.strategy_hash` to the SELECT in `get_run_history()` and include in each entry dict
- [x] 7.3 Write unit tests: get_active_detail includes hash, get_active_detail returns None for NULL hash, get_run_history includes hash per entry

## 8. API Route Updates

- [x] 8.1 In `src/api/routes/params.py` `GET /api/params/active/{strategy}`: compute current file hash via `compute_strategy_hash()`, call `check_code_hash_match()`, add `code_changed: bool | None` to response
- [x] 8.2 In `GET /api/params/runs/{strategy}`: include `strategy_hash` per run entry (already from registry query)
- [x] 8.3 Handle FileNotFoundError from `compute_strategy_hash()` in API — set `code_changed: null`

## 9. Frontend: Warning Banners and Hash Display

- [x] 9.1 Add `strategy_hash?: string` and `code_changed?: boolean | null` to `ActiveParams` type in `frontend/src/lib/api.ts`
- [x] 9.2 In `frontend/src/pages/strategy/TearSheet.tsx`: add amber warning banner when `paramSource.code_changed === true` — "Active parameters were optimized against a different version of this strategy. Re-run optimization." (supersedes former `Backtest.tsx` / `Optimizer.tsx` targets after Strategy hub refactor)
- [x] 9.3 In `TearSheet.tsx` run history table: show truncated hash (first 8 chars) alongside each run entry if `strategy_hash` is present
- [x] 9.4 Same warning and param context as 9.2–9.3 live on Tear Sheet; no separate Optimizer page
- [x] 9.5 In `frontend/src/pages/Trading.tsx` (War Room): show stale indicator on strategy card when deployed candidate has mismatched hash

## 10. Tests: Integration and Regression

- [x] 10.1 Write integration test: full flow — run_backtest → verify strategy_hash in DB → write_strategy_file with new content → verify active candidate deactivated → verify stale_candidates_deactivated in response
- [x] 10.2 Write integration test: clamping — call run_backtest with out-of-range param → verify clamped value in DB → verify param_warnings in response
- [x] 10.3 Write integration test: backward compat — DB with NULL hash rows → write_strategy_file → verify no false invalidation of NULL hash candidates
- [x] 10.4 Run full test suite and verify no regressions: `uv run pytest tests/unit/ -x`
- [x] 10.5 Run integration tests: `uv run pytest tests/integration/ -x`
