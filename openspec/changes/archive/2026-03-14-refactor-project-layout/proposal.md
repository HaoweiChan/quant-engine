## Why

The project lives in `quant-engine/` but the Python package is `quant-engine/quant_engine/` — a redundant nesting that makes navigation confusing. Additionally, `docs/structure.md` describes a layout (`src/quant_engine/`, top-level `config/`, `scripts/`, `notebooks/`) that diverges significantly from the actual codebase, creating stale documentation.

## What Changes

- **BREAKING**: Rename `quant_engine/` → `src/` — the package directory becomes `src/` directly under project root
- Update `pyproject.toml` build config to discover packages from `src/`
- Update all internal imports from `quant_engine.xxx` to `src.xxx` across source and tests
- Move `quant_engine/config/` → top-level `config/` (TOML config files shouldn't live inside the package)
- Update `docs/structure.md` to reflect the actual directory layout
- Update any other references (test imports, conftest paths)

## Capabilities

### New Capabilities

_None — this is a structural refactoring with no new behavioral capabilities._

### Modified Capabilities

_None — no spec-level requirements are changing. Module interfaces, types, and behavior remain identical. Only the directory layout and import paths change._

## Impact

- **All source files**: Import statements change from `quant_engine.*` to `src.*`
- **All test files**: Same import path changes
- **`pyproject.toml`**: Build system config update for new package location
- **`docs/structure.md`**: Full rewrite to match reality
- **`openspec/config.yaml`**: No change (specs reference module names, not import paths)
- **Config loading code**: Any code that reads from `quant_engine/config/` must be updated to read from `config/`
- **No behavioral changes**: All module interfaces, types, and logic remain identical
