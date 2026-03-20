## Context

The quant engine dashboard (Dash 4+, dark terminal theme) has 5 primary tabs: Data Hub, Strategy, Backtest, Optimization, Trading. The user wants to edit strategy-relevant Python files directly in the browser — but only user-facing strategy code, NOT core system internals.

**Editable scope**: `src/strategies/` only. This directory contains user-authored policy implementations (entry, add, stop) and engine config files. Core modules (`src/core/types.py`, `src/core/position_engine.py`, `src/core/adapter.py`, `src/bar_simulator/`) are system code and must NOT be exposed.

## Goals / Non-Goals

**Goals:**
- Create `src/strategies/` with example policy implementations and config files
- Add a "Strategy" tab with an embedded Ace code editor scoped to `src/strategies/`
- Three-level validation on save (syntax, lint, engine instantiation with user strategies)
- Stale-backtest indicator when strategy files are modified

**Non-Goals:**
- No editing of `src/core/` or `src/bar_simulator/` (system internals)
- No LSP / autocompletion
- No git integration
- No live execution from the editor

## Decisions

### 1. New `src/strategies/` directory structure

**Decision**: Create a user-facing directory with clear separation from core:

```
src/strategies/
├── __init__.py
├── example_entry.py      # PyramidEntryPolicy example
├── example_add.py        # PyramidAddPolicy example
├── example_stop.py       # ChandelierStopPolicy example
└── configs/
    └── default.toml      # Engine config (max_loss, margin_limit, etc.)
```

**Why**: Users need a sandbox to write strategies without risk of breaking system internals. Each file implements one policy ABC from `src/core/policies.py`. The example files serve as templates — users copy and modify them.

**Policy ABC contract**: Each strategy file exports a class implementing `EntryPolicy`, `AddPolicy`, or `StopPolicy`. The engine validation step (Level 3) imports these and wires them into a `PositionEngine`.

### 2. Use `dash-ace` as the editor component

**Decision**: Use `dash-ace` (Ace Editor wrapper for Dash).

**Ace configuration**:
```
theme:  "monokai"
mode:   "python"
fontSize: 13
showGutter: True
wrapEnabled: True
```

### 3. Scoped file access — `src/strategies/` ONLY

**Decision**: The editor backend reads/writes files ONLY under `src/strategies/`. The `ALLOWED_DIRS` constant in `editor.py` changes from `[src/core/, src/bar_simulator/]` to `[src/strategies/]`.

**Why**: The user explicitly requested limited permissions. Exposing `types.py`, `adapter.py`, `position_engine.py` lets users break the system in ways they shouldn't. Strategy files are the correct abstraction boundary — users control *what* the engine does (entry/add/stop logic), not *how* the engine works.

### 4. Three-level validation on save

Same pipeline as before, but adapted for the new scope:

**Level 1 — Syntax check (`ast.parse`)**: Instant, runs before save.

**Level 2 — Ruff lint**: Runs after save via `subprocess.run([sys.executable, "-m", "ruff", ...])`.

**Level 3 — Engine validation**: Load user strategy modules from `src/strategies/`, instantiate `PositionEngine` with them. If instantiation succeeds → "Engine OK". If it fails → show error. This validates that user-authored policies conform to the ABC contract.

**Reload implementation** changes: Instead of reloading `src.core.*`, we reload `src.strategies.*` modules and then try to instantiate `PositionEngine` using the user-defined policies.

### 5. Config files in `src/strategies/configs/`

**Decision**: Store engine parameters as TOML files in `src/strategies/configs/`. The editor can edit these. The backtest tab reads the active config to build `PyramidConfig` and `EngineConfig`.

**default.toml example**:
```toml
[pyramid]
max_loss = 500000
max_levels = 4
stop_atr_mult = 1.5
trail_atr_mult = 3.0
entry_conf_threshold = 0.65
kelly_fraction = 0.25
margin_limit = 0.50

[engine]
max_loss = 500000
margin_limit = 0.50
trail_lookback = 22
```

### 6. Tab position unchanged

Data Hub → **Strategy** → Backtest → Optimization → Trading.

## Risks / Trade-offs

- **[User strategy errors]** → A broken strategy file means the engine can't instantiate. Mitigation: Level 3 validation catches this immediately on save; the editor shows the error.
- **[Import path complexity]** → `src/strategies/` modules need to import from `src/core/policies` for ABCs and `src/core/types` for type hints. This is safe since users only extend, never modify, those modules.
- **[dash-ace maintenance]** → Same as before; fallback is vendored Ace via `app.index_string`.
- **[Config format]** → TOML is human-readable and the editor can syntax-highlight it (Ace has a TOML mode). Python dicts would also work but TOML is cleaner for config.
