## Why

Currently, modifying strategy logic requires editing Python source files in an IDE and restarting the dashboard. An embedded code editor lets users iterate on strategy code directly in the browser, combined with the Backtest and Optimization tabs.

However, the editor must NOT expose core system internals (`src/core/types.py`, `src/core/adapter.py`, `src/core/position_engine.py`, `src/bar_simulator/`). Users should only control strategy performance through a well-defined surface: custom policy implementations and engine configuration files inside dedicated user-facing directories.

## What Changes

- **Create `src/strategies/` directory** with example strategy files implementing `EntryPolicy`, `AddPolicy`, and `StopPolicy`. These are the user-editable building blocks. Include a few starter examples (pyramid entry, chandelier stop, no-add passthrough).
- **Create `src/strategies/configs/` directory** with TOML/Python config files for PositionEngine parameterization (max_loss, margin_limit, stop_atr_mult, etc.) so users can tune engine behavior without touching engine internals.
- **Restrict the code editor** to ONLY `src/strategies/` — not `src/core/` or `src/bar_simulator/`. The user has limited permission to control strategy performance, not the whole system logic.
- **Add a "Strategy" primary tab** to the dashboard navigation (5 tabs: Data Hub, Strategy, Backtest, Optimization, Trading) with an embedded Ace code editor.
- **File browser sidebar** listing editable files from `src/strategies/` only.
- **Save-to-disk + validation** with syntax check, ruff lint, and engine validation (load user strategies, instantiate PositionEngine with them).

## Capabilities

### New Capabilities

- `code-editor`: Embedded code editor for the dashboard — file browsing, editing, saving Python source files from `src/strategies/` only.
- `strategies`: User-facing strategy directory with example policy implementations and engine configs.

### Modified Capabilities

- `dashboard`: Tab navigation gains a fifth primary tab "Strategy" between Data Hub and Backtest.

## Impact

- **Code**: `src/dashboard/app.py` — `build_strategy_page()`, updated tab layout. `src/dashboard/callbacks.py` — file-read/write callbacks. `src/dashboard/editor.py` — file I/O scoped to `src/strategies/`.
- **New directory**: `src/strategies/` with example entry/add/stop policy files and a configs subdirectory.
- **Dependencies**: `dash-ace` (already installed).
- **Security**: File writes scoped to `src/strategies/` only. Core engine, types, adapter, and bar_simulator are read-only system code — never exposed in the editor.
