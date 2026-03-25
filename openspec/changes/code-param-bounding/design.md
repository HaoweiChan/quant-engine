## Context

Strategy optimization runs are currently persisted to `param_registry.db` with performance metrics (Sharpe, MDD, win rate) but no reference to the strategy code that produced them. The `StrategyOptimizer` and MCP facade dynamically import whatever `.py` file lives under `src/strategies/` at runtime — so if the agent modifies strategy logic after an optimization run, replaying that run's parameters executes them against different code. The stored metrics become historically dishonest.

Additionally, parameters pass directly from MCP tool inputs through `_build_runner()` to engine factories without any validation against the `PARAM_SCHEMA` min/max/type bounds. Out-of-range floats silently reach the engine.

Current data flow:

```
MCP Tool Input
    │
    ▼
facade.py::run_backtest_for_mcp()
    │  (no clamping)
    ▼
_build_runner() → BacktestRunner
    │  (no hash)
    ▼
ParamRegistry.save_backtest_run()  ← stores metrics only
    │  (no strategy_hash, no strategy_code)
    ▼
param_registry.db::param_runs
```

After this change, the flow becomes:

```
MCP Tool Input
    │
    ▼
facade.py::run_*_for_mcp()
    ├── validate_and_clamp(slug, params) → (clamped_params, warnings)
    ├── compute_strategy_hash(slug) → (hash, source)
    │
    ▼
_build_runner(clamped_params) → BacktestRunner
    │
    ▼
ParamRegistry.save_backtest_run(strategy_hash=hash, strategy_code=source)
    │
    ▼
param_registry.db::param_runs  ← now includes hash + source snapshot
```

## Goals / Non-Goals

**Goals:**
- Bind every optimization run to the exact strategy code it was tested against (SHA-256 hash + full source snapshot)
- Auto-deactivate stale active candidates when `write_strategy_file` changes the code hash
- Enforce `PARAM_SCHEMA` min/max/type bounds on all parameters before engine factory calls
- Surface `code_changed` boolean and hash metadata through the API and dashboard
- Maintain backward compatibility — old rows with NULL hash must never trigger false invalidation

**Non-Goals:**
- Temp-module replay (executing a historical run against its stored code snapshot) — hash + warn is sufficient for now
- Fork-to-live-draft UI mechanic — out of scope for this iteration
- Parameter validation in the API layer (only at facade/engine boundary)
- Cross-strategy parameter compatibility checks

## Decisions

### D1: Store full source text alongside the hash

Rationale: The hash alone can detect drift but can't explain it. Storing the full source in `param_runs.strategy_code` enables future forensics and replay without additional queries to a separate version store. The overhead is small — strategy files are typically 100–400 lines. Old rows get NULL (backward compat).

### D2: Clamp in each facade function, not inside `_build_runner`

`_build_runner()` currently returns `BacktestRunner`. Adding clamping inside it would force its return type to `tuple[BacktestRunner, list[str]]`, requiring all call sites (including `_mc_single_path` and `_run_mc_with_runner` in ProcessPoolExecutor paths) to unpack the tuple. Instead, clamping happens at the top of each `run_*_for_mcp()` function before any `_build_runner` call. This localizes the change and avoids return-type churn.

### D3: Auto-invalidation is non-fatal

`write_strategy_file` must never fail because invalidation logic errored. The entire deactivation block is wrapped in `try/except`. If it fails, the write still succeeds — a warning is appended to the response but the file is saved. This preserves the existing contract that `write_strategy_file` is always available to the agent.

### D4: NULL hash rows skip invalidation

`deactivate_stale_candidates()` uses `WHERE strategy_hash IS NOT NULL AND strategy_hash != ?` to skip pre-bounding rows. This prevents false invalidation of all legacy candidates the first time a new strategy file is written after this migration deploys.

### D5: `validate_and_clamp` lives in `registry.py`

The strategy registry already owns `PARAM_SCHEMA` access via `get_info()`. Placing `validate_and_clamp()` there keeps schema-bound logic co-located with schema definitions and avoids a circular import from `code_hash.py` → `registry.py` → `facade.py`.

### D6: Hash utility is a standalone module

`src/strategies/code_hash.py` contains only `strategy_file_path()` and `compute_strategy_hash()`. It depends on `registry._resolve_slug()` for alias resolution. Keeping it separate from `param_registry.py` avoids adding file I/O to the DB module.

## Risks / Trade-offs

### R1: Large source snapshots inflate DB size
Strategy files at 400 lines × ~40 bytes/line = ~16 KB per run. At 1000 runs/year this is ~16 MB — negligible for SQLite. If strategies grow significantly, a BLOB compression strategy (zlib) can be added as a future migration without breaking the schema.

### R2: Hash collisions are astronomically unlikely
SHA-256 provides 2^256 hash space. Treating a collision as "same code" is an acceptable risk.

### R3: Clamping changes param values silently
If an agent passes `stop_atr_mult=0.1` (below minimum) and the schema clamps it to `0.5`, the agent may not notice unless it reads `param_warnings` in the response. Mitigated by including `param_warnings` in every MCP tool response and logging at WARN level in the facade.

### R4: `strategy_code` column holds live Python source
The stored code is read from disk at backtest time, not compiled or sandboxed. This is consistent with the existing dynamic import model — no new attack surface is introduced. The column is read-only after INSERT.

### R5: Dashboard warning depends on API returning `code_changed`
If the API route fails to compute the current hash (e.g., strategy file deleted), it should return `code_changed: null` rather than `false`. Frontend must treat `null` as "unknown" rather than "safe". This is documented in the API spec.
