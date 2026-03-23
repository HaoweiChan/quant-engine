## 1. FastAPI Backend Skeleton

- [x] 1.1 Add `fastapi`, `uvicorn[standard]`, `websockets` to `pyproject.toml` dependencies and run `uv lock`
- [x] 1.2 Create `src/api/__init__.py` and `src/api/main.py` with FastAPI app, CORS middleware (allow `localhost:5173`), and health check endpoint at `GET /api/health`
- [x] 1.3 Create `src/api/deps.py` with shared dependencies (DB path, helper imports) used across route modules
- [x] 1.4 Verify server starts: `uvicorn src.api.main:app --port 8000` serves `/docs` and `/api/health` returns 200

## 2. REST Data Endpoints

- [x] 2.1 Create `src/api/routes/ohlcv.py` — `GET /api/ohlcv` with query params `symbol`, `start`, `end`, `tf_minutes`; delegates to `helpers.load_ohlcv`; returns `{bars: [...], count: N}`
- [x] 2.2 Create `src/api/routes/coverage.py` — `GET /api/coverage` returning per-symbol bar counts and date ranges from `helpers.get_db_coverage`
- [x] 2.3 Create `src/api/routes/strategies.py` — `GET /api/strategies` returning all registered strategies with slug, name, and param_grid from `helpers.STRATEGY_REGISTRY`
- [x] 2.4 Create `src/api/routes/backtest.py` — `POST /api/backtest/run` accepting strategy, symbol, date range, params, max_loss; delegates to `helpers.run_strategy_backtest`; returns full result dict
- [x] 2.5 Create `src/api/routes/optimizer.py` — `POST /api/optimizer/run` starting the optimizer subprocess via `helpers.start_optimizer_run`; `GET /api/optimizer/status` returning `helpers.get_optimizer_state()`
- [x] 2.6 Create `src/api/routes/accounts.py` — `GET /api/accounts` (list all), `POST /api/accounts` (create/update), `GET /api/accounts/{id}` (single with credential status)
- [x] 2.7 Create `src/api/routes/war_room.py` — `GET /api/war-room` returning `helpers.get_war_room_data()` serialized as JSON
- [x] 2.8 Create `src/api/routes/crawl.py` — `POST /api/crawl/start` and `GET /api/crawl/status` wrapping `helpers.start_crawl` and `helpers.get_crawl_state`
- [x] 2.9 Mount all route modules in `src/api/main.py` and verify all endpoints return correct responses via `/docs`

## 3. WebSocket Channels

- [x] 3.1 Create `src/api/ws/live_feed.py` — `WS /ws/live-feed` with a broadcast manager that bridges Shioaji `on_tick`/`on_order` callbacks to all connected WebSocket clients
- [x] 3.2 Create `src/api/ws/backtest.py` — `WS /ws/backtest-progress` that streams progress messages during backtest execution and sends completion payload
- [x] 3.3 Create `src/api/ws/risk.py` — `WS /ws/risk-alerts` that pushes risk threshold breaches to connected clients and sends periodic heartbeat pings
- [x] 3.4 Add WebSocket connection lifecycle management: client tracking, graceful disconnect cleanup, exponential backoff heartbeat
- [x] 3.5 Mount all WS routes in `src/api/main.py` and write a manual test script to verify connection + message delivery

## 4. FastAPI Tests

- [x] 4.1 Create `tests/test_api_ohlcv.py` — test OHLCV endpoint with valid params, empty result, and invalid date
- [x] 4.2 Create `tests/test_api_backtest.py` — test backtest endpoint with known strategy and unknown strategy (400)
- [x] 4.3 Create `tests/test_api_strategies.py` — test strategy listing returns correct structure
- [x] 4.4 Create `tests/test_api_accounts.py` — test account CRUD operations
- [x] 4.5 Create `tests/test_ws_live_feed.py` — test WebSocket connection, message receipt, and graceful disconnect

## 5. React Frontend Scaffold

- [x] 5.1 Initialize `frontend/` with `npm create vite@latest -- --template react-ts`; configure TypeScript strict mode in `tsconfig.json`
- [x] 5.2 Install and configure Tailwind CSS v4 with the dark terminal color palette as CSS variables
- [x] 5.3 Install shadcn/ui and initialize with dark theme; add Button, Input, Select, Tabs, Card, Dialog components
- [x] 5.4 Install `lightweight-charts`, `zustand`, `recharts`
- [x] 5.5 Create `frontend/src/lib/theme.ts` — export all color constants matching `src/dashboard/theme.py` (BG, SIDEBAR_BG, CARD_BG, GREEN, RED, BLUE, etc.)
- [x] 5.6 Create `frontend/src/lib/api.ts` — typed API client with `fetchOHLCV`, `fetchStrategies`, `runBacktest`, etc. using `fetch()` against the FastAPI backend
- [x] 5.7 Load Google Fonts (IBM Plex Serif, IBM Plex Sans, JetBrains Mono) in `index.html`
- [x] 5.8 Verify `npm run dev` starts on port 5173 and renders a dark-themed shell with the header and tab bar

## 6. Zustand Stores

- [x] 6.1 Create `frontend/src/stores/marketDataStore.ts` — OHLCV cache, loaded symbol/tf/range, loading state
- [x] 6.2 Create `frontend/src/stores/backtestStore.ts` — backtest results, progress, loading state
- [x] 6.3 Create `frontend/src/stores/tradingStore.ts` — accounts, sessions, WS connection status, live positions
- [x] 6.4 Create `frontend/src/stores/uiStore.ts` — active primary tab, active sub-tabs (strategy, trading), sidebar state

## 7. Shared Components

- [x] 7.1 Create `StatCard` component — uppercase label, colored value in JetBrains Mono, optional sub-label; matching `#0d0d26` bg and `#1a1a38` border
- [x] 7.2 Create `StatRow` component — horizontal flex row of StatCard children
- [x] 7.3 Create `ChartCard` component — labeled card wrapper for chart/table content
- [x] 7.4 Create `Sidebar` component — 234px fixed sidebar with section labels and input slot areas
- [x] 7.5 Create `OHLCVChart` component — wraps TradingView Lightweight Charts for price data with dark theme config
- [x] 7.6 Create `EquityCurveChart` component — line chart for equity curves (strategy vs B&H overlay)
- [x] 7.7 Create `DrawdownChart` component — area chart for drawdown with red fill
- [x] 7.8 Create `DistributionChart` component — Recharts bar chart for return/PnL distributions with green/red bin coloring

## 8. WebSocket Hooks

- [x] 8.1 Create `frontend/src/hooks/useLiveFeed.ts` — connects to `/ws/live-feed`, parses tick/order messages, updates tradingStore, auto-reconnect with exponential backoff
- [x] 8.2 Create `frontend/src/hooks/useBacktestProgress.ts` — connects to `/ws/backtest-progress`, updates backtestStore with progress/completion
- [x] 8.3 Create `frontend/src/hooks/useRiskAlerts.ts` — connects to `/ws/risk-alerts`, stores alerts in tradingStore, triggers UI notifications

## 9. Data Hub Page

- [x] 9.1 Create `frontend/src/pages/DataHub.tsx` — sidebar with contract dropdown, timeframe, date range, export/crawl controls
- [x] 9.2 Implement database coverage summary section fetching from `/api/coverage`
- [x] 9.3 Implement OHLCV chart rendering using `OHLCVChart` component with stat cards (First Bar, Last Bar, Latest Close, Period Return, Avg Volume)
- [x] 9.4 Implement High/Low and Volume charts
- [x] 9.5 Implement raw data table (last 100 bars) using shadcn/ui DataTable
- [x] 9.6 Implement CSV export preview and download via `/api/ohlcv` endpoint
- [x] 9.7 Implement crawl console with progress polling from `/api/crawl/status`

## 10. Backtest Page

- [x] 10.1 Create `frontend/src/pages/Backtest.tsx` — sidebar with strategy selector, contract, dates, dynamic strategy params, Run Backtest button
- [x] 10.2 Implement dynamic strategy parameter inputs that update when strategy selection changes (fetched from `/api/strategies`)
- [x] 10.3 Implement backtest results rendering — equity curve (vs B&H), drawdown, return distribution, stat cards, trade log table
- [x] 10.4 Wire up loading state and progress feedback

## 11. Strategy Sub-tabs

- [x] 11.1 Create `frontend/src/pages/strategy/CodeEditor.tsx` — file browser sidebar, code editor (Monaco or CodeMirror), validation panel, save/revert buttons via API
- [x] 11.2 Create `frontend/src/pages/strategy/Optimizer.tsx` — param grid inputs, run button, IS/OOS equity curves, heatmap, top-10 table, save best params
- [x] 11.3 Create `frontend/src/pages/strategy/GridSearch.tsx` — X/Y axis param selectors, range inputs, MC sims, heatmap visualization, best/worst annotations
- [x] 11.4 Create `frontend/src/pages/strategy/MonteCarlo.tsx` — strategy/contract/date selection, path count, simulation days, paths chart, PnL distribution, percentile table

## 12. Trading Sub-tabs

- [x] 12.1 Create `frontend/src/pages/trading/Accounts.tsx` — account table, add button, detail modal with broker type, sandbox/demo toggles, credentials, guards, save/reconnect
- [x] 12.2 Create `frontend/src/pages/trading/WarRoom.tsx` — account overview cards with equity sparklines, daily PnL, margin utilization, live positions, session monitor grid; all driven by WebSocket updates
- [x] 12.3 Create `frontend/src/pages/trading/Blotter.tsx` — unified fill feed table with account/strategy filters, auto-refresh via polling or WS
- [x] 12.4 Create `frontend/src/pages/trading/Risk.tsx` — aggregated stat cards (total equity, margin, worst drawdown, unrealized PnL), margin utilization table, alert history

## 13. Client-Side Indicators

- [x] 13.1 Create `frontend/src/lib/indicators.ts` — pure functions for MA, EMA, ATR, Bollinger Bands operating on cached OHLCV arrays
- [x] 13.2 Add indicator toggle controls to Data Hub sidebar and wire overlays to `OHLCVChart` component
- [x] 13.3 Verify indicator toggling and parameter changes execute with zero network requests

## 14. Integration Testing & Cutover

- [x] 14.1 Verify feature parity: run Dash and React side-by-side, compare all tabs/pages for visual and data correctness
- [x] 14.2 Verify WebSocket reliability: test reconnection after server restart, multiple simultaneous clients, and long-running connections
- [x] 14.3 Update `pyproject.toml` scripts and project README with new startup commands (`uvicorn` + `npm run dev`)
- [x] 14.4 Remove `src/dashboard/` directory (app.py, callbacks.py, helpers.py, theme.py, editor.py) and Dash-related dependencies from `pyproject.toml`
- [x] 14.5 Run full test suite and verify no regressions
