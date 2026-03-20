## 1. Dependencies and Project Setup

- [x] 1.1 Add `dash>=2.18` to `pyproject.toml` dependencies and run `uv sync` to install
- [x] 1.2 Verify `dash`, `dash_table`, `plotly` are importable in the project venv
- [x] 1.3 Update `pyproject.toml` scripts entry (if any) to replace `streamlit run` with `python src/dashboard/app.py`

## 2. Theme Module

- [x] 2.1 Create `src/dashboard/theme.py` with the dark color palette constants (`BG`, `SIDEBAR_BG`, `CARD_BG`, `ACCENT_*` etc.) matching the JSX palette exactly
- [x] 2.2 Add `DARK_CHART_LAYOUT` dict to `theme.py` with Plotly paper/plot bgcolor, grid colors, font, and margin defaults
- [x] 2.3 Add `stat_card(label, value, color, sub=None)` helper to `theme.py` returning an `html.Div` matching the JSX `St` component
- [x] 2.4 Add `dark_table_style()` helper to `theme.py` returning `style_header`, `style_cell`, and `style_data` dicts for `dash_table.DataTable`
- [x] 2.5 Add `GLOBAL_CSS` string to `theme.py` with body background, scrollbar, and Google Fonts `@import` for IBM Plex Sans / IBM Plex Serif / JetBrains Mono

## 3. App Skeleton and Navigation

- [x] 3.1 Replace `src/dashboard/app.py` content: initialize `dash.Dash(__name__)`, inject `app.index_string` with Google Fonts link and global CSS
- [x] 3.2 Build the top-level layout in `app.py`: header bar (IBM Plex Serif, `#07071a` bg), left sidebar `html.Div` at 234px, and main area flex `html.Div`
- [x] 3.3 Add `dcc.Tabs` with 6 `dcc.Tab` items (Historical Data, Live / Paper, Backtest, Grid Search, Monte Carlo, Risk) in the main area, styled with `#5a8af2` active border
- [x] 3.4 Add `html.Div(id='page-content')` as the tab panel output target below the tabs

## 4. Callbacks Module

- [x] 4.1 Create `src/dashboard/callbacks.py`; import the Dash `app` instance and all helper functions from `app.py`
- [x] 4.2 Register `@app.callback(Output('page-content', 'children'), Input('nav-tabs', 'value'))` to route tab selection to page render functions
- [x] 4.3 Import `callbacks` module at the bottom of `app.py` (after `app` and `server` are defined) to trigger callback registration

## 5. Historical Data Page

- [x] 5.1 Implement `build_historical_page()` in `app.py`: sidebar with symbol dropdown, timeframe dropdown, date range pickers; main area placeholder (stat cards + charts)
- [x] 5.2 Add Dash callback that loads OHLCV data and returns 5 stat cards (First Bar, Last Bar, Latest Close, Period Return, Avg Volume) using `stat_card()` from `theme.py`
- [x] 5.3 Add close price line chart using `go.Scatter` + `DARK_CHART_LAYOUT`, stroke `#5a8af2`
- [x] 5.4 Add High/Low dual-line chart (high in `#4fc3f7`, low in `#ff5252`) and Volume bar chart
- [x] 5.5 Add collapsible raw data table using `dash_table.DataTable` with dark styles from `dark_table_style()`
- [x] 5.6 Handle missing database case: show error `html.Div` with red border and path message

## 6. Live / Paper Trading Page

- [x] 6.1 Implement `build_live_page()`: 4 stat cards (Equity, Unrealized PnL, Drawdown, Engine Mode) using `_generate_equity_curve` mock data
- [x] 6.2 Add equity curve `go.Scatter` chart with `#69f0ae` stroke
- [x] 6.3 Add current positions `DataTable` and current signal JSON display styled as a dark card
- [x] 6.4 Add recent trades `DataTable` (last 10 trades)
- [x] 6.5 Add `dcc.Interval(id='live-interval', interval=30000)` and register callback to refresh the page content

## 7. Backtest Page

- [x] 7.1 Implement `build_backtest_page()`: sidebar with all 9 position engine parameters (number inputs + re-entry strategy dropdown)
- [x] 7.2 Add "Run Backtest" button and callback that regenerates mock results and updates 5 performance stat cards
- [x] 7.3 Add equity curve chart (`#69f0ae`), drawdown area chart (`rgba(255,82,82,0.15)` fill), and return distribution histogram (green/red bins)
- [x] 7.4 Add trade log `DataTable` with action-color conditional formatting (`#ff5252` for stop_loss/trail_stop, `#69f0ae` for take_profit/pyramid_add)

## 8. Grid Search Page

- [x] 8.1 Implement `build_grid_search_page()`: sidebar with X/Y axis parameter selectors and range inputs (min, max, steps) and MC sims/cell
- [x] 8.2 Add "Run Grid Search" button and callback that calls `_run_grid_mc()` and stores result in `dcc.Store`
- [x] 8.3 Implement metric selector buttons (E[Return %], Sharpe, Win Rate %, Std Dev) that update heatmap coloring without re-running simulation
- [x] 8.4 Implement heatmap as a `go.Heatmap` trace with custom `colorscale` (red→green) and `hovertemplate` showing Δ, λ, E[Ret], Win Rate, Sharpe
- [x] 8.5 Add Best and Worst cell highlight cards below the heatmap using `stat_card()` or styled `html.Div`
- [x] 8.6 Add full results `DataTable` below the heatmap

## 9. Monte Carlo Page

- [x] 9.1 Implement `build_monte_carlo_page()`: sidebar with Number of Paths slider, Simulation Days slider, Scenario dropdown
- [x] 9.2 Add sample paths line chart (up to 50 paths, `rgba(90,138,242,0.3)` per path)
- [x] 9.3 Add PnL distribution histogram with green/red bin coloring
- [x] 9.4 Add 4 stat cards (Median PnL, P5, P95, P(Loss)) and percentile `DataTable`
- [x] 9.5 Register callback to re-run simulation and update all outputs when "Run Simulation" is clicked

## 10. Risk Monitor Page

- [x] 10.1 Implement `build_risk_page()`: 4 stat cards (Margin Ratio, Drawdown, Max Loss Limit, Engine Mode)
- [x] 10.2 Add drawdown over time area chart with `rgba(255,82,82,0.15)` fill
- [x] 10.3 Add margin ratio history line chart with `go.Scatter` and a dashed reference line at y=0.30 in `#ff5252`
- [x] 10.4 Add risk thresholds `DataTable` and alert history `DataTable` with action-color conditional formatting (`#5a1a1a` bg for CLOSE_ALL/REDUCE_HALF, `#0a1a0a` for NORMAL)

## 11. Final Wiring and Validation

- [x] 11.1 Confirm `python src/dashboard/app.py` starts the Dash server on port 8050 without errors
- [x] 11.2 Verify all 6 tabs render without exceptions and charts display with the correct dark theme
- [x] 11.3 Run `ruff check src/dashboard/` and resolve any linting issues
- [x] 11.4 Run `mypy src/dashboard/` with strict mode and fix type errors
- [x] 11.5 Update `README.md` or project docs to replace `streamlit run` instructions with `python src/dashboard/app.py`
