## Purpose

A user-editable directory (`src/strategies/`) containing custom policy implementations and engine configuration files. This is the defined sandbox for strategy development — users extend the core policy ABCs here without touching system internals. The directory is the exclusive target of the dashboard code editor.

## Requirements

### Requirement: User-editable strategy directory
The project SHALL maintain a `src/strategies/` directory containing Python files that implement one or more of the core policy ABCs (`EntryPolicy`, `AddPolicy`, `StopPolicy`) and a `configs/` subdirectory for TOML engine configuration files.

#### Scenario: Example files are present
- **WHEN** the project is first set up
- **THEN** `src/strategies/` SHALL contain at least one example file for each policy type (`EntryPolicy`, `AddPolicy`, `StopPolicy`) to serve as templates

#### Scenario: Strategy files import from core only
- **WHEN** a strategy file is evaluated
- **THEN** it SHALL only import from `src.core.policies` (ABCs) and `src.core.types` (data types) — never from `src.core.position_engine` or `src.bar_simulator`

### Requirement: Engine config files
The `src/strategies/configs/` directory SHALL contain TOML files defining `PyramidConfig` and `EngineConfig` parameters (max_loss, margin_limit, stop_atr_mult, trail_atr_mult, etc.).

#### Scenario: Default config exists
- **WHEN** the project is first set up
- **THEN** `src/strategies/configs/default.toml` SHALL exist with all required fields for `PyramidConfig` and `EngineConfig` and inline comments explaining each parameter

### Requirement: Policy ABC compliance
All `.py` files in `src/strategies/` SHALL implement at least one of the policy ABCs from `src.core.policies`. Classes SHALL be instantiable with a `PyramidConfig` argument and SHALL implement all abstract methods.

#### Scenario: Strategy instantiation succeeds
- **WHEN** the engine validation pipeline runs
- **THEN** all strategy classes SHALL instantiate with a default `PyramidConfig` without raising exceptions
