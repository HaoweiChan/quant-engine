## 1. Data Layer — Session Persistence

- [x] 1.1 Add `sessions` table to `trading.db` schema (session_id, account_id, strategy_slug, symbol, status, started_at, initial_equity, peak_equity, deployed_candidate_id, updated_at). Acceptance: table created on first access, idempotent with CREATE IF NOT EXISTS.
- [x] 1.2 Add `deployment_log` table to `trading.db` (id, deployed_at, account_id, session_id, strategy, symbol, candidate_id, params JSON, source). Acceptance: table created alongside sessions table.
- [x] 1.3 Create `src/trading_session/session_db.py` with `SessionDB` class: `save(session)`, `update_status(session_id, status)`, `update_deployed(session_id, candidate_id)`, `load_all() -> list[TradingSession]`, `log_deployment(...)`. Acceptance: round-trip save/load test passes.
- [x] 1.4 Write `tests/test_session_db.py` with unit tests: create, load, update status, update deployed, deployment log insert/query. Acceptance: all tests pass.

## 2. TradingSession & SessionManager Extensions

- [x] 2.1 Add `deployed_candidate_id: int | None = None` field to `TradingSession` dataclass. Acceptance: existing code still works, field defaults to None.
- [x] 2.2 Add `SessionManager.set_status(session_id, status)` method that validates transitions (stopped→active, active→paused, active→stopped, paused→active, paused→stopped) and persists to DB. Acceptance: invalid transitions raise ValueError.
- [x] 2.3 Modify `SessionManager.__init__` to accept optional `SessionDB` and load sessions from DB on init. Supplement with `AccountConfig` strategies not yet in DB. Acceptance: sessions survive restart (DB seeded → restart → sessions loaded).
- [x] 2.4 Add `SessionManager.deploy(session_id, candidate_id)` that sets `deployed_candidate_id`, persists to DB, and writes deployment log. Acceptance: deploy updates session and creates log entry.
- [x] 2.5 Write `tests/test_session_manager_lifecycle.py` covering: create session (saved to DB), set_status transitions, deploy, restore from DB. Acceptance: all tests pass.

## 3. Backend API — Deploy & Session Lifecycle

- [x] 3.1 Create `src/api/routes/deploy.py` with `POST /api/deploy/{account_id}` endpoint. Accepts {strategy_slug, symbol, candidate_id}. Validates account and candidate exist. Creates or updates session. Records deployment log. Returns session_id, deployed_candidate_id, params, status. Acceptance: curl test succeeds with valid payload, 404 for invalid account/candidate.
- [x] 3.2 Add `GET /api/deploy/history/{account_id}` and `GET /api/deploy/history` endpoints returning recent deployment log entries. Acceptance: returns JSON array sorted by deployed_at desc.
- [x] 3.3 Create `src/api/routes/sessions.py` with `POST /api/sessions/{session_id}/start`, `/stop`, `/pause` endpoints. Wire to `SessionManager.set_status()`. Return 404 for unknown session, 409 for invalid transition. Acceptance: state transitions work end-to-end.
- [x] 3.4 Extend `GET /api/war-room` response to include per-session `deployed_candidate_id`, `deployed_params`, `backtest_metrics`, and `is_stale` flag. Resolve candidate → run → metrics from param_registry. Acceptance: war-room endpoint returns deployment info per session.
- [x] 3.5 Add `GET /api/params/compare` endpoint (comma-separated run_ids). Delegates to `ParamRegistry.compare_runs()`. Returns list of run objects with metrics. Acceptance: compare 2 valid runs returns side-by-side data.
- [x] 3.6 Register new routers in `src/api/app.py`. Acceptance: all new endpoints appear in OpenAPI docs.

## 4. Frontend — War Room Deployment Panel

- [x] 4.1 Add API client functions in `frontend/src/lib/api.ts`: `deployToAccount(accountId, body)`, `fetchDeployHistory(accountId?)`, `startSession(sessionId)`, `stopSession(sessionId)`, `pauseSession(sessionId)`, `compareRuns(runIds)`. Acceptance: TypeScript compiles, functions match endpoint signatures.
- [x] 4.2 Extend `fetchWarRoom()` response types to include per-session deployment info: `deployed_candidate_id`, `deployed_params`, `backtest_metrics`, `is_stale`, `active_candidate_id`. Acceptance: types match backend response.
- [x] 4.3 Build `StrategyDeployTile` component: displays strategy name, symbol, param summary, backtest sharpe/PnL badges, status badge, stale-params warning, action buttons (Deploy, Start, Stop, Pause). Acceptance: renders correctly with mock data.
- [x] 4.4 Build Strategy Deployment Panel section in `WarRoomTab`: groups deploy tiles by account, fetches data from war-room endpoint, shows "No strategies deployed" placeholder when empty. Acceptance: panel appears below account overview.
- [x] 4.5 Wire lifecycle buttons (Start/Stop/Pause) to API calls with immediate poll after action. Disable Start when no deployed params. Acceptance: clicking Start on stopped session → API call → status updates on next poll.
- [x] 4.6 Add "Deploy" flow: button on deploy tile opens a picker showing the strategy's active candidate from param_registry. Confirm → calls `POST /api/deploy/{account_id}`. Acceptance: deploy succeeds, tile updates with deployed params.

## 5. Frontend — Comparison Widget

- [x] 5.1 Build `ComparePanel` component: dropdown to select 2-3 runs from param_run_registry, side-by-side metric table (Sharpe, PnL, Win Rate, Max DD, PF, Trades, Period, TF), better value highlighted green. Acceptance: renders with mock data, highlighting works.
- [x] 5.2 Add "Compare" button on `StrategyDeployTile` that opens `ComparePanel` with runs pre-filtered to the deployed strategy. Acceptance: clicking Compare opens panel with correct runs.
- [x] 5.3 Show backtest vs live side-by-side on deploy tile when live session data is available. Format: "Backtest: Sharpe 1.17 | Live: Sharpe 0.92". Show "Live: Awaiting data…" when no snapshot exists. Acceptance: both states render correctly.

## 6. Frontend — Deployment History

- [x] 6.1 Build collapsible "Deployment History" section in War Room with a table: Timestamp, Account, Strategy, Symbol, Sharpe, Revert button. Acceptance: table renders with data from `GET /api/deploy/history`.
- [x] 6.2 Wire "Revert" button to re-deploy the historical candidate_id. Acceptance: clicking Revert → deploy API call → tile updates.

## 7. Integration & Verification

- [x] 7.1 End-to-end test: Run backtest via MCP → activate params → deploy to mock account → start session → verify War Room shows correct data. Acceptance: full flow works in browser.
- [x] 7.2 Verify session persistence: deploy + start → restart API server → sessions restored from DB with correct status and deployed_candidate_id. Acceptance: sessions survive restart.
- [x] 7.3 Verify stale-params detection: deploy candidate A → activate candidate B in param_registry → War Room shows "New params available" badge. Acceptance: stale indicator appears.
