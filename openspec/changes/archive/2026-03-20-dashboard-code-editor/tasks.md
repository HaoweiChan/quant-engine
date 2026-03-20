## 1. Dependencies and Spike

- [x] 1.1 Add `dash-ace` to `pyproject.toml` under the `dashboard` optional dependency group. Run `uv sync --extra dashboard` to install. **Verify**: `from dash_ace import DashAceEditor` imports without error.
- [x] 1.2 If `dash-ace` fails with Dash 4+, evaluate `dash-monaco-editor` as fallback. Document findings in this file. **Verify**: One editor component confirmed working.

## 2. Create `src/strategies/` Directory

- [x] 2.1 Create `src/strategies/__init__.py` with a module docstring explaining this is the user-editable strategies directory.
- [x] 2.2 Create `src/strategies/example_entry.py` — a `PyramidEntryPolicy` implementation that imports `EntryPolicy` ABC from `src.core.policies` and `PyramidConfig`, `MarketSnapshot`, `MarketSignal`, `EngineState`, `EntryDecision` from `src.core.types`. Include clear comments explaining what each method does and how users can customize it. **Verify**: File is importable and instantiates with a default `PyramidConfig`.
- [x] 2.3 Create `src/strategies/example_add.py` — a `PyramidAddPolicy` implementation following the same pattern. **Verify**: Importable and instantiates.
- [x] 2.4 Create `src/strategies/example_stop.py` — a `ChandelierStopPolicy` implementation following the same pattern. **Verify**: Importable and instantiates.
- [x] 2.5 Create `src/strategies/configs/default.toml` with `[pyramid]` and `[engine]` sections containing all `PyramidConfig` and `EngineConfig` fields with sensible defaults. Add comments explaining each parameter. **Verify**: File parses with `tomllib`.

## 3. Update File I/O and Validation Module

- [x] 3.1 Update `ALLOWED_DIRS` in `src/dashboard/editor.py` from `[src/core/, src/bar_simulator/]` to `[src/strategies/]`. Update `list_editable_files()` to include `.toml` files alongside `.py` files. **Verify**: `list_editable_files()` returns only `src/strategies/` files; `_validate_path("src/core/types.py")` raises ValueError.
- [x] 3.2 Update `validate_engine()` in `editor.py` to reload `src.strategies.*` modules (instead of `src.core.*`), import the user policy classes from them, and instantiate `PositionEngine`. **Verify**: Returns None for the example strategies; returns error if a strategy file is broken.
- [x] 3.3 Update `tests/test_editor_io.py` to reflect the new allowed dirs and strategy-based validation. **Verify**: `pytest tests/test_editor_io.py` passes.

## 4. Update Strategy Tab Layout

- [x] 4.1 Update `build_strategy_page()` in `app.py` to use the new `editor.list_editable_files()` which now returns `src/strategies/` files. Set Ace editor mode dynamically based on file extension (python for `.py`, toml for `.toml`). **Verify**: Strategy tab shows only strategies files; no `src/core/` or `src/bar_simulator/` visible.

## 5. Update Editor Callbacks

- [x] 5.1 Update the save callback to set Ace editor mode based on file extension (`.py` → python, `.toml` → toml). Skip syntax check and engine validation for `.toml` files. **Verify**: Saving a `.toml` file runs no Python validation; saving a `.py` file runs all three levels.
- [x] 5.2 Update the file-select callback to set Ace mode dynamically when loading a file. **Verify**: Opening a `.toml` file shows TOML highlighting; opening `.py` shows Python highlighting.

## 6. Fix Tab-Switch Bug

- [x] 6.1 Move `editor-file-select` and `editor-modified-files` `dcc.Store` components from `build_strategy_page()` to the persistent `app.layout` so they survive tab switches. **Verify**: Switching from Strategy to another tab and back preserves state; save callback doesn't reset active tab.

## 7. Polish and Lint

- [x] 7.1 Style the file browser sidebar items: hover highlight, selected state highlight, monospace font. **Verify**: Visual consistency with other dashboard sidebars.
- [x] 7.2 Run `ruff check src/dashboard/ src/strategies/` and ensure all code passes. **Verify**: Clean output.
