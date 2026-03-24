## Why

The strategy directory (`src/strategies/`) is flat and unclassified — all strategies sit as top-level `.py` files with no grouping by timeframe or type. As we add more strategies (VWAP rubber band, EMA pullback, Donchian channel, etc.), this becomes unmanageable: the agent has no scaffold tool to generate correct boilerplate, `resolve_factory()` in `facade.py` maintains a hardcoded `_BUILTIN_FACTORIES` dict that must be manually updated for every new strategy, and session helpers (`_in_day_session`, `_in_force_close`) are duplicated across `ta_orb.py` and `atr_mean_reversion.py`. The `docs/strategies.md` already proposes a 2D taxonomy (timeframe × strategy-type) that the codebase doesn't yet reflect.

## What Changes

- **Restructure `src/strategies/`** into a nested directory tree: `intraday/breakout/`, `intraday/mean_reversion/`, `intraday/trend_following/`, `daily/breakout/`, `daily/trend_following/`, with `examples/` for existing example policies.
- **Extract shared utilities** into `src/strategies/_session_utils.py` (TAIFEX session boundaries, force-close helpers) and `src/strategies/_shared_indicators.py` (rolling ATR, BB, RSI, trend MA — currently duplicated in `atr_mean_reversion.py`).
- **Eliminate `_BUILTIN_FACTORIES`** from `facade.py`. Make `resolve_factory()` use the strategy registry (`src/strategies/registry.py`) as the single source of truth, removing the need to manually register new strategies.
- **Update `registry._discover()`** to use `rglob("*.py")` with relative-path slugs (e.g., `intraday/breakout/ta_orb`), supporting the new nested directory structure.
- **Update `validation.py` and `tools.py`** so `list_strategy_files()`, `read_strategy_file`, `write_strategy_file`, and `backup_strategy_file` all support path-like stems with subdirectories.
- **Add a `scaffold_strategy` MCP tool** that generates correct boilerplate (policy classes, factory function, `PARAM_SCHEMA`, `STRATEGY_META`) with the right naming convention so `discover_strategies()` immediately finds it.
- **Add a CLI scaffold command** (`python -m src.strategies.scaffold <slug>`) for human developers.
- **Add `StrategyCategory` and `StrategyTimeframe` enums** to `STRATEGY_META` for programmatic filtering and dashboard display.
- **Update the `add-new-strategy` SKILL.md** to reflect the new directory structure, scaffold tool, and removal of manual `_BUILTIN_FACTORIES` registration.

## Capabilities

### New Capabilities
- `strategy-scaffold`: MCP tool + CLI for generating strategy boilerplate with correct conventions, ensuring `discover_strategies()` auto-detects the new strategy immediately.

### Modified Capabilities
- `strategies`: Directory restructure to nested layout (timeframe/type), shared utilities extraction, `STRATEGY_META` enum fields for `category` and `timeframe`.
- `strategy-registry`: `_discover()` updated for recursive directory scanning; slug format changes from flat stem to path-like stem (`intraday/breakout/ta_orb`).
- `backtest-mcp-server`: `resolve_factory()` migrated from hardcoded map to registry-based lookup; new `scaffold_strategy` tool added; `read_strategy_file`/`write_strategy_file` updated for path-like stems.

## Impact

- **All strategy imports change**: `src.strategies.ta_orb` → `src.strategies.intraday.breakout.ta_orb`. Registry handles this transparently via `module` field in `StrategyInfo`.
- **Strategy slugs change**: `ta_orb` → `intraday/breakout/ta_orb` (or a flat alias). Existing TOML configs and `param_registry.db` entries use old slugs — need migration or alias mapping.
- **Dashboard strategy selector** in `helpers.py` / `run_strategy_backtest()` uses `_BUILTIN_FACTORIES` check — must switch to registry-based resolution.
- **No external API changes**: MCP tool names and schemas remain identical; only internal routing changes.
- **add-new-strategy SKILL.md**: Step 2 ("Register in `_BUILTIN_FACTORIES`") is removed entirely.
