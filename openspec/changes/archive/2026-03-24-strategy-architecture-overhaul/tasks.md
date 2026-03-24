## 1. Enums and Shared Utilities (non-breaking prep)

- [x] 1.1 Add `StrategyCategory` and `StrategyTimeframe` enums to `src/strategies/__init__.py`. Verify `json.dumps(StrategyCategory.BREAKOUT)` serializes as `"breakout"`.
- [x] 1.2 Create `src/strategies/_session_utils.py` with `in_day_session()`, `in_night_session()`, `in_or_window()`, `in_force_close()`. Port logic from both `ta_orb.py` and `atr_mean_reversion.py`. Add unit tests.
- [x] 1.3 Create `src/strategies/_shared_indicators.py` with `RollingATR`, `RollingBB`, `RollingRSI`, `RollingMA` classes. Extract from `atr_mean_reversion._Indicators`. Verify numerical parity with existing implementation.

## 2. Directory Restructure

- [x] 2.1 Create nested directory skeleton: `intraday/breakout/`, `intraday/mean_reversion/`, `intraday/trend_following/`, `daily/breakout/`, `daily/trend_following/`, `examples/`. Add `__init__.py` to each.
- [x] 2.2 Move `ta_orb.py` → `intraday/breakout/ta_orb.py`. Update imports to use `_session_utils`. Update `STRATEGY_META` to include `StrategyCategory.BREAKOUT` and `StrategyTimeframe.INTRADAY`.
- [x] 2.3 Move `atr_mean_reversion.py` → `intraday/mean_reversion/atr_mean_reversion.py`. Refactor to use `_session_utils` and `_shared_indicators`. Update `STRATEGY_META`.
- [x] 2.4 Move `pyramid_wrapper.py` → `daily/trend_following/pyramid_wrapper.py`. Update `STRATEGY_META` with enums. Update the re-export import path.
- [x] 2.5 Move `example_entry.py`, `example_add.py`, `example_stop.py` → `examples/`. These are not discoverable (no `PARAM_SCHEMA`).
- [x] 2.6 Remove old flat strategy files from `src/strategies/` root after confirming nested versions work.

## 3. Registry Update (recursive discovery + aliases)

- [x] 3.1 Update `registry._discover()` to use `rglob("*.py")` with `_INFRA_MODULES` exclusion set. Generate path-like slugs from relative paths. Generate correct `mod_name` using `.` separator.
- [x] 3.2 Add `_SLUG_ALIASES` dict to `registry.py` mapping old flat slugs to new path-based slugs.
- [x] 3.3 Update `get_info()` and all public functions that take a slug to resolve aliases first.
- [x] 3.4 Add `invalidate()` function that clears `_registry` cache (sets to `None`).
- [x] 3.5 Add `category` and `timeframe` fields to `StrategyInfo` dataclass. Populate from `STRATEGY_META` during discovery.
- [x] 3.6 Add `get_by_category()` and `get_by_timeframe()` filter functions.
- [x] 3.7 Verify `validate_schemas()` works with new path-based slugs and nested imports.

## 4. Unified Factory Resolution (eliminate `_BUILTIN_FACTORIES`)

- [x] 4.1 Rewrite `facade.resolve_factory()` to use `registry.get_info()` as primary path, with alias resolution and `"module:factory"` fallback. Remove `_BUILTIN_FACTORIES` dict entirely.
- [x] 4.2 Update `helpers.py/run_strategy_backtest()` to remove the `_BUILTIN_FACTORIES` check. Use `resolve_factory()` directly (which now uses the registry).
- [x] 4.3 Verify all MCP tools (`run_backtest`, `run_monte_carlo`, `run_parameter_sweep`, `run_stress_test`) work with both old slugs (via aliases) and new path-based slugs.

## 5. Scaffold Tool (MCP + CLI)

- [x] 5.1 Create `src/strategies/scaffold.py` with `scaffold_strategy()` function. Generate policy classes with correct ABC stubs, `PARAM_SCHEMA`, `STRATEGY_META` with enums, and `create_<stem>_engine()` factory.
- [x] 5.2 Add `__main__` block to `scaffold.py` with argparse CLI: `python -m src.strategies.scaffold <name> --category <cat> --timeframe <tf> [--description] [--write]`.
- [x] 5.3 Add `scaffold_strategy` Tool to `tools.py` TOOLS list with input schema (name, category, timeframe, description, policies, params).
- [x] 5.4 Add handler in `register_tools()` that calls `scaffold_strategy()` and returns `_json_response()`.
- [x] 5.5 Verify end-to-end: scaffold → write_strategy_file → registry discovers → run_monte_carlo succeeds with `trade_count >= 0`.

## 6. Validation and File Tools Update

- [x] 6.1 Update `validation.list_strategy_files()` to use `rglob` with the same exclusion logic as the registry. Return path-like stems.
- [x] 6.2 Update `validation.backup_strategy_file()` to handle path-like filenames, preserving subdirectory structure in `.backup/`.
- [x] 6.3 Update `tools.py` `read_strategy_file` handler to resolve path-like filenames, with alias fallback for legacy flat names.
- [x] 6.4 Update `tools.py` `write_strategy_file` handler to create parent directories (`mkdir(parents=True)`) and call `registry.invalidate()` after successful write.
- [x] 6.5 Update tool descriptions and `inputSchema` help text in TOOLS list to document path-like filenames.

## 7. Documentation and Skill Update

- [x] 7.1 Update `.claude/skills/add-new-strategy/SKILL.md`: remove Step 2 (manual `_BUILTIN_FACTORIES`), add scaffold tool usage, update file paths to nested structure.
- [x] 7.2 Update `docs/strategies.md` to reflect the implemented directory structure (was a proposal, now is reality).
- [x] 7.3 Update MCP tool descriptions in `tools.py`: `read_strategy_file` and `get_parameter_schema` `description` fields to list new path-like stems and scaffold workflow.
