## ADDED Requirements

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
