## Why

The current Dash+Plotly dashboard is fundamentally limited for production trading. Dash's single-threaded callback model cannot handle real-time WebSocket push (Shioaji `on_tick`/`on_order` callbacks have no server-push channel), its `dcc.Interval` polling caps at ~1s latency, and every UI interaction (zoom, dropdown, filter) round-trips to the server — which with Taiwan↔Germany cross-ocean RTT of 200-250ms makes the UX unusable for live trading monitoring. The platform has outgrown its prototype dashboard; migrating now unblocks the live trading and risk monitoring features that are actively being built.

## What Changes

- **Add a FastAPI backend** serving REST endpoints and WebSocket channels alongside the existing Python core. No changes to the core engine — only the presentation layer is replaced.
- **Replace Dash frontend with React + Vite + TypeScript** using TradingView Lightweight Charts (financial charts), shadcn/ui (dark terminal aesthetic), and Zustand (state management).
- **Introduce WebSocket push channels**: `/ws/live-feed` for tick-level data from Shioaji callbacks, `/ws/backtest-progress` for streaming backtest status, and `/ws/risk-alerts` for sub-100ms risk alert delivery.
- **Move chart interactions client-side**: zoom/pan, indicator overlays (MA, ATR, Bollinger), timeframe switching on loaded data, and UI state (tabs, filters) all run in-browser with zero server round-trips.
- **Adopt a bulk-load-then-local-compute data pattern**: historical OHLCV is fetched once, then all timeframe aggregation and indicator calculation happens in the browser.
- **Deprecate and remove `src/dashboard/`** (Dash app, callbacks, helpers, theme, editor) once migration is complete.
- **BREAKING**: The dashboard URL and startup command will change from `python -m src.dashboard.app` to separate backend (`uvicorn`) and frontend (`vite dev`) processes.

## Capabilities

### New Capabilities
- `fastapi-backend`: REST API layer (`/api/ohlcv`, `/api/backtest/run`, `/api/positions`, `/api/strategies`) and WebSocket channels (`/ws/live-feed`, `/ws/backtest-progress`, `/ws/risk-alerts`) bridging existing Python core to the new frontend.
- `react-frontend`: React + Vite + TypeScript SPA with TradingView Lightweight Charts, shadcn/ui dark terminal theme, Zustand state, and native WebSocket integration. Covers all current dashboard tabs: Data Hub, Strategy (Code Editor, Optimizer, Grid Search, Monte Carlo), Backtest, and Trading (Accounts, War Room, Blotter, Risk).

### Modified Capabilities
- `dashboard`: The spec will be updated to reflect the new technology stack (React instead of Dash), client-side chart interactions, WebSocket-based real-time updates, and removal of all Dash-specific requirements (dcc.Interval polling, Dash callbacks, DataTable).

## Impact

- **New dependencies**: `fastapi`, `uvicorn[standard]`, `websockets`; frontend: `react`, `vite`, `typescript`, `lightweight-charts`, `zustand`, `@shadcn/ui`
- **Affected code**: `src/dashboard/` (entire directory replaced), `pyproject.toml` (new deps), project startup scripts/docs
- **APIs**: New REST + WebSocket API surface in `src/api/`
- **Systems**: Development workflow changes — frontend runs separately via `vite dev`; production serves built assets from FastAPI or a reverse proxy
- **MCP server**: Unaffected — the MCP facade and tools remain independent of the dashboard
