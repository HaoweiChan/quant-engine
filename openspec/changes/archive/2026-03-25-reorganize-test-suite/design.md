## Context

The `tests/` directory has grown organically over time, creating a fragmented test suite that is difficult to maintain and lacking coverage alignment with our defined `openspec/specs/`. Because we use a modular, one-way pipeline (Prediction Engine → Position Engine → Execution Engine) and independent sub-systems (Risk Monitor, Market Adapters), the tests should logically group by these boundaries. This allows developers to verify specific spec domains efficiently and sets up a structure where new specs mandate new, neatly categorized tests. E2E tests are also missing or loosely defined, which hurts our confidence in the platform's holistic operation.

## Goals / Non-Goals

**Goals:**
- Completely restructure the `tests/` directory to mirror the spec domains (e.g., `tests/prediction_engine/`, `tests/risk_monitor/`).
- Standardize the distinction between `unit`, `integration`, and `e2e` tests.
- Design meaningful E2E test scenarios that validate data flow from tick ingestion to order execution.
- Ensure all existing, valid tests are migrated to the new structure, and obsolete ones are purged.

**Non-Goals:**
- Writing complete test suites for 100% coverage in this single change. (This change establishes the *framework* and moves existing tests, writing a few high-value E2E test stubs).
- Changing the underlying testing tool (we will continue to use `pytest`).

## Decisions

**1. Directory Layout Strategy**
- **Decision:** The top-level `tests/` directory will be split by test phase: `tests/unit/`, `tests/integration/`, and `tests/e2e/`. Inside `unit/` and `integration/`, the directories will mirror the capability domains (e.g., `tests/unit/prediction_engine/`).
- **Rationale:** Separating by phase allows CI/CD to run fast unit tests constantly and slower integration/e2e tests on demand or prior to merges. Mirroring domains makes it immediately obvious if a spec lacks test coverage.
- **Alternative:** Splitting by domain first (`tests/prediction_engine/unit/`). This was rejected because it makes running phase-specific test suites in CI slightly more complex regarding pytest invocation.

**2. E2E Testing Approach**
- **Decision:** E2E tests will use the `MockGateway` (from `broker-gateway` spec) and synthetic historical data to run a localized, accelerated full-stack simulation, asserting on final output portfolios and execution logs.
- **Rationale:** E2E tests need to simulate real market conditions without risking actual capital or hitting real exchange rate limits. `MockGateway` provides a perfect, deterministic sink for orders.

**3. Dependency and Fixture Management**
- **Decision:** We will create a robust set of shared fixtures in `tests/conftest.py` that provide synthetic ticks, mock broker states, and scaffolded in-memory SQLite databases for `trading.db`.
- **Rationale:** Prevents duplicate setup code across the newly separated directories and standardizes the way we mock the `Position Engine` and `Risk Monitor` states.

## Risks / Trade-offs

- **[Risk]** Test restructuring might break current CI pipelines.
  - **Mitigation:** Update CI config `.github/workflows/` (or equivalent) in parallel with this change to point to the new paths and handle separated phase testing.
- **[Risk]** Some legacy tests may be too coupled to multiple domains to neatly fit in one folder.
  - **Mitigation:** Refactor these tests into proper `integration` tests, or break them down into smaller `unit` tests that target a single domain.
