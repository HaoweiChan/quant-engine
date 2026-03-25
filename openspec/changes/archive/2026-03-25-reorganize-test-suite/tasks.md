## 1. Directory Restructuring

- [x] 1.1 Create top-level `tests/unit/`, `tests/integration/`, and `tests/e2e/` directories.
- [x] 1.2 Create domain-specific subdirectories inside `tests/unit/` and `tests/integration/` mirroring `openspec/specs/` (e.g., `prediction_engine`, `position_engine`, `execution_engine`, `risk_monitor`).
- [x] 1.3 Create a central `tests/conftest.py` file to hold shared pytest fixtures.

## 2. Shared Fixtures Setup

- [x] 2.1 Implement `in_memory_db` and `temp_db` fixtures in `tests/conftest.py` to provide clean SQLite database instances for testing.
- [x] 2.2 Implement `mock_market_data` fixture to provide deterministic synthetic OHLCV DataFrames (using polars).
- [x] 2.3 Implement `mock_gateway` fixture that instantiates a `MockGateway` for execution tests.

## 3. Legacy Test Audit and Migration

- [x] 3.1 Review all existing files in the current `tests/` directory to identify valid test logic.
- [x] 3.2 Move valid unit test logic into corresponding `tests/unit/<domain>/` files. Refactor imports and paths as necessary.
- [x] 3.3 Move valid integration test logic into `tests/integration/<domain>/` files.
- [x] 3.4 Delete legacy test files that are obsolete, redundant, or explicitly test behaviors removed from the current specs.

## 4. E2E Pipeline Implementation

- [x] 4.1 Create `tests/e2e/test_trading_pipeline.py`.
- [x] 4.2 Write E2E test: `test_full_synthetic_session`. This should initialize a `TradingSession`, feed it deterministic synthetic ticks, and assert the final `SessionSnapshot` equity and open positions match an expected deterministic outcome using `MockGateway`.
- [x] 4.3 Write E2E test: `test_risk_halt_scenario`. This should intentionally trigger a massive drawdown in the simulation and verify the `RiskMonitor` properly transitions the session to `STOPPED` and emits a `CLOSE_ALL` alert.

## 5. Verification and CI Updates

- [x] 5.1 Run `pytest tests/unit/` locally and ensure all tests pass and coverage is accurate.
- [x] 5.2 Run `pytest tests/integration/` locally and ensure success.
- [x] 5.3 Run `pytest tests/e2e/` locally and verify the full pipeline successfully executes.
- [x] 5.4 Update any CI configuration files (e.g., GitHub Actions workflows) to invoke these three test paths distinctly.