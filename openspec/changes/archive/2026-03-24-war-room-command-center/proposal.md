## Why

The War Room currently shows only account connections and equity/margin. There is no way to decide which strategy with which params to deploy to live trading. The backtest system now has a full run history with metrics and active-param tracking, but this intelligence dead-ends at the Backtest page — it never flows into the live trading decision layer. Traders need a single command center that bridges research (backtest results) and execution (live sessions) so they can compare, select, and deploy with confidence.

## What Changes

- **Strategy Deployment Panel**: Each account's War Room view gains a deployment panel showing which strategies are deployed, with which params, and their backtest provenance (sharpe, PnL from the active run).
- **Deploy action**: A new API endpoint lets the user push active params from `param_registry` to a live session's config, creating or updating a `TradingSession`.
- **Start/Stop/Pause controls**: Per-session lifecycle controls in the War Room UI, wired to `SessionManager`.
- **Side-by-side comparison**: Pick any 2 runs from the param registry and compare metrics before deploying — backtest performance vs live performance (when available).
- **Quick Compare**: A comparison widget accessible from the deployment panel that pulls runs from `param_run_registry`.
- **Deployment history log**: Track who deployed what params when, persisted to `trading.db`.

## Capabilities

### New Capabilities
- `strategy-deployment`: Manage deployment of optimized params from `param_registry` to live `TradingSession` instances. Covers the deploy API, deployment history log, and linking param candidates to sessions.
- `war-room-compare`: Side-by-side run comparison widget in the War Room. Pulls data from `param_run_registry`, displays backtest metrics alongside live session metrics where available.

### Modified Capabilities
- `war-room-dashboard`: Add the Strategy Deployment Panel, session lifecycle controls (start/stop/pause), and deployment history table to the existing War Room sub-tab.
- `trading-session`: Extend `TradingSession` with a `deployed_candidate_id` field linking back to `param_candidates`, and add session lifecycle API (start/stop/pause).

## Impact

- **Backend**: New `src/api/routes/deploy.py` with `POST /api/deploy/{account_id}`, `POST /api/sessions/{session_id}/start|stop|pause`. New `deployment_log` table in `trading.db`. `TradingSession` gets a `deployed_candidate_id` column.
- **Frontend**: `WarRoomTab` in `Trading.tsx` expanded significantly — deployment panel, comparison widget, session controls. New API client functions in `api.ts`.
- **Data**: `trading.db` gains `deployment_log` table. `TradingSession` extended.
- **Dependencies**: No new external dependencies. Uses existing `param_registry`, `SessionManager`, `GatewayRegistry`.
