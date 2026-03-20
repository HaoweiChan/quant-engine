## 1. Primary Tab Structure

- [x] 1.1 Replace the 7-tab `dcc.Tabs` in `app.py::app.layout` with 4 primary tabs: Data Hub, Backtest, Optimization, Trading. Update `_TAB_STYLE` / `_TAB_SELECTED_STYLE` if needed. **Verify**: App loads with 4 tabs visible, default is Data Hub.
- [x] 1.2 Update `callbacks.py::render_page()` to route the 4 new primary tab values (`datahub`, `backtest`, `optimization`, `trading`) to their respective builder functions. **Verify**: Clicking each tab renders the correct page.

## 2. Data Hub Page (merge Historical Data + Data Export)

- [x] 2.1 Create `build_data_hub_page()` in `app.py` combining sidebar controls from both `build_historical_page()` and `build_data_export_page()`. Use the richer contract dropdown (with display name + description) from Data Export. Add sections: DATA QUERY (contract, timeframe, date range), EXPORT (Preview & Download button), CRAWL FROM SINOPAC (crawl contract, date range, Start Crawl button). **Verify**: Sidebar renders all controls without overflow issues.
- [x] 2.2 Create unified Data Hub callback in `callbacks.py` that renders the main area: DB coverage summary at the top, stat cards, price/high-low/volume charts, raw data table. Merge logic from `update_historical()` and `preview_export()`. **Verify**: Selecting a contract + timeframe loads charts and stats.
- [x] 2.3 Wire up the export preview + download callbacks for Data Hub. Reuse existing `download_csv()` callback with updated component IDs (`dh-` prefix). **Verify**: Preview & Download shows preview section with download button; clicking download triggers CSV file save.
- [x] 2.4 Wire up the crawl callbacks for Data Hub. Reuse existing `handle_crawl()` / `_crawl_header()` logic with updated component IDs (`dh-` prefix). **Verify**: Start Crawl shows console with progress; poll updates until complete.
- [x] 2.5 Remove `build_historical_page()` and `build_data_export_page()` from `app.py`. Remove `update_historical()` and `preview_export()` callbacks from `callbacks.py`. **Verify**: No dead code remains; no import errors.

## 3. Optimization Tab (sub-tabs: Grid Search + Monte Carlo)

- [x] 3.1 Create `build_optimization_page()` in `app.py` that renders a secondary `dcc.Tabs` with two sub-tabs: Grid Search (value `opt-gs`) and Monte Carlo (value `opt-mc`). Default to Grid Search. Use lighter sub-tab styling. **Verify**: Optimization tab shows secondary tab bar with two options.
- [x] 3.2 Add sub-tab routing callback in `callbacks.py` that calls `build_grid_search_page()` or `build_monte_carlo_page()` based on the active sub-tab. **Verify**: Switching sub-tabs renders the correct page content.
- [x] 3.3 Verify existing Grid Search and Monte Carlo callbacks still work under the new nesting. No changes expected to `run_grid()`, `update_grid_heatmap()`, or `run_monte_carlo()`. **Verify**: Run Grid Search and Run Simulation buttons produce correct results.

## 4. Trading Tab (sub-tabs: Live/Paper + Risk Monitor)

- [x] 4.1 Create `build_trading_page()` in `app.py` that renders a secondary `dcc.Tabs` with two sub-tabs: Live/Paper (value `trd-live`) and Risk Monitor (value `trd-risk`). Default to Live/Paper. Use lighter sub-tab styling. **Verify**: Trading tab shows secondary tab bar with two options.
- [x] 4.2 Add sub-tab routing callback in `callbacks.py` that calls `build_live_page()` or `build_risk_page()` based on the active sub-tab. **Verify**: Switching sub-tabs renders the correct page content.
- [x] 4.3 Verify existing Live/Paper and Risk callbacks still work under the new nesting. No changes expected to `update_live()`. **Verify**: Live/Paper auto-refreshes; Risk page renders charts and tables.

## 5. Cleanup and Polish

- [x] 5.1 Define a `_SUB_TAB_STYLE` / `_SUB_TAB_SELECTED_STYLE` in `app.py` (or `theme.py`) for secondary tabs: smaller font (9px), no bold, subtler border color. **Verify**: Sub-tabs are visually distinguishable from primary tabs.
- [x] 5.2 Update the dashboard spec at `openspec/specs/dashboard/spec.md` — verify the spec mentions "four tabs: Data Hub, Backtest, Optimization, Trading" and documents the sub-tab structure. **Verify**: Spec accurately reflects the implemented dashboard.
- [x] 5.3 Run `ruff check src/dashboard/` and `mypy src/dashboard/` to confirm no lint or type errors. **Verify**: Clean output from both tools.
