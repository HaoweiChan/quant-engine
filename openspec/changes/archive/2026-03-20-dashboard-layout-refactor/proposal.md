## Why

The dashboard's 7 flat tabs (Historical Data, Data Export, Live/Paper, Backtest, Grid Search, Monte Carlo, Risk) have no conceptual grouping or workflow progression. Data tabs are split by an execution tab, three research tabs sit side-by-side without a shared identity, and Risk is isolated from the trading view it monitors. Users can't intuit "what do I do first?" from the tab order. Refactoring to 4 domain-grouped tabs aligned with the strategy lifecycle (Data → Research → Optimization → Trading) reduces cognitive load and matches how professional quant platforms organize their UIs.

## What Changes

- **Merge Historical Data + Data Export → "Data Hub"**: One page for browsing market data, exporting CSV, and crawling from Sinopac. The current two pages share the same inputs (symbol, timeframe, date range) and should be a single unified view.
- **Keep Backtest as its own tab**: Single-run backtest with position engine parameters, equity curve, drawdown, trade log. No structural change to content, just repositioned in tab order.
- **Merge Grid Search + Monte Carlo → "Optimization"**: Both are parameter sensitivity analysis from different angles (deterministic sweep vs stochastic simulation). Sub-tabs or toggle within a single top-level tab.
- **Merge Live/Paper + Risk → "Trading"**: Live/paper monitoring with risk as a persistent sub-view or sub-tab. Risk thresholds, drawdown, margin ratio, and alerts are displayed alongside live positions and equity — not hidden on a separate page.
- **Reorder tabs to follow the strategy lifecycle**: Data Hub → Backtest → Optimization → Trading.

## Capabilities

### New Capabilities

_None — this is a reorganization of existing capabilities, not new functionality._

### Modified Capabilities

- `dashboard`: Tab structure changes from 7 flat tabs to 4 grouped tabs. Historical Data and Data Export merge into "Data Hub". Grid Search and Monte Carlo merge into "Optimization" with sub-navigation. Live/Paper and Risk merge into "Trading" with sub-navigation. Tab order changes to follow the strategy lifecycle.

## Impact

- **Code**: `src/dashboard/app.py` — tab definitions, page builders restructured. `src/dashboard/callbacks.py` — callback routing updated for new tab/sub-tab structure. Possibly new sub-tab navigation components.
- **Specs**: `openspec/specs/dashboard/spec.md` — tab navigation requirement rewritten, page requirements consolidated.
- **No breaking API changes**: This is a UI-only refactor. No changes to helpers, data layer, or computation logic.
- **No new dependencies**: Existing Dash components (`dcc.Tabs`, `html.Div`) are sufficient.
