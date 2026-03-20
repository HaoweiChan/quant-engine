## Context

The project directory is `quant-engine/` and the Python package lives at `quant-engine/quant_engine/` — a flat layout that creates confusing visual redundancy. The documented structure in `docs/STRUCTURE.md` describes a `src/quant_engine/` layout that was never adopted, plus several directories (`scripts/`, `notebooks/`, `data/`) that don't exist.

Current layout:

```
quant-engine/               ← project root (we're here in Cursor)
├── quant_engine/           ← redundant with project name
│   ├── core/
│   ├── prediction/
│   ├── adapters/
│   ├── config/             ← TOML configs inside the package
│   ├── data/
│   ├── execution/
│   ├── pipeline/
│   ├── risk/
│   ├── secrets/
│   ├── simulator/
│   └── dashboard/
├── tests/
├── docs/
└── openspec/
```

## Goals / Non-Goals

**Goals:**

- Eliminate the `quant-engine/quant_engine/` redundancy by renaming the package dir to `src/`
- Move config TOML files out of the package into top-level `config/`
- Update `docs/STRUCTURE.md` to match reality
- Keep all module interfaces and behavior unchanged

**Non-Goals:**

- Reorganizing modules internally (e.g., merging `risk/` into `core/`)
- Adding missing directories from STRUCTURE.md (`scripts/`, `notebooks/`, `data/`)
- Changing the build system (staying with hatchling)
- Restructuring tests into subdirectories

## Decisions

### 1. Rename `quant_engine/` → `src/`

The directory on disk becomes `src/`. All internal imports change from `quant_engine.xxx` to `src.xxx`.

**Why not `src/quant_engine/`?** Too many hierarchy levels. The user navigates this in Cursor daily — `src/core/types.py` is cleaner than `src/quant_engine/core/types.py`.

**Why `src` as a package name?** This is a personal quant engine, not a library published to PyPI. The import `from src.core.types import MarketSnapshot` reads fine for an application package. If we ever publish it, we'd rename then.

**Alternative considered:** Keep `quant_engine/` as-is. Rejected because the user finds the redundancy confusing and wants to fix it now.

### 2. Move config outside the package

Config TOML files (`engine.toml`, `prediction.toml`, `secrets.toml`, `taifex.toml`) move from `quant_engine/config/` → top-level `config/`.

**Why:** Config isn't code. Keeping it at the project root follows 12-factor conventions and makes it easy to find. The config loader in `pipeline/config.py` already uses `Path` resolution — we update the base path to `PROJECT_ROOT / "config"`.

**Config path resolution:** Define `PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent` (from `src/pipeline/config.py` → `src/pipeline/` → `src/` → project root). Then `_CONFIG_DIR = PROJECT_ROOT / "config"`.

### 3. Update pyproject.toml for hatchling

Configure hatchling to discover the `src` package:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src"]
```

This tells hatchling to include `src/` as a top-level package in the wheel.

### 4. Bulk import rewrite

All `quant_engine.` → `src.` across source and tests. This is mechanical — a find-and-replace operation. ~56 imports in source, ~55 in tests.

Target layout after refactoring:

```
quant-engine/
├── src/                    ← clean, no redundancy
│   ├── __init__.py
│   ├── core/
│   ├── prediction/
│   ├── adapters/
│   ├── data/
│   ├── execution/
│   ├── pipeline/
│   ├── risk/
│   ├── secrets/
│   ├── simulator/
│   └── dashboard/
├── config/                 ← TOML files, top-level
│   ├── engine.toml
│   ├── prediction.toml
│   ├── secrets.toml
│   └── taifex.toml
├── tests/
├── docs/
└── openspec/
```

## Risks / Trade-offs

**[`src` as package name is unconventional]** → Acceptable for a personal project. The name is short and clear. If the project ever needs to be published, rename `src/` → `quant_engine/` and do another bulk import rewrite.

**[Every import in every file changes]** → This is mechanical and low-risk. A single `sed`-style find-and-replace handles it. Tests verify nothing broke.

**[Editable installs need testing]** → After changing pyproject.toml, verify `uv pip install -e .` still works and imports resolve correctly.

**[Config path resolution changes]** → Only one file (`pipeline/config.py`) resolves config paths. Update the `_CONFIG_DIR` constant and verify all config loading still works.
