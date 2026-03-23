## ADDED Requirements

### Requirement: save_optimization_run MCP tool
The server SHALL expose a `save_optimization_run` tool that persists parameter sweep results to the registry database.

```python
@app.tool()
async def save_optimization_run(
    strategy: str,
    symbol: str,
    objective: str,
    tag: str | None = None,
    notes: str | None = None,
) -> dict: ...
```

#### Scenario: Save after sweep
- **WHEN** `save_optimization_run` is called after a `run_parameter_sweep` has completed in the same session
- **THEN** the most recent sweep result SHALL be persisted to `param_registry.db` with full trial data
- **AND** the response SHALL include `run_id`, number of trials saved, and number of Pareto candidates extracted

#### Scenario: No recent sweep to save
- **WHEN** `save_optimization_run` is called but no sweep has been run in the current session
- **THEN** it SHALL return an error message indicating no sweep results are available

### Requirement: get_run_history MCP tool
The server SHALL expose a `get_run_history` tool that queries persisted optimization runs from the registry database.

```python
@app.tool()
async def get_run_history(
    strategy: str | None = None,
    limit: int = 10,
) -> dict: ...
```

#### Scenario: Query all runs for a strategy
- **WHEN** `get_run_history` is called with `strategy="atr_mean_reversion"`
- **THEN** it SHALL return the most recent runs for that strategy, each with `run_id`, `run_at`, `objective`, `best_params`, best metrics, `n_trials`, `tag`, and candidate count

#### Scenario: Query all strategies
- **WHEN** `get_run_history` is called without a strategy filter
- **THEN** it SHALL return runs across all strategies, sorted by `run_at` descending

### Requirement: activate_candidate MCP tool
The server SHALL expose an `activate_candidate` tool that marks a parameter candidate as active for production use.

```python
@app.tool()
async def activate_candidate(
    candidate_id: int,
) -> dict: ...
```

#### Scenario: Activate candidate
- **WHEN** `activate_candidate` is called with a valid candidate ID
- **THEN** that candidate SHALL become the active parameter set for its strategy
- **AND** the response SHALL confirm the strategy name, activated params, and timestamp

#### Scenario: Invalid candidate ID
- **WHEN** `activate_candidate` is called with a non-existent ID
- **THEN** it SHALL return an error message

### Requirement: get_active_params MCP tool
The server SHALL expose a `get_active_params` tool that returns the currently active optimized parameters for a strategy.

```python
@app.tool()
async def get_active_params(
    strategy: str = "pyramid",
) -> dict: ...
```

#### Scenario: Active params exist
- **WHEN** `get_active_params` is called with `strategy="atr_mean_reversion"` and an active candidate exists
- **THEN** it SHALL return `params`, `label`, `run_id`, `activated_at`, and the run's `objective` and `tag`

#### Scenario: No active params
- **WHEN** `get_active_params` is called and no candidate is active
- **THEN** it SHALL return the PARAM_SCHEMA defaults with a note indicating these are schema defaults, not optimized values

## MODIFIED Requirements

### Requirement: Session optimization history tracking
The server SHALL maintain optimization history in the persistent `param_registry.db` instead of an in-memory list. The `get_optimization_history` tool SHALL return all persisted runs, with an option to filter to the current session.

#### Scenario: History persists across restarts
- **WHEN** the MCP server is restarted
- **THEN** `get_optimization_history` SHALL still return all previously recorded runs from the database

#### Scenario: History append on run
- **WHEN** any simulation tool completes (run_backtest, run_monte_carlo, run_parameter_sweep, run_stress_test)
- **THEN** the run parameters, result metrics, tool name, and ISO timestamp SHALL be appended to session history
- **AND** for `run_parameter_sweep`, the full result SHALL also be persisted to the param registry

#### Scenario: History entry format
- **WHEN** a history entry is queried
- **THEN** it SHALL contain: `tool` (string), `params` (dict), `metrics` (dict), `scenario` (string), `timestamp` (ISO string), `strategy` (string), and optionally `run_id` (integer, if persisted to param registry)

### Requirement: run_parameter_sweep auto-persistence
The `run_parameter_sweep` tool SHALL automatically persist its results to the param registry database after completion, in addition to returning the result to the caller.

#### Scenario: Sweep results auto-saved
- **WHEN** `run_parameter_sweep` completes successfully
- **THEN** the full trial data SHALL be persisted to `param_registry.db` with `source="mcp"`
- **AND** the response SHALL include the `run_id` for later reference

#### Scenario: Sweep result includes candidates
- **WHEN** `run_parameter_sweep` completes and is persisted
- **THEN** the response SHALL include the best candidate and any Pareto-optimal candidates with their labels
