## Purpose

Persistent SQLite-backed registry for optimization runs, trials, candidates, Pareto fronts, activation, and history so optimized parameters survive restarts and integrate with the dashboard API and MCP tools.

## Requirements

### Requirement: SQLite parameter registry database
The system SHALL provide a `param_registry.db` SQLite database located alongside `taifex_data.db` in the project root, containing three tables: `param_runs`, `param_trials`, and `param_candidates`. The database location SHALL be overridable via the `PARAM_REGISTRY_DB` environment variable. Tables SHALL be created automatically on first access.

```python
class ParamRegistry:
    def __init__(self, db_path: Path | None = None) -> None: ...
    def save_run(
        self,
        result: OptimizerResult,
        strategy: str,
        symbol: str,
        objective: str,
        train_start: str | None = None,
        train_end: str | None = None,
        test_start: str | None = None,
        test_end: str | None = None,
        is_fraction: float = 0.8,
        search_type: str = "grid",
        source: str = "cli",
        tag: str | None = None,
        notes: str | None = None,
    ) -> int: ...
    def save_candidate(
        self, run_id: int, trial_id: int | None, params: dict,
        label: str, regime: str | None = None, notes: str | None = None,
    ) -> int: ...
    def activate(self, candidate_id: int) -> None: ...
    def get_active(self, strategy: str) -> dict[str, Any] | None: ...
    def get_pareto_frontier(
        self, run_id: int, objectives: list[str] | None = None,
    ) -> list[dict]: ...
    def get_run_history(
        self, strategy: str, limit: int = 20,
    ) -> list[dict]: ...
    def compare_runs(self, run_ids: list[int]) -> list[dict]: ...
```

#### Scenario: Database created on first access
- **WHEN** `ParamRegistry()` is instantiated and `param_registry.db` does not exist
- **THEN** the file SHALL be created with all three tables and indexes

#### Scenario: Custom DB path via environment variable
- **WHEN** `PARAM_REGISTRY_DB` is set to `/tmp/test_params.db`
- **THEN** `ParamRegistry()` SHALL use that path instead of the default project root location

#### Scenario: Tables already exist
- **WHEN** `ParamRegistry()` is instantiated and tables already exist
- **THEN** no error SHALL occur and existing data SHALL be preserved

### Requirement: Save optimization run with full trial data
`ParamRegistry.save_run()` SHALL persist the complete `OptimizerResult` — inserting one `param_runs` row for the run metadata and one `param_trials` row for each trial in the trials DataFrame. It SHALL return the `run_id` of the inserted run. The best trial SHALL automatically be saved as a candidate with label `best_{objective}`.

#### Scenario: Grid search result saved
- **WHEN** `save_run()` is called with an `OptimizerResult` containing 100 trials
- **THEN** 1 row SHALL be inserted into `param_runs` and 100 rows into `param_trials`
- **AND** the return value SHALL be the integer `run_id`

#### Scenario: Best candidate auto-created
- **WHEN** `save_run()` completes with `objective="sharpe"`
- **THEN** a `param_candidates` row SHALL be created with `label="best_sharpe"` and the best trial's params

#### Scenario: OOS metrics stored separately
- **WHEN** `save_run()` is called with an `OptimizerResult` that has `best_oos_result`
- **THEN** the OOS metrics SHALL be stored in a separate `param_trials` row with `is_oos=1`

#### Scenario: Run metadata preserved
- **WHEN** `save_run()` is called with `strategy="atr_mean_reversion"`, `symbol="TX"`, `tag="bull_2025"`
- **THEN** the `param_runs` row SHALL contain these exact values plus the ISO timestamp of the run

### Requirement: Pareto frontier extraction
`ParamRegistry.get_pareto_frontier()` SHALL compute the Pareto-optimal set of trials for a given run across specified objectives. A trial is Pareto-optimal if no other trial dominates it (equal or better on all objectives, strictly better on at least one). The default objectives SHALL be `["sharpe", "calmar"]`.

#### Scenario: Pareto frontier with two objectives
- **WHEN** `get_pareto_frontier(run_id=1, objectives=["sharpe", "calmar"])` is called
- **THEN** it SHALL return a list of dicts, each containing the trial's `params`, `sharpe`, and `calmar` values
- **AND** no returned trial SHALL be dominated by any other trial in the run

#### Scenario: Single-objective degenerates to best
- **WHEN** `get_pareto_frontier(run_id=1, objectives=["sharpe"])` is called
- **THEN** it SHALL return exactly one trial — the one with the highest Sharpe

#### Scenario: All trials on the frontier
- **WHEN** all trials have identical metric values
- **THEN** all trials SHALL be returned (none dominates another)

### Requirement: Auto-save Pareto candidates after run
After `save_run()` completes, the registry SHALL automatically compute the Pareto frontier for the default objectives and save each Pareto-optimal trial as a candidate with label format `pareto_sharpe{value:.2f}_calmar{value:.2f}`.

#### Scenario: Pareto candidates created on save
- **WHEN** `save_run()` completes and the Pareto frontier contains 3 non-dominated trials
- **THEN** 3 additional `param_candidates` rows SHALL be created with `pareto_` prefixed labels

#### Scenario: Large trial set warning
- **WHEN** `save_run()` is called with more than 5000 trials
- **THEN** Pareto extraction SHALL still execute but a warning SHALL be logged via structlog

### Requirement: Activate a parameter candidate
`ParamRegistry.activate()` SHALL set `is_active=1` on the specified candidate and `is_active=0` on all other candidates for the same strategy. The `activated_at` timestamp SHALL be set to the current ISO time.

#### Scenario: Activate deactivates previous
- **WHEN** `activate(candidate_id=5)` is called and candidate 5 is for strategy `atr_mean_reversion`
- **THEN** candidate 5 SHALL have `is_active=1` and `activated_at` set
- **AND** all other `atr_mean_reversion` candidates SHALL have `is_active=0`

#### Scenario: Activate non-existent candidate
- **WHEN** `activate(candidate_id=999)` is called and no such candidate exists
- **THEN** a `ValueError` SHALL be raised

### Requirement: Get active params for a strategy
`ParamRegistry.get_active()` SHALL return the `params` dict of the currently active candidate for the given strategy. If no active candidate exists, it SHALL return `None`.

#### Scenario: Active candidate exists
- **WHEN** `get_active("atr_mean_reversion")` is called and an active candidate exists
- **THEN** it SHALL return the candidate's `params` as a `dict[str, Any]`

#### Scenario: No active candidate
- **WHEN** `get_active("atr_mean_reversion")` is called and no candidate has `is_active=1`
- **THEN** it SHALL return `None`

#### Scenario: Active params reflect most recent activation
- **WHEN** candidate A is activated, then candidate B is activated for the same strategy
- **THEN** `get_active()` SHALL return candidate B's params

### Requirement: Query run history
`ParamRegistry.get_run_history()` SHALL return a list of past runs for a strategy, sorted by `run_at` descending, limited to the specified count. Each entry SHALL include run metadata, best trial metrics, and the count of associated candidates. The method SHALL also accept an optional `search_type` filter to include or exclude single backtest runs.

#### Scenario: History returns most recent runs first
- **WHEN** `get_run_history("atr_mean_reversion", limit=5)` is called with 10 runs in the DB
- **THEN** it SHALL return the 5 most recent runs sorted by `run_at` descending

#### Scenario: Empty history
- **WHEN** `get_run_history("nonexistent_strategy")` is called
- **THEN** it SHALL return an empty list

#### Scenario: Filter by search type
- **WHEN** `get_run_history("ema_trend_pullback", search_type="single")` is called
- **THEN** it SHALL return only runs where `search_type="single"` (individual backtests)

#### Scenario: Default includes all search types
- **WHEN** `get_run_history("ema_trend_pullback")` is called without a `search_type` filter
- **THEN** it SHALL return both sweep runs and single backtest runs

### Requirement: Save single backtest run
`ParamRegistry.save_backtest_run()` SHALL persist a single backtest result (not a full optimization sweep) to the database. It SHALL insert one `param_runs` row with `search_type="single"` and `n_trials=1`, and one `param_trials` row with the result metrics. It SHALL NOT auto-create candidates or compute Pareto frontiers. It SHALL return the `run_id`.

```python
def save_backtest_run(
    self,
    strategy: str,
    symbol: str,
    params: dict[str, Any],
    metrics: dict[str, Any],
    source: str = "mcp",
    tool: str = "run_backtest",
    tag: str | None = None,
    notes: str | None = None,
) -> int: ...
```

#### Scenario: Single backtest persisted
- **WHEN** `save_backtest_run()` is called with `strategy="intraday/trend_following/ema_trend_pullback"`, params `{"lots": 4}`, and metrics `{"sharpe": 1.559, "total_pnl": 1520000}`
- **THEN** 1 row SHALL be inserted into `param_runs` with `search_type="single"`, `n_trials=1`, `source="mcp"`
- **AND** 1 row SHALL be inserted into `param_trials` with the given metrics and `is_oos=0`
- **AND** the return value SHALL be the integer `run_id`

#### Scenario: No candidate auto-creation
- **WHEN** `save_backtest_run()` completes
- **THEN** no `param_candidates` rows SHALL be created (single runs are exploratory, not optimization results)

#### Scenario: Tool name recorded
- **WHEN** `save_backtest_run()` is called with `tool="run_backtest_realdata"`
- **THEN** the `param_runs` row SHALL store the tool name in the `tag` field prefixed with `tool:` (e.g., `tag="tool:run_backtest_realdata"`)

#### Scenario: Persistence failure does not raise
- **WHEN** `save_backtest_run()` encounters a database error
- **THEN** it SHALL log the error via structlog and return `-1` instead of raising an exception

### Requirement: Strategy name normalization on write
All `ParamRegistry` write methods (`save_run`, `save_backtest_run`, `save_candidate`) SHALL accept only normalized strategy slugs (e.g., `intraday/trend_following/ema_trend_pullback`). Callers are responsible for normalizing before calling. The registry SHALL validate that the strategy string does not contain `:` or start with `src.` and SHALL raise `ValueError` if it does.

#### Scenario: Reject module:factory format
- **WHEN** `save_run()` is called with `strategy="src.strategies.intraday.trend_following.ema_trend_pullback:create_ema_trend_pullback_engine"`
- **THEN** it SHALL raise `ValueError` with a message indicating the strategy must be a normalized slug

#### Scenario: Accept valid slug
- **WHEN** `save_run()` is called with `strategy="intraday/trend_following/ema_trend_pullback"`
- **THEN** it SHALL proceed normally without error

#### Scenario: Accept legacy alias
- **WHEN** `save_run()` is called with `strategy="atr_mean_reversion"`
- **THEN** it SHALL proceed normally (legacy aliases are valid identifiers, though callers SHOULD normalize to full slugs)

### Requirement: One-time strategy name migration
`ParamRegistry.__init__()` SHALL check for rows in `param_runs` and `param_candidates` where the `strategy` column contains `:` (module:factory format). For each such row, it SHALL attempt to resolve the strategy to a canonical slug and update the column. The migration SHALL be idempotent and logged via structlog.

#### Scenario: Module:factory names migrated
- **WHEN** `ParamRegistry()` is instantiated and `param_runs` contains a row with `strategy="src.strategies.intraday.trend_following.ema_trend_pullback:create_ema_trend_pullback_engine"`
- **THEN** the `strategy` column SHALL be updated to `"intraday/trend_following/ema_trend_pullback"`
- **AND** the corresponding `param_candidates` rows SHALL also be updated

#### Scenario: Already-normalized rows unchanged
- **WHEN** `ParamRegistry()` is instantiated and all `strategy` values are already valid slugs
- **THEN** no rows SHALL be modified

#### Scenario: Unresolvable names left unchanged
- **WHEN** a `strategy` value contains `:` but cannot be resolved to a known slug
- **THEN** the row SHALL be left unchanged and a warning SHALL be logged

### Requirement: Compare runs
`ParamRegistry.compare_runs()` SHALL accept a list of run IDs and return their best trial metrics side-by-side for comparison.

#### Scenario: Compare two runs
- **WHEN** `compare_runs([1, 2])` is called
- **THEN** it SHALL return a list of dicts, one per run, each containing `run_id`, `run_at`, `objective`, `best_params`, and the best trial's metric values

#### Scenario: Non-existent run ID
- **WHEN** `compare_runs([1, 999])` is called and run 999 does not exist
- **THEN** the result SHALL contain only the data for run 1 (invalid IDs silently skipped)
