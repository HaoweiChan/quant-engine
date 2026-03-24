## Purpose

Run comparison and backtest-vs-live performance tools for the War Room. Enables side-by-side metric analysis of optimization runs and deployed sessions.

## Requirements

### Requirement: Run comparison API
The system SHALL provide a `GET /api/params/compare` endpoint that accepts a list of run IDs and returns their metrics side-by-side.

```python
@router.get("/compare")
async def compare_runs(run_ids: str) -> CompareResponse: ...
# run_ids is comma-separated: "1,2,5"
```

#### Scenario: Compare two runs
- **WHEN** `GET /api/params/compare?run_ids=1,2` is called
- **THEN** it SHALL return a list of objects, one per run, each containing `run_id`, `run_at`, `strategy`, `symbol`, `best_params`, and metrics (`sharpe`, `total_pnl`, `win_rate`, `max_drawdown_pct`, `profit_factor`, `trade_count`)

#### Scenario: Compare with non-existent run
- **WHEN** `GET /api/params/compare?run_ids=1,999` is called and run 999 does not exist
- **THEN** the response SHALL include only run 1's data (invalid IDs silently skipped)

#### Scenario: Compare with no valid runs
- **WHEN** `GET /api/params/compare?run_ids=998,999` is called and neither exists
- **THEN** the response SHALL return an empty list

### Requirement: Comparison widget in War Room
The War Room SHALL include a "Compare" button that opens a comparison panel. The panel SHALL let the user select 2-3 runs from a dropdown (populated from `param_run_registry` for the deployed strategy) and display their metrics side-by-side.

#### Scenario: Open comparison panel
- **WHEN** the user clicks "Compare" on a strategy deployment tile
- **THEN** a comparison panel SHALL open showing a dropdown of available runs for that strategy

#### Scenario: Select runs and display comparison
- **WHEN** the user selects 2 runs from the dropdown
- **THEN** the panel SHALL display a side-by-side table with rows: Sharpe, PnL, Win Rate, Max DD, Profit Factor, Trade Count, Time Period, Timeframe
- **AND** each column SHALL be one run, with the better value highlighted in green

#### Scenario: Comparison includes live metrics when available
- **WHEN** one of the compared runs is currently deployed and has live session data
- **THEN** the comparison SHALL include a "Live" column showing the session's current metrics alongside the backtest metrics

### Requirement: Backtest vs live performance side-by-side
For deployed sessions with both backtest and live data, the deployment panel SHALL show a mini comparison: backtest sharpe vs live sharpe, backtest PnL vs live PnL, etc.

#### Scenario: Session with both backtest and live data
- **WHEN** a session has been running for at least one poll cycle and has a deployed candidate with backtest metrics
- **THEN** the deployment tile SHALL display: "Backtest: Sharpe 1.17 | Live: Sharpe 0.92" (or similar side-by-side format)

#### Scenario: Session with no live data yet
- **WHEN** a session was just deployed and has no snapshot data
- **THEN** the deployment tile SHALL show backtest metrics only with "Live: Awaiting data…"
