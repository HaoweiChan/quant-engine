## Why

Strategy parameter metadata (schemas, defaults, ranges, optimizer grids) is scattered across three consumer files: `src/mcp_server/facade.py` hardcodes per-strategy schema functions (`_atr_mr_schema`, `_pyramid_schema`), `src/dashboard/helpers.py` hardcodes `CURATED_PARAM_GRIDS`, and `src/strategies/param_loader.py` only handles TOML I/O with no awareness of schema. This means adding a new strategy requires editing three unrelated files, defaults can drift between the factory signature and the schema, and the MCP `get_parameter_schema` tool has a hardcoded `if/elif` chain that breaks for any new strategy.

## What Changes

- Each strategy module declares a `PARAM_SCHEMA` dict at module level — the single source of truth for parameter metadata (type, default, min/max, description, optimizer grid).
- A new `src/strategies/registry.py` module discovers strategies automatically (scanning for `create_*_engine` + `PARAM_SCHEMA`), merges TOML config overrides, and exposes `get_schema()`, `get_defaults()`, `get_param_grid()`, `get_active_params()`.
- `facade.py` deletes ~120 lines of hardcoded schemas (`_atr_mr_schema`, `_pyramid_schema`, `_load_default_pyramid_params`) and delegates to the registry.
- `helpers.py` deletes `CURATED_PARAM_GRIDS` and `discover_strategies()`, delegates to the registry.
- `configs/default.toml` is split into per-strategy files (`configs/pyramid.toml`). Existing `param_loader.py` save/load stays the same.

## Capabilities

### New Capabilities
- `strategy-registry`: Central registry that auto-discovers strategies, serves schema/defaults/param-grids, and merges TOML overrides. All consumers read from here instead of maintaining their own copies.

### Modified Capabilities
- `strategies`: Strategy files now export a `PARAM_SCHEMA` dict alongside their factory function.
- `strategy-param-persistence`: TOML config files shift from a single `default.toml` to per-strategy files (`<slug>.toml`). Save/load API unchanged.

## Impact

- **Code removed**: ~120 lines from `facade.py`, ~15 lines from `helpers.py`
- **Code added**: ~80 lines (`registry.py` + `PARAM_SCHEMA` dicts in strategy files)
- **APIs**: `get_strategy_parameter_schema()` in `facade.py` keeps the same signature but delegates to registry. `STRATEGY_REGISTRY` in `helpers.py` keeps the same shape but is populated by the registry.
- **Breaking**: None — all public function signatures stay identical. Only internal wiring changes.
- **Files affected**: `src/strategies/atr_mean_reversion.py`, `src/strategies/registry.py` (new), `src/mcp_server/facade.py`, `src/dashboard/helpers.py`, `src/strategies/configs/`
