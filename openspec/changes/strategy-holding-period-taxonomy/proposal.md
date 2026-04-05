## Why

The current `src/strategies/` directory uses a binary `intraday/` vs `daily/` split that conflates signal timeframe with holding period. All 8 intraday strategies — from 20-minute mean reversion to multi-hour trend following — are lumped under "intraday", while a multi-week pyramid system sits alone in "daily". The `StrategyTimeframe` enum (`INTRADAY`/`DAILY`/`MULTI_DAY`) provides no information about how long a position is actually held, what bar the signal is generated on, or whether the strategy must flatten before session close. This makes it impossible to apply the correct quality gates (short-term strategies need 55-65% win rate; swing strategies need 2.5+ profit factor), group strategies meaningfully in the dashboard, or reason about session-close behavior from metadata alone.

## What Changes

- **BREAKING**: Replace `StrategyTimeframe` enum with three new enums: `SignalTimeframe` (bar used for signal generation), `HoldingPeriod` (expected position duration), and `StopArchitecture` (session-close behavior)
- **BREAKING**: Reorganize directory structure from `intraday/`+`daily/` to `short_term/`+`medium_term/`+`swing/` (by holding period), retaining entry-logic subdirectories (`breakout/`, `mean_reversion/`, `trend_following/`)
- Expand `STRATEGY_META` in all 9 strategy files with: `signal_timeframe`, `holding_period`, `expected_duration_minutes`, `tradeable_sessions`, `stop_architecture`
- Update registry slug generation; retain flat-name aliases only (e.g., `"ta_orb"` → `"short_term/breakout/ta_orb"`)
- Add registry query methods for filtering by holding period, signal timeframe, and session
- Update all consumers: backtester, API routes, MCP tools, scaffold template, frontend strategy selector

## Capabilities

### New Capabilities
- `strategy-taxonomy`: New enum types (`SignalTimeframe`, `HoldingPeriod`, `StopArchitecture`) and expanded `STRATEGY_META` schema for multi-dimensional strategy classification

### Modified Capabilities
- `strategies`: Directory structure changes from timeframe-first to holding-period-first organization; `STRATEGY_META` schema expanded with new required fields
- `strategy-registry`: Slug format changes to reflect new directory paths; new query methods for multi-dimensional filtering; flat-name alias map only
- `strategy-scaffold`: Template updated to generate new directory structure and expanded `STRATEGY_META`

## Impact

- **Code**: All 9 strategy files (META updates + file moves), `src/strategies/__init__.py` (enum changes), `registry.py`, `scaffold.py`, `param_loader.py`
- **Data**: `param_registry.py` SQLite stores strategy slugs — new canonical slugs only
- **API**: `src/api/routes/backtest.py` and `src/mcp_server/tools.py` accept strategy slugs — new slugs are canonical
- **Frontend**: Strategy selector in React dashboard groups by old categories — needs update to group by holding period
- **Configs**: TOML param files in `configs/` reference strategy names — verify no path-based references break
- **No changes to**: `PositionEngine`, `EntryPolicy`, `AddPolicy`, `StopPolicy` interfaces, or the backtesting engine's core simulation logic
