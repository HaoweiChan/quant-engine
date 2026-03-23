## 1. Add PARAM_SCHEMA to strategy files

- [x] 1.1 Add `PARAM_SCHEMA` and `STRATEGY_META` dicts to `src/strategies/atr_mean_reversion.py`. Keys must match the `create_atr_mean_reversion_engine()` kwargs (excluding `max_loss`, `lots`, `contract_type`). Each entry has `type`, `default`, `min`, `max`, `description`, and optional `grid`. Acceptance: `PARAM_SCHEMA` importable, keys match factory signature.

- [x] 1.2 Create `src/strategies/pyramid_wrapper.py` that exports `PARAM_SCHEMA` for the pyramid strategy and re-exports `create_pyramid_engine` from `src.core.position_engine`. Acceptance: `PARAM_SCHEMA` importable with pyramid-specific params (max_levels, stop_atr_mult, trail_atr_mult, trail_lookback, kelly_fraction, entry_conf_threshold).

## 2. Create strategy registry

- [x] 2.1 Create `src/strategies/registry.py` with `StrategyInfo` dataclass and lazy discovery logic. Scan `src/strategies/*.py` for modules with both `create_*_engine` and `PARAM_SCHEMA`. Cache results in a module-level singleton. Acceptance: `get_all()` returns `{"atr_mean_reversion": StrategyInfo(...), "pyramid_wrapper": StrategyInfo(...)}`.

- [x] 2.2 Implement `get_schema(slug)` that returns `{"strategy": str, "parameters": dict, "meta": dict}`. Acceptance: `get_schema("atr_mean_reversion")` returns a dict with all param entries from `PARAM_SCHEMA`.

- [x] 2.3 Implement `get_active_params(slug)` that merges TOML overrides (via `param_loader.load_strategy_params`) over `PARAM_SCHEMA` defaults. Acceptance: without TOML file returns defaults; with partial TOML returns merged values.

- [x] 2.4 Implement `get_param_grid(slug)` that extracts `"grid"` from each `PARAM_SCHEMA` entry (falling back to `[default]` if no grid). Acceptance: returns dict with grid arrays matching `CURATED_PARAM_GRIDS` shape.

- [x] 2.5 Implement `register(slug, module, factory, param_schema, meta)` for explicit registration. Acceptance: after `register("pyramid", ...)`, `get_schema("pyramid")` works.

- [x] 2.6 Implement `validate_schemas()` that checks each strategy's `PARAM_SCHEMA` keys against factory kwargs. Acceptance: returns empty list for consistent strategies, error strings for mismatches.

## 3. Migrate TOML configs

- [x] 3.1 Create `src/strategies/configs/pyramid.toml` from the `[pyramid]` section of `default.toml`. Acceptance: `load_strategy_params("pyramid")` returns the same values as before.

- [x] 3.2 Delete `src/strategies/configs/default.toml`. Update `_load_default_pyramid_params()` in `facade.py` to call `load_strategy_params("pyramid")` instead of `load_strategy_params("default")`. Acceptance: existing pyramid backtest produces identical results.

## 4. Refactor facade.py

- [x] 4.1 Delete `_atr_mr_schema()` and `_pyramid_schema()` (~90 lines). Replace `get_strategy_parameter_schema()` body with a call to `registry.get_schema(strategy)`. Add `_scenario_descriptions()` to the schema output. Acceptance: MCP `get_parameter_schema` tool returns identical JSON structure for both strategies.

- [x] 4.2 Replace `_load_default_pyramid_params()` with a call to `registry.get_active_params("pyramid")`. Acceptance: `_build_pyramid_config()` still returns correct `PyramidConfig`.

## 5. Refactor helpers.py

- [x] 5.1 Delete `CURATED_PARAM_GRIDS` dict. Modify `get_param_grid_for_strategy()` to call `registry.get_param_grid(slug)`. Acceptance: dashboard optimizer grid inputs show the same values as before.

- [x] 5.2 Replace `discover_strategies()` body with a wrapper around `registry.get_all()`. Keep `StrategyInfo` dataclass and `STRATEGY_REGISTRY` dict for backward compatibility. Acceptance: `STRATEGY_REGISTRY` dict has the same keys and shape as before.

## 6. Tests

- [x] 6.1 Add `tests/test_strategy_registry.py`: test auto-discovery finds `atr_mean_reversion`, `get_schema` returns correct structure, `get_active_params` merges TOML overrides, `get_param_grid` extracts grid values, `validate_schemas` returns empty for consistent strategies.

- [x] 6.2 Add a test that validates `PARAM_SCHEMA` keys match factory kwargs for all discovered strategies (the schema-factory consistency check). Acceptance: test passes for all strategies in `src/strategies/`.

- [x] 6.3 Verify existing tests still pass (`pytest tests/`). Acceptance: all existing tests green, no regressions.
