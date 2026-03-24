## ADDED Requirements

### Requirement: Strategy slug normalization in facade
The facade module SHALL provide a `resolve_strategy_slug(strategy: str) -> str` function that converts any strategy identifier to its canonical registry slug. All facade functions that persist results to `param_registry.db` SHALL call this function before writing.

```python
def resolve_strategy_slug(strategy: str) -> str:
    """Resolve any strategy identifier to its canonical registry slug.

    Handles: slug, legacy alias, module:factory format.
    Falls back to the raw string if resolution fails.
    """
    ...
```

#### Scenario: Slug passes through unchanged
- **WHEN** `resolve_strategy_slug("intraday/trend_following/ema_trend_pullback")` is called
- **THEN** it SHALL return `"intraday/trend_following/ema_trend_pullback"`

#### Scenario: Legacy alias resolved
- **WHEN** `resolve_strategy_slug("ta_orb")` is called
- **THEN** it SHALL return `"intraday/breakout/ta_orb"`

#### Scenario: Module:factory format resolved
- **WHEN** `resolve_strategy_slug("src.strategies.intraday.trend_following.ema_trend_pullback:create_ema_trend_pullback_engine")` is called
- **THEN** it SHALL return `"intraday/trend_following/ema_trend_pullback"`

#### Scenario: Unknown strategy falls back
- **WHEN** `resolve_strategy_slug("unknown_strategy")` is called and no registry entry exists
- **THEN** it SHALL return `"unknown_strategy"` unchanged

## MODIFIED Requirements

### Requirement: run_backtest tool
The server SHALL expose a `run_backtest` tool that runs a single backtest on synthetic price data and returns performance metrics. The result SHALL be persisted to `param_registry.db` via `ParamRegistry.save_backtest_run()` with `source="mcp"` and the strategy identifier normalized to a slug.

```python
@app.tool()
async def run_backtest(
    scenario: str,
    strategy_params: dict | None = None,
    strategy: str = "pyramid",
    date_range: dict | None = None,
) -> dict: ...
```

#### Scenario: Backtest with preset scenario
- **WHEN** `run_backtest` is called with `scenario="strong_bull"`
- **THEN** it SHALL generate a synthetic price path using the `strong_bull` PathConfig preset, run BacktestRunner with the specified strategy factory, and return metrics including sharpe, max_drawdown, win_rate, total_pnl, and trade_count

#### Scenario: Backtest with custom parameters
- **WHEN** `run_backtest` is called with `strategy_params={"stop_atr_mult": 2.0}`
- **THEN** it SHALL merge the provided params with defaults and run the backtest with the merged config

#### Scenario: Invalid scenario name
- **WHEN** `run_backtest` is called with an unknown scenario name
- **THEN** it SHALL return an error with the list of valid scenario names

#### Scenario: Result recorded in history
- **WHEN** a backtest completes successfully
- **THEN** the result SHALL be appended to the session optimization history

#### Scenario: Result persisted to param registry
- **WHEN** a backtest completes successfully
- **THEN** the result metrics and strategy params SHALL be persisted to `param_registry.db` via `ParamRegistry.save_backtest_run()` with `source="mcp"` and the strategy slug normalized via `resolve_strategy_slug()`
- **AND** the response SHALL include the `run_id` from the registry

#### Scenario: Persistence failure does not block response
- **WHEN** a backtest completes but `save_backtest_run()` fails
- **THEN** the backtest result SHALL still be returned to the caller with `run_id=null`

### Requirement: run_backtest_realdata tool
The server SHALL expose a `run_backtest_realdata` tool that runs a backtest on real historical data from the database. The result SHALL be persisted to `param_registry.db` via `ParamRegistry.save_backtest_run()` with `source="mcp"` and the strategy identifier normalized to a slug. The `symbol` field SHALL record the actual market symbol (e.g., `"TX"`), not a synthetic label.

#### Scenario: Real-data backtest persisted
- **WHEN** `run_backtest_realdata` is called with `symbol="TX"`, `start="2025-08-01"`, `end="2026-03-14"`, `strategy="intraday/trend_following/ema_trend_pullback"`, and `strategy_params={"lots": 5}`
- **THEN** the result SHALL be persisted to `param_registry.db` with `strategy="intraday/trend_following/ema_trend_pullback"`, `symbol="TX"`, and the run metrics
- **AND** the response SHALL include the `run_id`

#### Scenario: Persistence uses normalized slug
- **WHEN** `run_backtest_realdata` is called with `strategy="src.strategies.intraday.trend_following.ema_trend_pullback:create_ema_trend_pullback_engine"`
- **THEN** the `strategy` stored in `param_registry.db` SHALL be `"intraday/trend_following/ema_trend_pullback"`

### Requirement: run_parameter_sweep auto-persistence
The `run_parameter_sweep` tool SHALL automatically persist its results to the param registry database after completion, in addition to returning the result to the caller. The strategy identifier SHALL be normalized to a slug before persistence.

#### Scenario: Sweep results auto-saved
- **WHEN** `run_parameter_sweep` completes successfully
- **THEN** the full trial data SHALL be persisted to `param_registry.db` with `source="mcp"`
- **AND** the response SHALL include the `run_id` for later reference

#### Scenario: Sweep result includes candidates
- **WHEN** `run_parameter_sweep` completes and is persisted
- **THEN** the response SHALL include the best candidate and any Pareto-optimal candidates with their labels

#### Scenario: Sweep uses normalized strategy slug
- **WHEN** `run_parameter_sweep` is called with `strategy="src.strategies.intraday.trend_following.ema_trend_pullback:create_ema_trend_pullback_engine"`
- **THEN** the `strategy` column in `param_registry.db` SHALL contain `"intraday/trend_following/ema_trend_pullback"`, not the module:factory string

### Requirement: Session optimization history tracking
The server SHALL maintain optimization history in the persistent `param_registry.db` instead of an in-memory list. The `get_optimization_history` tool SHALL return all persisted runs, with an option to filter to the current session.

#### Scenario: History persists across restarts
- **WHEN** the MCP server is restarted
- **THEN** `get_optimization_history` SHALL still return all previously recorded runs from the database

#### Scenario: History append on run
- **WHEN** any simulation tool completes (run_backtest, run_monte_carlo, run_parameter_sweep, run_stress_test)
- **THEN** the run parameters, result metrics, tool name, and ISO timestamp SHALL be appended to session history
- **AND** for `run_backtest`, `run_backtest_realdata`, and `run_parameter_sweep`, the full result SHALL also be persisted to the param registry

#### Scenario: History entry format
- **WHEN** a history entry is queried
- **THEN** it SHALL contain: `tool` (string), `params` (dict), `metrics` (dict), `scenario` (string), `timestamp` (ISO string), `strategy` (string), and optionally `run_id` (integer, if persisted to param registry)
