## Why

The current test files are outdated and unorganized, making it difficult to verify that the system correctly implements the behaviors defined in our source of truth (`openspec/specs/`). We need a structured, meaningful test suite that directly aligns with our defined specifications and includes robust end-to-end (E2E) tests to ensure cross-module coherence.

## What Changes

- Reorganizes the `tests/` directory structure to mirror the capability domains defined in `openspec/specs/` (e.g., `tests/prediction_engine/`, `tests/position_engine/`, `tests/execution_engine/`).
- Introduces a clear separation between `unit`, `integration`, and `e2e` test phases.
- **BREAKING**: Removes outdated, redundant, or flaky legacy test files that do not map to current specifications.
- Adds comprehensive E2E test stubs that simulate the full pipeline from data ingestion to execution.

## Capabilities

### New Capabilities
- `testing-suite`: Defines the overarching testing architecture, organization requirements, and E2E flow testing strategies to ensure all code aligns with `openspec/specs/`.

### Modified Capabilities
- `project-layout`: Modifying the project structure requirements to formally specify the new layout of the `tests/` directory.

## Impact

- All existing test files in `tests/` will be audited, moved, or removed.
- CI/CD pipelines will be updated to run the newly structured test phases (unit, integration, e2e) separately.
- Future development workflows will require new tests to be placed in paths corresponding to their spec domains.