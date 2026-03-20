## 1. Directory Restructure

- [x] 1.1 Rename `quant_engine/` → `src/` (git mv to preserve history)
- [x] 1.2 Move `src/config/` → top-level `config/` (TOML files out of package)
- [x] 1.3 Remove empty `src/config/` directory if it remains

## 2. Build Configuration

- [x] 2.1 Update `pyproject.toml`: add `[tool.hatch.build.targets.wheel] packages = ["src"]`
- [x] 2.2 Verify `uv pip install -e .` succeeds with the new layout

## 3. Import Rewrite — Source

- [x] 3.1 Replace all `quant_engine.` → `src.` in `src/core/` imports
- [x] 3.2 Replace all `quant_engine.` → `src.` in `src/adapters/` imports
- [x] 3.3 Replace all `quant_engine.` → `src.` in `src/data/` imports
- [x] 3.4 Replace all `quant_engine.` → `src.` in `src/prediction/` imports
- [x] 3.5 Replace all `quant_engine.` → `src.` in `src/execution/` imports
- [x] 3.6 Replace all `quant_engine.` → `src.` in `src/risk/` imports
- [x] 3.7 Replace all `quant_engine.` → `src.` in `src/simulator/` imports
- [x] 3.8 Replace all `quant_engine.` → `src.` in `src/pipeline/` imports
- [x] 3.9 Replace all `quant_engine.` → `src.` in `src/secrets/` imports
- [x] 3.10 Replace all `quant_engine.` → `src.` in `src/dashboard/` imports

## 4. Config Path Fix

- [x] 4.1 Update `_CONFIG_DIR` in `src/pipeline/config.py` to resolve to `<project_root>/config/`

## 5. Import Rewrite — Tests

- [x] 5.1 Replace all `quant_engine.` → `src.` in `tests/conftest.py`
- [x] 5.2 Replace all `quant_engine.` → `src.` in all `tests/test_*.py` files

## 6. Documentation

- [x] 6.1 Update `docs/STRUCTURE.md` to match the new directory layout

## 7. Verification

- [x] 7.1 Run `ruff check src/ tests/` — no import errors
- [x] 7.2 Run `pytest tests/` — all tests pass
