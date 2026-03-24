## ADDED Requirements

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

## MODIFIED Requirements

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
