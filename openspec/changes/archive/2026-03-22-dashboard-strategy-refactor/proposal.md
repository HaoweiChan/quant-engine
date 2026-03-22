## Why

The Strategy and Optimization tabs serve the same workflow: create/edit a strategy, then optimize its parameters. Having them as separate primary tabs adds navigation friction and makes the parameter optimization feel disconnected from the strategy code it applies to. The Optimization tab also lacks a strategy selector — it's hardwired to ATR Mean Reversion — so a second strategy would have no optimization path at all. Finally, the Dash dropdown search bar renders with a white/light background inside the dark theme, visually jarring every time the user opens a dropdown.

## What Changes

- **Merge Strategy + Optimization into one "Strategy" primary tab** with three sub-tabs: Code Editor, Backtest Optimizer, and Monte Carlo. The existing Grid Search sub-tab becomes "Backtest Optimizer" (it runs real OHLCV backtests via `StrategyOptimizer`, not synthetic MC). The MC Grid Search sub-tab remains as "Monte Carlo".
- **BREAKING**: Remove the standalone "Optimization" primary tab. Its sub-tabs move under "Strategy".
- **Add a strategy selector dropdown** to the Backtest Optimizer sub-tab. It discovers all `create_*_engine()` factory functions in `src/strategies/` at startup and lists them as options.
- **Add "Save as Default Params"** button to the Backtest Optimizer results. After optimization, the user can persist the best params as a TOML config file in `src/strategies/configs/<strategy>.toml`, which the factory function can load as defaults.
- **Fix dropdown search bar color**: the `<input>` inside `.Select-input` and the Dash v4 search wrapper render with browser-default white background. Add targeted CSS to override.

## Capabilities

### New Capabilities
- `strategy-param-persistence`: Saving optimized parameter sets as TOML config files in `src/strategies/configs/` and loading them as factory defaults.

### Modified Capabilities
- `dashboard`: Tab structure changes from 5 tabs (Data Hub / Strategy / Backtest / Optimization / Trading) to 4 tabs (Data Hub / Strategy / Backtest / Trading). The Strategy tab gains sub-tabs. Dropdown search input CSS fixed.
- `code-editor`: No behavioral changes, but now lives under Strategy > Code Editor sub-tab instead of the top-level Strategy tab.

## Impact

- **Modified files**: `src/dashboard/app.py`, `src/dashboard/callbacks.py`, `src/dashboard/helpers.py`, `src/dashboard/theme.py`
- **New file**: `src/strategies/param_loader.py` — TOML param save/load utility
- **No backend API changes** — optimizer and backtester remain unchanged
- **No new dependencies** — uses stdlib `tomllib` / `tomli_w` (already available in Python 3.12)
