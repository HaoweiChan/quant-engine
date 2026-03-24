## Context

The strategy directory (`src/strategies/`) currently holds 10 flat files. Two real strategies (`ta_orb.py`, `atr_mean_reversion.py`) duplicate session helpers, three `example_*.py` files have no factory or schema, and `pyramid_wrapper.py` is a thin re-export. The MCP facade (`facade.py`) maintains a hardcoded `_BUILTIN_FACTORIES` dict that must be updated manually for each new strategy. The strategy registry (`registry.py`) auto-discovers via `glob("*.py")` but `resolve_factory()` doesn't use it — creating a split-brain between dashboard and MCP resolution paths.

```
CURRENT RESOLUTION PATHS (split-brain)
═══════════════════════════════════════

MCP tools                           Dashboard
    │                                   │
    ▼                                   ▼
resolve_factory()                  discover_strategies()
    │                                   │
    ├─ _BUILTIN_FACTORIES (hardcoded)   ├─ registry._discover()
    ├─ "module:factory" fallback        │   glob("*.py") + PARAM_SCHEMA
    └─ error                            └─ STRATEGY_REGISTRY (module-level)
```

## Goals / Non-Goals

**Goals:**
- Unified strategy resolution: one code path for MCP, dashboard, and CLI
- Nested directory layout matching the timeframe × type taxonomy from `docs/strategies.md`
- Scaffold tool (MCP + CLI) that produces discoverable strategies on first write
- Eliminate manual `_BUILTIN_FACTORIES` maintenance
- Extract duplicated session/indicator code into shared modules

**Non-Goals:**
- Changing the `PositionEngine` or policy ABC interfaces
- Migrating existing `param_registry.db` data (slug aliases handle backward compat)
- Adding new strategies (only restructuring existing ones)
- Changing TOML config loading logic (beyond path adjustments)
- Multi-strategy portfolio orchestration

## Decisions

### D1: Directory layout — timeframe as first axis

```
src/strategies/
├── intraday/
│   ├── __init__.py
│   ├── breakout/
│   │   ├── __init__.py
│   │   └── ta_orb.py
│   ├── mean_reversion/
│   │   ├── __init__.py
│   │   └── atr_mean_reversion.py
│   └── trend_following/
│       └── __init__.py
├── daily/
│   ├── __init__.py
│   ├── breakout/
│   │   └── __init__.py
│   └── trend_following/
│       ├── __init__.py
│       └── pyramid_wrapper.py
├── examples/
│   ├── example_entry.py
│   ├── example_add.py
│   └── example_stop.py
├── _session_utils.py
├── _shared_indicators.py
├── registry.py
├── param_registry.py
├── param_loader.py
├── scaffold.py              ← NEW: scaffold tool + CLI
├── configs/
│   └── *.toml
└── __init__.py
```

**Why timeframe first?** Intraday and daily strategies have fundamentally different technical requirements (session boundaries, force-close logic, state reset, ATR source). Strategy type is the secondary grouping. This matches `docs/strategies.md` analysis.

**Alternative rejected:** Type first (`breakout/intraday/`, `breakout/daily/`). This groups strategies with different technical needs together while separating strategies that share session infrastructure.

### D2: Unified factory resolution — eliminate `_BUILTIN_FACTORIES`

```
AFTER: SINGLE RESOLUTION PATH
═══════════════════════════════

MCP / Dashboard / CLI
        │
        ▼
  resolve_factory(strategy_slug)
        │
        ├─ 1. registry.get_info(slug)        ← primary path
        │     imports module, returns factory
        │
        ├─ 2. _SLUG_ALIASES[slug]            ← backward compat
        │     maps old slug → new slug
        │     (e.g., "ta_orb" → "intraday/breakout/ta_orb")
        │
        ├─ 3. "module:factory" format         ← escape hatch
        │     for external strategies
        │
        └─ 4. raise ValueError                ← clear error
```

`_BUILTIN_FACTORIES` is removed entirely. The registry is the single source of truth.

**Slug alias map** for backward compatibility:
```python
_SLUG_ALIASES: dict[str, str] = {
    "ta_orb": "intraday/breakout/ta_orb",
    "atr_mean_reversion": "intraday/mean_reversion/atr_mean_reversion",
    "pyramid": "daily/trend_following/pyramid_wrapper",
}
```

This ensures existing MCP calls like `run_monte_carlo(strategy="ta_orb")` and existing `param_registry.db` entries continue to work.

### D3: Registry discovery — recursive scan with path-like slugs

`registry._discover()` changes from `glob("*.py")` to `rglob("*.py")`:

```python
for py in sorted(_STRATEGIES_DIR.rglob("*.py")):
    if py.name.startswith("_") or py.name == "__init__.py":
        continue
    # Skip infra modules at strategies root level
    if py.parent == _STRATEGIES_DIR and py.stem in _INFRA_MODULES:
        continue
    relative = py.relative_to(_STRATEGIES_DIR)
    slug = str(relative.with_suffix(""))  # e.g. "intraday/breakout/ta_orb"
    mod_name = f"src.strategies.{slug.replace('/', '.')}"
    ...
```

`_INFRA_MODULES` = `{"registry", "param_registry", "param_loader", "scaffold"}` — infrastructure files at root level that aren't strategies.

### D4: Enums for STRATEGY_META classification

```python
from enum import Enum

class StrategyCategory(str, Enum):
    BREAKOUT = "breakout"
    MEAN_REVERSION = "mean_reversion"
    TREND_FOLLOWING = "trend_following"

class StrategyTimeframe(str, Enum):
    INTRADAY = "intraday"
    DAILY = "daily"
    MULTI_DAY = "multi_day"
```

These live in `src/strategies/__init__.py` (or a `_types.py` file). Each strategy's `STRATEGY_META` is updated:

```python
STRATEGY_META = {
    "category": StrategyCategory.BREAKOUT,
    "timeframe": StrategyTimeframe.INTRADAY,
    "session": "day",
    "description": "...",
}
```

The registry and dashboard can filter strategies by enum values.

### D5: Scaffold tool — MCP + CLI dual interface

A single `src/strategies/scaffold.py` module provides:

1. **`scaffold_strategy()`** — pure function returning generated content + metadata
2. **MCP tool** — `scaffold_strategy` tool in `tools.py` that calls the function
3. **CLI** — `python -m src.strategies.scaffold <slug>` entry point

The scaffold generates:
- Policy classes (`EntryPolicy`, `StopPolicy`, optionally `AddPolicy`) with correct ABC method stubs
- `PARAM_SCHEMA` with placeholder params and grid hints
- `STRATEGY_META` with enum classification
- `create_<stem>_engine()` factory with correct signature matching `PARAM_SCHEMA`
- File placement in the correct subdirectory based on category + timeframe

```
scaffold_strategy(
    name="vwap_rubber_band",
    category=StrategyCategory.MEAN_REVERSION,
    timeframe=StrategyTimeframe.INTRADAY,
    description="VWAP deviation-based mean reversion scalper",
    policies=["entry", "stop"],   # auto-includes NoAddPolicy
    params={                      # optional initial params
        "vwap_dev_mult": {"type": "float", "default": 2.0, "min": 1.0, "max": 4.0},
    },
)
→ {
    "slug": "intraday/mean_reversion/vwap_rubber_band",
    "path": "src/strategies/intraday/mean_reversion/vwap_rubber_band.py",
    "content": "...",             # complete Python file
    "next_steps": ["write_strategy_file", "run_monte_carlo"],
}
```

### D6: Shared utilities extraction

**`_session_utils.py`** — TAIFEX session boundaries:
```python
def in_day_session(t: time) -> bool: ...
def in_night_session(t: time) -> bool: ...
def in_or_window(t: time) -> bool: ...
def in_force_close(t: time, mode: str = "default") -> bool: ...
```

**`_shared_indicators.py`** — rolling indicator state:
```python
class RollingATR: ...      # from atr_mean_reversion._Indicators
class RollingBB: ...       # Bollinger Bands
class RollingRSI: ...      # RSI
class RollingMA: ...       # simple moving average
```

Both use `_` prefix to be excluded from strategy discovery. Existing strategies are refactored to import from these shared modules.

### D7: Validation and file tools — path-like stems

`list_strategy_files()`:
```python
for p in sorted(_STRATEGIES_DIR.rglob("*.py")):
    if p.name.startswith("_") or p.name == "__init__.py":
        continue
    if p.parent == _STRATEGIES_DIR and p.stem in _INFRA_MODULES:
        continue
    relative_stem = str(p.relative_to(_STRATEGIES_DIR)).removesuffix(".py")
    # e.g. "intraday/breakout/ta_orb"
```

`write_strategy_file(filename="intraday/breakout/ta_orb", content=...)`:
- Resolves to `_STRATEGIES_DIR / "intraday/breakout/ta_orb.py"`
- Auto-creates parent directories: `mkdir(parents=True, exist_ok=True)`
- After write, invalidates registry cache: `registry.invalidate()`

`read_strategy_file`: same path-like stem resolution.

`backup_strategy_file`: preserves directory structure in `.backup/`.

## Risks / Trade-offs

**[Risk] Existing slug references break** → Mitigation: `_SLUG_ALIASES` dict maps all old slugs to new path-based slugs. Both `resolve_factory()` and `registry.get_info()` check aliases first. Migration is transparent — old `run_monte_carlo(strategy="ta_orb")` calls keep working.

**[Risk] `param_registry.db` has old slugs in `strategy` column** → Mitigation: The alias system works at the facade level. DB entries with old slugs remain valid. New entries use new slugs. A future migration can normalize the DB column, but it's not blocking.

**[Risk] `rglob` imports more modules than expected** → Mitigation: `_INFRA_MODULES` set explicitly excludes non-strategy root-level files. `_` prefix files are already excluded. Registry catches and logs import errors.

**[Risk] Scaffold generates stale boilerplate** → Mitigation: Scaffold reads the actual policy ABCs via `inspect` to verify method signatures. `validate_schemas()` catches schema-factory mismatches. Both are run as part of the scaffold's output validation.

**[Trade-off] Path-like slugs are longer** → The alternative (keep flat slugs even in nested dirs) creates ambiguity when two categories have the same filename. Path-like slugs are explicit and self-documenting.

## Migration Plan

1. **Phase 1 — Non-breaking prep**: Create `_session_utils.py`, `_shared_indicators.py`, scaffold module. Add enums. All additive — no file moves yet.
2. **Phase 2 — Directory restructure**: Create nested dirs, move strategy files, update `__init__.py` files. Update `registry._discover()` to use `rglob`.
3. **Phase 3 — Unify resolution**: Add `_SLUG_ALIASES` to `facade.py`. Replace `_BUILTIN_FACTORIES` with registry-based lookup. Update `helpers.py/run_strategy_backtest()`.
4. **Phase 4 — Update tooling**: Update `validation.py`, `tools.py` for path-like stems. Add `scaffold_strategy` MCP tool and CLI.
5. **Phase 5 — Update docs**: Update `add-new-strategy` SKILL.md, `docs/strategies.md`.

Rollback: Each phase is independently revertible via git. Phase 2 (the file move) is the riskiest; reverting it restores the flat layout while keeping all other improvements.

## Open Questions

- **Flat slug aliases — how long do we keep them?** Suggest: indefinitely in code, but deprecation warning in logs after 6 months.
- **Should `examples/` be discoverable by the registry?** Currently they lack `PARAM_SCHEMA` and factories, so they'd be skipped. But should we add a flag like `discoverable: false` to their meta?
