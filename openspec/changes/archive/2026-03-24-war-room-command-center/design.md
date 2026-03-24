## Context

The War Room (`Trading → War Room` sub-tab) currently shows a read-only account overview: equity, margin, connection status. Strategy deployment is manual — a user must edit `config/broker_accounts.toml` to bind strategies to accounts, and there is no UI flow to go from "this backtest looks good" to "deploy these params live."

Meanwhile, the backtest system now has:
- `param_registry.db` with full run history, candidates, and an `is_active` flag per strategy
- Per-run metadata: sharpe, PnL, win rate, max DD, profit factor, time range, timeframe
- Auto-activation logic on deletion
- Dashboard UI showing run history with green-dot active indicator

The `SessionManager` creates `TradingSession` objects from `AccountConfig.strategies` on startup, and `poll_all()` updates snapshots. But there's no runtime deploy/undeploy capability and no link back to which param candidate is running.

```
Current flow (broken):

  Backtest Page                    War Room
  ┌──────────────┐                ┌──────────────┐
  │ Run history   │                │ Account cards │
  │ Active params │   (no link)    │ Sessions      │
  │ Green dot ●   │ ──────────X──→ │ (from TOML)   │
  └──────────────┘                └──────────────┘

Desired flow:

  Backtest Page        Deploy API          War Room
  ┌──────────────┐    ┌──────────┐    ┌──────────────────────┐
  │ Run history   │───→│ POST     │───→│ Strategy Deploy Panel │
  │ Active params │    │ /deploy  │    │ Session controls      │
  │ Green dot ●   │    └──────────┘    │ Comparison widget     │
  └──────────────┘                     │ Deploy history log    │
                                       └──────────────────────┘
```

## Goals / Non-Goals

**Goals:**
- Let traders deploy active params from `param_registry` to a live session in one click
- Show which params are deployed per session with their backtest provenance
- Provide start/stop/pause controls for each session
- Enable side-by-side comparison of 2+ runs before deployment
- Persist a deployment history log for audit

**Non-Goals:**
- Auto-deploy on param activation (user explicitly rejected this)
- Strategy code editing or hot-reload in the War Room
- Paper trading / simulation mode toggle (future scope)
- Multi-user access control or approval workflows
- Real-time P&L streaming via WebSocket (polling is sufficient for v1)

## Decisions

### 1. Deploy = create/update TradingSession with param candidate link

**Decision**: A deployment writes a `deployed_candidate_id` to the `TradingSession` record and records it in a new `deployment_log` table. It does NOT auto-start the session — start is a separate action.

**Why**: Separating deploy (bind params) from start (begin trading) prevents accidental live trading. A trader can deploy params, review the session config, then explicitly start.

**Alternative considered**: Merge deploy + start into one action. Rejected because it's too risky — one click shouldn't open positions.

### 2. Deployment log in trading.db, not param_registry.db

**Decision**: New `deployment_log` table goes in `trading.db` alongside `session_snapshots`.

**Why**: Deployment is a trading concern (which account, when, by whom), not an optimization concern. Keeps `param_registry.db` focused on backtest/optimization data.

### 3. Session lifecycle as REST endpoints, not WebSocket commands

**Decision**: `POST /api/sessions/{session_id}/start`, `/stop`, `/pause` as regular REST calls.

**Why**: Session state changes are infrequent (a few times per day). REST is simpler, matches existing API patterns, and avoids adding WS command handling. The War Room already polls every 15s for snapshot updates.

### 4. Comparison widget reads from param_registry directly

**Decision**: The comparison widget calls `GET /api/params/compare?run_ids=1,2,3` which delegates to `ParamRegistry.compare_runs()`.

**Why**: Data already exists. No duplication needed. The same registry that tracks optimization results feeds the comparison.

### 5. Frontend: extend existing WarRoomTab, don't create new page

**Decision**: The Strategy Deployment Panel, session controls, and comparison widget are all added to the existing `WarRoomTab` component in `Trading.tsx`.

**Why**: The War Room is the natural home for deployment decisions. Creating a separate page fragments the workflow. The current WarRoomTab is lightweight and has room to grow.

### 6. TradingSession extended with deployed_candidate_id

**Decision**: Add `deployed_candidate_id: int | None` to `TradingSession` dataclass. Persisted to `trading.db` via a new `sessions` table (currently sessions are in-memory only).

**Why**: Need to know which param candidate is driving each session. Also provides the foundation for session persistence across restarts (currently sessions rebuild from TOML on every restart).

**Alternative considered**: Store the params directly on the session. Rejected because it duplicates data and loses provenance.

## Risks / Trade-offs

**[Risk] Session persistence migration** — Currently sessions are ephemeral (rebuilt from TOML). Adding a `sessions` table means a migration path. → **Mitigation**: The `sessions` table is additive. On startup, `SessionManager` first loads from DB, then supplements from TOML config for any unregistered strategies.

**[Risk] Deploy without backtest validation** — A user could deploy params that were never backtested. → **Mitigation**: The deployment panel shows the backtest metrics for the candidate being deployed. If no metrics exist, show a warning badge "Unvalidated params."

**[Risk] Stale comparison data** — Live metrics may lag behind real performance due to 15s polling. → **Mitigation**: Clearly label live metrics with "as of {timestamp}" and offer a manual refresh button.

**[Trade-off] No auto-deploy** — The user must manually deploy after activating params in the Backtest page. This is intentional (user preference) but adds friction. → **Mitigation**: The deployment panel shows a "New active params available" notification when the active candidate differs from the deployed candidate.

**[Trade-off] REST-only session control** — Start/stop over REST means no immediate confirmation. → **Mitigation**: After sending start/stop, the UI polls once immediately to update the status badge.
