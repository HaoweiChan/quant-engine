## Context

Strategy parameter metadata is currently scattered across three files:

1. **`src/mcp_server/facade.py`** — hardcoded `_atr_mr_schema()` and `_pyramid_schema()` functions return dicts with defaults, types, ranges, and descriptions. `_load_default_pyramid_params()` has its own fallback defaults. Adding a new strategy means adding a new `_*_schema()` function and extending the `if/elif` chain in `get_strategy_parameter_schema()`.

2. **`src/dashboard/helpers.py`** — `discover_strategies()` scans for factory functions and infers param types from signatures. A separate `CURATED_PARAM_GRIDS` dict hardcodes optimizer grid values per strategy. `StrategyInfo` dataclass holds the merged result.

3. **`src/strategies/param_loader.py`** — TOML save/load for optimized params. No schema awareness — it just reads/writes flat dicts.

The strategy files themselves (`atr_mean_reversion.py`) declare defaults only in their factory function signatures. Schema metadata (ranges, descriptions, grid values) lives nowhere near the strategy.

## Goals / Non-Goals

**Goals:**
- Each strategy module is the single source of truth for its parameter schema (types, defaults, ranges, descriptions, optimizer grid)
- A central registry auto-discovers strategies and serves schema to all consumers
- Adding a new strategy requires only editing the strategy file — no changes to facade, helpers, or MCP tools
- TOML config overrides (from optimizer) are merged transparently

**Non-Goals:**
- Changing how the optimizer runs or how the dashboard renders params
- Adding a database backend for params (TOML files are sufficient and human-editable)
- Changing factory function signatures or the `PositionEngine` wiring
- Migrating `PyramidConfig` dataclass away from `src/core/types`

## Decisions

### D1: Module-level `PARAM_SCHEMA` dict in strategy files

Each strategy module exports a `PARAM_SCHEMA: dict[str, dict]` at module level, where each key is a parameter name and each value contains `type`, `default`, `min`, `max`, `description`, and optionally `grid` (for optimizer).

**Why over alternatives:**
- **Alternative: decorator on factory function** — More magical, harder to introspect statically, and mypy can't check it.
- **Alternative: separate YAML/JSON schema files** — Splits the strategy across two files, harder to keep in sync. TOML configs already handle the override layer.
- **Alternative: introspect factory signature** — Already done in `discover_strategies()` but only gets types and defaults, not ranges/descriptions/grids.

A plain dict is the simplest, most readable, and requires zero new dependencies.

### D2: Optional `STRATEGY_META` dict for non-param metadata

Strategy modules may export `STRATEGY_META: dict` containing `recommended_timeframe`, `bars_per_day`, `presets`, etc. This replaces the hardcoded metadata block in `_atr_mr_schema()`.

### D3: New `src/strategies/registry.py` as the central hub

```
                    ┌──────────────────────┐
                    │   Strategy Files     │
                    │  atr_mean_reversion  │
                    │    PARAM_SCHEMA      │
                    │    STRATEGY_META     │
                    │    create_*_engine   │
                    └──────────┬───────────┘
                               │ discovered by
                    ┌──────────▼───────────┐
                    │  strategies/registry  │
                    │                      │
                    │  get_schema(slug)    │
                    │  get_defaults(slug)  │◄── configs/<slug>.toml
                    │  get_param_grid(slug)│    (TOML overrides)
                    │  get_active_params() │
                    │  get_all()           │
                    └──────────┬───────────┘
                               │ consumed by
              ┌────────────────┼────────────────┐
              ▼                ▼                 ▼
        facade.py        helpers.py         tools.py
   get_strategy_       STRATEGY_REGISTRY   get_parameter_
   parameter_schema    get_param_grid      schema (MCP)
```

The registry:
- Scans `src/strategies/*.py` on first access (lazy singleton)
- Looks for modules with both `create_*_engine` and `PARAM_SCHEMA`
- Merges TOML overrides from `configs/<slug>.toml` over `PARAM_SCHEMA` defaults
- Caches the result in memory

**Why not put this in `param_loader.py`:** `param_loader` is pure I/O (read/write TOML). The registry is discovery + schema + merge — different responsibility.

### D4: Per-strategy TOML files, not a single `default.toml`

Current `default.toml` contains only `[pyramid]`. We split to `pyramid.toml`. The naming convention is `configs/<slug>.toml` (matching strategy slug). `param_loader.py` already supports per-name files so no API change is needed.

### D5: Backward-compatible `_build_pyramid_config` in facade

The pyramid strategy is special — it uses `PyramidConfig` dataclass from `src/core/types` rather than flat kwargs. `_build_pyramid_config()` stays in facade but loads defaults from the registry instead of its own hardcoded dict. This keeps the existing `BacktestRunner` interface unchanged.

## Risks / Trade-offs

**[Module import order]** — `registry.py` imports strategy modules at discovery time. If a strategy module has a heavy import (e.g., `shioaji`), it will be loaded. Mitigation: discovery already happens in `helpers.discover_strategies()` today; no regression. Strategy files that require optional deps should guard imports.

**[PARAM_SCHEMA can drift from factory signature]** — The schema dict and factory kwargs could diverge if someone edits one without the other. Mitigation: add a unit test that validates `PARAM_SCHEMA` keys match the factory's keyword arguments (excluding `max_loss`).

**[Pyramid is special]** — The pyramid strategy lives in `src/core/position_engine.py`, not `src/strategies/`. Its schema must be registered differently. Mitigation: the registry allows explicit `register()` calls in addition to auto-discovery, or we create a thin `src/strategies/pyramid.py` wrapper that exports `PARAM_SCHEMA` and re-exports the factory.
