## Context

The quant engine dashboard is currently a monolithic Dash+Plotly application (`src/dashboard/`) serving both UI rendering and business logic from a single Python process. The user operates from Taiwan while the server runs on a VPS in Germany, resulting in 200-250ms RTT for every callback. Dash's architecture forces a server round-trip for all interactions — including purely visual operations like chart zoom/pan and dropdown filtering — making the experience sluggish. More critically, Dash has no server-push mechanism: live trading monitoring relies on `dcc.Interval` polling (minimum 1s), which is fundamentally inadequate for tick-level data and risk alerts.

The Python core (simulator, prediction engine, position engine, execution engine, risk monitor, broker gateway, trading session manager) is well-separated and requires zero changes. Only the presentation layer needs replacement.

## Goals / Non-Goals

**Goals:**
- Sub-100ms UI interactions for chart zoom/pan, tab switches, indicator toggles, and data filtering — all handled client-side
- Real-time WebSocket push for Shioaji tick data, order updates, and risk alerts
- Streaming backtest progress (no more polling)
- Preserve all current dashboard functionality across all tabs
- Parallel coexistence during migration — Dash and FastAPI run side-by-side until cutover
- Keep the Python core completely untouched

**Non-Goals:**
- Rewriting the backtest engine, strategy registry, or any core business logic
- Adding new trading features (scope is infrastructure migration only)
- Mobile-responsive design (desktop-only, matching current Dash layout)
- Authentication/authorization (not present in current Dash app, remains out of scope)
- Replacing the MCP server (independent of dashboard)

## Decisions

### D1: FastAPI as the API layer

**Choice**: FastAPI with uvicorn

**Why**: Native async/await, first-class WebSocket support, automatic OpenAPI docs, and the team already uses Python. Compared to alternatives:
- *Flask*: No native async, no WebSocket support without extensions
- *Django*: Too heavyweight for an API-only layer
- *Litestar*: Less ecosystem/community than FastAPI

FastAPI wraps the existing Python helpers (`src/dashboard/helpers.py` logic) behind REST endpoints and bridges Shioaji callbacks into WebSocket channels.

### D2: React + Vite + TypeScript frontend

**Choice**: React 18+ with Vite bundler and TypeScript

**Why**: Matches the OpenAlice-style terminal aesthetic the user likes. Vite provides instant HMR during development. TypeScript catches API contract mismatches at build time.
- *Svelte/SvelteKit*: Smaller ecosystem for financial charting libraries
- *Vue*: Viable but React has stronger TradingView Lightweight Charts integration and shadcn/ui

### D3: TradingView Lightweight Charts for financial charts

**Choice**: TradingView Lightweight Charts (free, open-source)

**Why**: Purpose-built for OHLCV/candlestick/line charts with canvas rendering (10x faster than Plotly SVG). Handles zoom/pan/crosshair entirely client-side. Plotly is retained nowhere — all chart types (equity curves, drawdown, distributions) use Lightweight Charts or Recharts.

### D4: Zustand for client state

**Choice**: Zustand over Redux/Jotai

**Why**: Minimal boilerplate, TypeScript-friendly, no provider wrapper needed. The dashboard state is relatively flat (current tab, loaded data, WebSocket connection status, filter selections) — no need for Redux's complexity.

### D5: shadcn/ui for component library

**Choice**: shadcn/ui (Tailwind-based, copy-paste components)

**Why**: Highly customizable dark themes that match the current terminal aesthetic. Not an npm dependency — components are copied into the project and fully owned. Pairs naturally with Tailwind CSS.

### D6: Parallel coexistence migration strategy

**Choice**: Run FastAPI on a separate port alongside Dash during migration; migrate tab-by-tab.

**Why**: Zero-downtime migration. Each tab can be independently verified before cutting over. Order:
1. FastAPI skeleton + data endpoints (Data Hub backend)
2. Live Trading tab (most urgent — Dash fundamentally can't do this)
3. Backtest tab (needs progress streaming)
4. Strategy tabs (Code Editor, Optimizer, Grid Search, Monte Carlo)
5. Trading tabs (Accounts, War Room, Blotter, Risk)
6. Remove Dash

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Python Backend                      │
│                                                      │
│  FastAPI (src/api/)                                  │
│    ├── REST                                          │
│    │   ├── GET  /api/ohlcv?symbol=TX&tf=60&...       │
│    │   ├── GET  /api/strategies                      │
│    │   ├── POST /api/backtest/run                    │
│    │   ├── POST /api/optimizer/run                   │
│    │   ├── GET  /api/optimizer/status                │
│    │   ├── GET  /api/accounts                        │
│    │   ├── POST /api/accounts                        │
│    │   └── GET  /api/war-room                        │
│    └── WebSocket                                     │
│        ├── /ws/live-feed       (shioaji on_tick)     │
│        ├── /ws/backtest-progress  (SSE alternative)  │
│        └── /ws/risk-alerts     (risk monitor push)   │
│                                                      │
│  Existing Python core (UNTOUCHED)                    │
│    ├── src/simulator/        (backtest engine)       │
│    ├── src/strategies/       (strategy registry)     │
│    ├── src/broker_gateway/   (gateway registry)      │
│    ├── src/trading_session/  (session manager)       │
│    ├── src/mcp_server/       (MCP facade+tools)      │
│    ├── src/prediction/       (LightGBM, HMM, GARCH) │
│    └── src/secrets/          (GSM credentials)       │
└────────────────────┬────────────────────────────────┘
                     │ HTTP + WebSocket
┌────────────────────┴────────────────────────────────┐
│            React Frontend (frontend/)                │
│                                                      │
│  ├── TradingView Lightweight Charts                  │
│  │   (OHLCV, equity curves, drawdown — canvas)       │
│  ├── Recharts (histograms, heatmaps, bar charts)     │
│  ├── shadcn/ui dark terminal components              │
│  ├── Zustand stores                                  │
│  │   ├── marketDataStore  (OHLCV cache + indicators) │
│  │   ├── backtestStore    (results, progress)        │
│  │   ├── tradingStore     (accounts, sessions, WS)   │
│  │   └── uiStore          (tabs, filters, sidebar)   │
│  └── WebSocket hooks                                 │
│      ├── useLiveFeed()                               │
│      ├── useBacktestProgress()                       │
│      └── useRiskAlerts()                             │
└─────────────────────────────────────────────────────┘
```

## Data Flow Patterns

**Pattern A — Bulk load + local compute (Data Hub, Backtest charts)**:
Browser requests full OHLCV range once → stores in Zustand → all zoom/pan/indicator/timeframe operations happen locally. Server RTT occurs once on load; subsequent interactions are 0ms.

**Pattern B — WebSocket push (Live Trading, Risk)**:
FastAPI bridges Shioaji `on_tick`/`on_order` callbacks into WS frames. The backend maintains a set of connected WS clients and broadcasts. Latency: TAIFEX→Shioaji→Germany server→WS push→Taiwan browser ≈ 250-300ms (physical limit, no polling overhead).

**Pattern C — Long-running task + streaming (Backtest, Optimizer)**:
`POST /api/backtest/run` spawns the computation (existing subprocess pattern). Progress streams via WebSocket or SSE. The frontend shows a real-time progress bar. On completion, full results are sent in one payload.

## File Structure

```
src/api/
  ├── __init__.py
  ├── main.py           # FastAPI app, CORS, mount points
  ├── routes/
  │   ├── ohlcv.py      # GET /api/ohlcv
  │   ├── backtest.py   # POST /api/backtest/run, GET /status
  │   ├── strategies.py # GET /api/strategies, param grids
  │   ├── optimizer.py  # POST /api/optimizer/run, GET /status
  │   ├── accounts.py   # CRUD accounts
  │   ├── war_room.py   # GET war-room data
  │   └── crawl.py      # POST crawl, GET crawl status
  ├── ws/
  │   ├── live_feed.py  # WS /ws/live-feed
  │   ├── backtest.py   # WS /ws/backtest-progress
  │   └── risk.py       # WS /ws/risk-alerts
  └── deps.py           # Shared dependencies (DB path, helpers)

frontend/
  ├── package.json
  ├── vite.config.ts
  ├── tsconfig.json
  ├── tailwind.config.ts
  ├── src/
  │   ├── App.tsx
  │   ├── main.tsx
  │   ├── stores/        # Zustand stores
  │   ├── hooks/         # WebSocket hooks, data fetching
  │   ├── components/    # shadcn/ui + custom components
  │   ├── pages/         # Tab pages (DataHub, Strategy, Backtest, Trading)
  │   └── lib/           # Chart configs, API client, theme
  └── public/
```

## Risks / Trade-offs

- **[Dual-stack maintenance during migration]** → Mitigated by migrating tab-by-tab and keeping Dash running until all tabs are ported. Each tab migration is independently testable.
- **[Frontend build tooling complexity]** → Vite is zero-config for React+TS. The team learns one new tool (npm/pnpm) but the Python backend is familiar territory.
- **[WebSocket reconnection reliability]** → Implement exponential backoff reconnect in the frontend WS hooks. Use a heartbeat ping/pong to detect stale connections.
- **[TradingView Charts learning curve]** → Well-documented library with abundant examples. Simpler API than Plotly for financial data.
- **[Cross-ocean WS latency is physics-limited]** → 250ms RTT is unavoidable for live data. The gain is eliminating the additional 1s+ polling overhead and unnecessary round-trips for local operations.

## Migration Plan

1. **Phase 1 — FastAPI skeleton (2-3 days)**: Create `src/api/` with REST endpoints wrapping existing `helpers.py` functions. Run on port 8000 alongside Dash on 8050. Verify API responses match current Dash data.
2. **Phase 2 — Frontend scaffold + Data Hub (3-4 days)**: Initialize `frontend/` with Vite+React+TS+Tailwind+shadcn. Implement Data Hub page with TradingView chart, verifying feature parity against Dash version.
3. **Phase 3 — Live Trading tab + WS (3-4 days)**: Implement `/ws/live-feed` bridging Shioaji callbacks. Build the War Room with real-time equity, positions, and session cards via WebSocket push.
4. **Phase 4 — Backtest + Strategy tabs (4-5 days)**: Backtest with progress streaming. Strategy sub-tabs (Code Editor, Optimizer, Grid Search, Monte Carlo).
5. **Phase 5 — Trading management tabs (2-3 days)**: Accounts CRUD, Blotter, Risk overview.
6. **Phase 6 — Cutover (1 day)**: Remove `src/dashboard/`, update startup docs, update `pyproject.toml`.

**Rollback**: At any phase, Dash remains functional on its original port. Rollback = stop FastAPI + frontend, continue using Dash.

## Open Questions

- **Code Editor replacement**: The current Dash app uses `DashAceEditor` for in-browser strategy editing. The React equivalent could be Monaco Editor (VS Code engine) or CodeMirror 6. Decision deferred to implementation.
- **Production deployment**: Serve frontend from FastAPI static files, or use nginx/caddy as reverse proxy? The infra-hosting doc suggests considering this. Decision deferred until Phase 6.
