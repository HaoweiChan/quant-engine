## Purpose

Define the testing architecture for the quant-engine platform. Ensures meaningful, domain-aligned coverage that corresponds to the `openspec/specs/` capability domains, with clear separation between unit, integration, and end-to-end test scopes.

## Requirements

### Requirement: Meaningful Test Architecture
The testing suite SHALL provide meaningful, domain-aligned coverage corresponding to `openspec/specs/`. Outdated, unorganized, or flaky tests that do not test currently specified behavior SHALL be removed.

#### Scenario: Unit tests align with specs
- **WHEN** developers write unit tests for the `position-engine`
- **THEN** the tests SHALL target the exact normative requirements (SHALL/MUST) defined in `openspec/specs/position-engine/spec.md`

#### Scenario: Integration tests verify module boundaries
- **WHEN** developers run integration tests for the `execution-engine`
- **THEN** the tests SHALL test the interaction between the `PositionManager` and `BrokerGateway` without hitting live market APIs

### Requirement: E2E Pipeline Testing
The test suite SHALL include End-to-End (E2E) tests that simulate the entire trading pipeline (Prediction -> Position -> Execution) over historical or synthetic market data.

#### Scenario: E2E simulation with MockGateway
- **WHEN** an E2E test runs a trading session
- **THEN** it SHALL use a `MockGateway` instance to simulate order fills and a `DataLayer` mock to feed synthetic bar data
- **AND** it SHALL assert the final equity curve and open positions match expected outcomes for a deterministic strategy

### Requirement: Shared Testing Fixtures
The testing suite SHALL utilize a robust set of shared `pytest` fixtures located in `tests/conftest.py`.

#### Scenario: Using database fixture
- **WHEN** a test requires a clean instance of `trading.db`
- **THEN** it SHALL use the `in_memory_db` or `temp_db` fixture that yields an initialized, schema-compliant SQLite connection
- **AND** the database SHALL be torn down or rolled back after the test completes
