## Purpose

Bind optimization runs to the exact strategy code version via SHA-256 hashing, enabling automatic detection and deactivation of stale candidates when strategy code changes. This prevents parameters optimized against old code from being used with new code.

## Requirements

### Requirement: Strategy code hash utility
The system SHALL provide a `src/strategies/code_hash.py` module with two public functions: `strategy_file_path(slug: str) -> Path` and `compute_strategy_hash(slug: str) -> tuple[str, str]`. The module SHALL resolve slug aliases via the strategy registry before locating the file.

```python
def strategy_file_path(slug: str) -> Path:
    """Return the absolute Path to the strategy .py file for the given slug.
    Raises FileNotFoundError if the resolved path does not exist."""

def compute_strategy_hash(slug: str) -> tuple[str, str]:
    """Read the strategy file and return (sha256_hex, full_source_text).
    Raises FileNotFoundError if the strategy file cannot be found."""
```

#### Scenario: Hash is deterministic for unchanged file
- **WHEN** `compute_strategy_hash("pyramid")` is called twice without modifying the file
- **THEN** both calls SHALL return identical `(hash, source)` tuples

#### Scenario: Hash changes after file edit
- **WHEN** a strategy file is modified and `compute_strategy_hash` is called again
- **THEN** the returned hash SHALL differ from the pre-edit hash

#### Scenario: Slug alias resolved
- **WHEN** `strategy_file_path("pyramid")` is called and `pyramid` is an alias for `swing/trend_following/pyramid_wrapper`
- **THEN** the returned Path SHALL point to `src/strategies/swing/trend_following/pyramid_wrapper.py`

#### Scenario: Missing file raises FileNotFoundError
- **WHEN** `compute_strategy_hash("nonexistent_slug")` is called and no corresponding `.py` file exists
- **THEN** it SHALL raise `FileNotFoundError` with a message indicating the expected path

### Requirement: Code hash persisted with every optimization run
The system SHALL compute `(strategy_hash, strategy_code)` and persist both alongside metrics for every backtest run saved to `param_registry.db`. This applies to all three save paths: single backtest, real-data backtest, and parameter sweep.

#### Scenario: Hash stored on single backtest save
- **WHEN** `run_backtest` completes and calls `save_backtest_run()`
- **THEN** `param_runs.strategy_hash` SHALL contain the SHA-256 of the strategy file at run time
- **AND** `param_runs.strategy_code` SHALL contain the full source text of the strategy file

#### Scenario: Hash stored on sweep save
- **WHEN** `run_parameter_sweep` completes and calls `save_run()`
- **THEN** `param_runs.strategy_hash` and `param_runs.strategy_code` SHALL be populated identically to the single-backtest case

#### Scenario: Hash computation failure does not block save
- **WHEN** `compute_strategy_hash()` raises `FileNotFoundError` (e.g., strategy file deleted mid-run)
- **THEN** the run SHALL still be saved with `strategy_hash=NULL` and `strategy_code=NULL`
- **AND** no exception SHALL propagate to the caller

### Requirement: Stale candidate auto-deactivation on code change
The system SHALL detect when `write_strategy_file` changes a strategy's code hash and automatically deactivate any active `param_candidates` whose associated `param_runs` row has a different (non-NULL) hash.

#### Scenario: Active candidates deactivated after code change
- **WHEN** `write_strategy_file` writes new content that changes the SHA-256 of a strategy file
- **THEN** all active `param_candidates` linked to that strategy via `param_runs.strategy_hash != new_hash` SHALL have `is_active` set to `0`
- **AND** candidates linked to rows with `strategy_hash IS NULL` SHALL NOT be deactivated

#### Scenario: No deactivation when hash unchanged
- **WHEN** `write_strategy_file` writes content identical to the current file (same hash)
- **THEN** no candidates SHALL be deactivated

#### Scenario: Deactivation failure does not block write
- **WHEN** the deactivation step raises an unexpected exception
- **THEN** the file write SHALL still complete successfully
- **AND** the `write_strategy_file` response SHALL include a warning field indicating deactivation failed

#### Scenario: Stale count reported in response
- **WHEN** `write_strategy_file` deactivates one or more stale candidates
- **THEN** the response SHALL include `stale_candidates_deactivated: <count>`

### Requirement: Code hash mismatch detection
The system SHALL expose a `check_code_hash_match(strategy: str, current_hash: str) -> bool | None` method on `ParamRegistry` that compares the stored hash of the active candidate against the provided current hash.

#### Scenario: Hashes match returns True
- **WHEN** the active candidate's `param_runs.strategy_hash` equals `current_hash`
- **THEN** `check_code_hash_match` SHALL return `True`

#### Scenario: Hashes differ returns False
- **WHEN** the active candidate's `param_runs.strategy_hash` differs from `current_hash`
- **THEN** `check_code_hash_match` SHALL return `False`

#### Scenario: No active candidate or NULL hash returns None
- **WHEN** no active candidate exists, or the active run has `strategy_hash IS NULL`
- **THEN** `check_code_hash_match` SHALL return `None`
