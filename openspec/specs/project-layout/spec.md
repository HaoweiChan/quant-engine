## Purpose

Define the project directory structure and package layout conventions. Ensures consistent import paths, config file locations, and a clean separation between source code and configuration.

## Requirements

### Requirement: Package directory is src/
The project SHALL use `src/` as the top-level Python package directory, replacing the previous `quant_engine/` directory. All module imports SHALL use the `src.` prefix.

#### Scenario: Import resolution
- **WHEN** any module imports from the package (e.g., `from src.core.types import MarketSnapshot`)
- **THEN** the import SHALL resolve correctly to `src/core/types.py`

#### Scenario: Editable install
- **WHEN** the project is installed in editable mode via `uv pip install -e .`
- **THEN** the `src` package SHALL be importable and all submodules SHALL be accessible

### Requirement: Config directory at project root
The project SHALL store all TOML configuration files in a top-level `config/` directory, not inside the package.

#### Scenario: Config loading
- **WHEN** `load_engine_config()` is called without an explicit path
- **THEN** it SHALL load from `<project_root>/config/engine.toml`

#### Scenario: Config files present
- **WHEN** the project is checked out
- **THEN** `config/` SHALL contain `engine.toml`, `prediction.toml`, `secrets.toml`, and `taifex.toml`

### Requirement: Tests directory structure
The project SHALL organize tests in a top-level `tests/` directory containing `unit/`, `integration/`, and `e2e/` subdirectories. Inside these subdirectories, test files SHALL be organized in paths that mirror the `openspec/specs/` capability domains (e.g., `tests/unit/prediction_engine/`).

#### Scenario: Running unit tests
- **WHEN** developers execute `pytest tests/unit/`
- **THEN** only unit tests isolated from external systems and databases SHALL run

#### Scenario: Running E2E tests
- **WHEN** developers execute `pytest tests/e2e/`
- **THEN** E2E test scenarios simulating full system flows SHALL execute

#### Scenario: Test file placement
- **WHEN** a developer adds a new test for the position engine
- **THEN** it SHALL be placed inside `tests/unit/position_engine/` or `tests/integration/position_engine/` depending on scope

### Requirement: No quant_engine/ directory
After refactoring, there SHALL be no `quant_engine/` directory at the project root. The package directory SHALL be `src/`.

#### Scenario: Directory structure
- **WHEN** listing the project root
- **THEN** the source package SHALL be at `src/` and `quant_engine/` SHALL NOT exist