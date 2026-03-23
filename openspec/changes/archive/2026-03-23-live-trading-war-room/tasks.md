## 1. Broker Gateway — Types & ABC

- [x] 1.1 Create `src/broker_gateway/__init__.py` with public exports
- [x] 1.2 Create `src/broker_gateway/types.py` with `AccountSnapshot`, `LivePosition`, `Fill`, `AccountConfig` dataclasses. Acceptance: mypy strict passes, all fields typed.
- [x] 1.3 Create `src/broker_gateway/abc.py` with `BrokerGateway` ABC defining `connect()`, `disconnect()`, `get_account_snapshot()`, `get_equity_history()`, `broker_name`, `is_connected`. Include TTL-based snapshot caching in a base mixin. Acceptance: subclass without all methods raises TypeError.
- [x] 1.4 Create `src/broker_gateway/registry.py` with `GatewayRegistry` that loads accounts from `trading.db`, resolves credentials via `CredentialStore`, instantiates gateway classes, and provides lookup by account ID. Support hot-reload when accounts are added via UI. Acceptance: empty DB returns empty registry.

## 2. GSM Write + Account DB

- [x] 2.1 Extend `SecretManager` in `src/secrets/manager.py` with `set(name, value)` (create or add version), `delete(name)`, and `exists(name)` methods. Update cache on set. Acceptance: `set("TEST_KEY", "val")` then `get("TEST_KEY")` returns "val"; delete removes from GSM.
- [x] 2.2 Create `src/broker_gateway/account_db.py` with SQLite schema for `accounts` table in `trading.db` (NO credentials stored). Provide `save_account()`, `load_all_accounts()`, `delete_account()`, `update_account()`. Acceptance: CRUD operations pass with SQLite; no secret fields in schema.
- [x] 2.3 Add GSM credential helpers in `src/broker_gateway/registry.py`: naming convention `{ACCOUNT_ID}_{FIELD}` (e.g., `SINOPAC_MAIN_API_KEY`), `save_credentials(account_id, creds_dict)` writes to GSM, `load_credentials(account_id)` reads from GSM. Also update `config/secrets.toml` on account create/delete. Acceptance: credentials written to GSM, no traces on disk.

## 3. Broker Gateway — Sinopac Implementation

- [x] 3.1 Create `src/broker_gateway/sinopac.py` with `SinopacGateway(BrokerGateway)`. Connect using credentials from the credential store or GSM. Acceptance: `connect()` logs in to shioaji, `is_connected` returns True.
- [x] 3.2 Implement `get_account_snapshot()` in `SinopacGateway`: query shioaji for margin (`api.margin()`), positions (`api.list_positions()`), and today's fills. Map raw shioaji data to `AccountSnapshot`. Acceptance: returns populated snapshot with real equity, margin, positions.
- [x] 3.3 Implement disconnected sentinel: on API error or timeout, return `AccountSnapshot(connected=False)` with zeroed values. On session expiry, attempt one auto-reconnect. Acceptance: unreachable broker returns sentinel without raising.
- [x] 3.4 Implement `get_equity_history()` using shioaji's account profit/loss history API or fallback to snapshot store. Acceptance: returns list of (datetime, equity) tuples for past N days.

## 4. Broker Gateway — Mock & Tests

- [x] 4.1 Create `src/broker_gateway/mock.py` with `MockGateway(BrokerGateway)`. Generate synthetic equity random-walk, 2-3 fake positions, mock fills. Acceptance: `is_connected` always True, snapshot has realistic values.
- [x] 4.2 Write tests `tests/test_broker_gateway.py`: test ABC enforcement, MockGateway snapshot generation, GatewayRegistry loading, TTL caching, AccountConfig CRUD, GSM naming convention. Acceptance: all tests pass.

## 5. Market Adapters — Extensions

- [x] 5.1 Add `account_info()` method to `BaseAdapter` in `src/core/adapter.py` with default `return None`. Acceptance: existing adapters still work, no breaking changes.
- [x] 5.2 Add `get_point_value(symbol: str) -> float` to `TaifexAdapter` in `src/adapters/taifex.py`. Load multipliers from `config/taifex.toml` (TX=200, MTX=50, etc.). Log warning and return 1.0 for unknown symbols. Acceptance: `get_point_value("TX")` returns 200.0.
- [x] 5.3 Override `account_info()` in `TaifexAdapter` to return exchange, currency, session_type, and contract multipliers dict. Acceptance: returns dict with "TAIFEX", "TWD", "futures" keys.

## 6. Trading Session — Core

- [x] 6.1 Create `src/trading_session/__init__.py` with public exports
- [x] 6.2 Create `src/trading_session/session.py` with `TradingSession` and `SessionSnapshot` dataclasses. `SessionSnapshot` computes `drawdown_pct` from equity and peak. Acceptance: mypy strict passes, drawdown math verified.
- [x] 6.3 Create `src/trading_session/store.py` with `SnapshotStore` class: SQLite persistence to `trading.db`, `write_snapshot()`, `get_equity_curve(session_id, days)`, auto-create schema on first use. Acceptance: write+read round-trip passes.
- [x] 6.4 Create `src/trading_session/manager.py` with `SessionManager`: create/restore sessions from account DB, `poll_all()` that fetches account snapshots and computes per-session state, `get_all_sessions()` for dashboard. Acceptance: poll_all with MockGateway produces valid snapshots.

## 7. Trading Session — Tests

- [x] 7.1 Write `tests/test_trading_session.py`: test SessionSnapshot drawdown calculation, SnapshotStore persistence round-trip, SessionManager create/restore/poll lifecycle. Acceptance: all tests pass.

## 8. Dashboard — Trading Tab Restructure

- [x] 8.1 Update `src/dashboard/callbacks.py`: change trading sub-tab routing from `["trd-live", "trd-risk"]` to `["trd-accounts", "trd-warroom", "trd-blotter", "trd-risk"]`. Wire to new page builders. Acceptance: clicking Trading tab shows 4 sub-tabs with Accounts as default.
- [x] 8.2 Update `src/dashboard/app.py`: replace `build_live_page()` and `build_risk_page()` with `build_accounts_page()`, `build_war_room_page()`, `build_blotter_page()`, `build_risk_overview_page()`. Update `build_trading_page()` to use new sub-tab IDs and labels. Acceptance: dashboard loads without errors.

## 9. Dashboard — Accounts Management Page

- [x] 9.1 Build `build_accounts_page()` layout: header ("Trading / Configure your trading accounts."), accounts table with columns [Account, Connection, Guards], "+ Add Account" link. Dark theme matching existing dashboard style. Acceptance: page renders with account rows from `trading.db`.
- [x] 9.2 Build account detail modal component: CONNECTION section (type dropdown, exchange input), Sandbox/Demo toggles, CREDENTIALS section (masked inputs for API Key, Secret, Password), GUARDS section (max drawdown %, max margin %, max daily loss inputs), STRATEGIES section (checkbox list + add button). "Reconnect", "Save", "Delete" action buttons. Acceptance: modal opens on row click, pre-populated with account data.
- [x] 9.3 Wire Accounts callbacks: open modal on row click, save account (write to account_db + credential_store), reconnect (test gateway connection), delete with confirmation, add new account. Acceptance: full CRUD operations work from the UI.
- [x] 9.4 Wire "+ Add Account" callback: opens empty modal with generated account ID suggestion and broker type dropdown focused. On save, creates new account entry in DB and hot-reloads GatewayRegistry. Acceptance: new account appears in table after save.

## 10. Dashboard — War Room Page

- [x] 10.1 Add dashboard helpers in `src/dashboard/helpers.py`: `get_war_room_data()` that calls `SessionManager.get_all_sessions()` and `GatewayRegistry.get_all_snapshots()`, returning structured data for the war room. Include initialization of SessionManager singleton. Acceptance: returns dict with accounts and sessions.
- [x] 10.2 Build `build_war_room_page()` layout: sidebar with polling interval selector, account filter, session status filter. Main area with `dcc.Interval` (id `warroom-interval`), account overview div, sessions grid div. Acceptance: page renders with correct dark theme.
- [x] 10.3 Implement Account Overview panel: horizontal row of account cards with broker name, connection badge (LIVE/DISCONNECTED/MOCK), equity, margin bar, active session count. Acceptance: Sinopac account card shows correct badge and real equity.
- [x] 10.4 Implement Strategy Session Monitor cards: per-session card with header (strategy name, symbol, status badge), stat row (Equity, Unrealized PnL, DD%, Trades), equity curve chart, positions table, signal JSON. Responsive CSS grid (2 cols wide, 1 col narrow). Acceptance: each session renders its own monitor card with data from SnapshotStore.
- [x] 10.5 Wire War Room callback: `update_war_room()` triggered by `warroom-interval`, fetches data from helpers, renders account cards + session monitors. Filter by account and session status from sidebar. Acceptance: auto-refresh updates all panels every N seconds.

## 11. Dashboard — Blotter Page

- [x] 11.1 Build `build_blotter_page()` layout: sidebar with account filter dropdown, date range picker. Main area with unified fills table. Acceptance: page renders with dark theme.
- [x] 11.2 Wire Blotter callback: `update_blotter()` collects fills from all sessions, merges into time-ordered table. Apply account filter. Acceptance: shows fills from all connected accounts sorted by time.

## 12. Dashboard — Risk Overview Page

- [x] 12.1 Build `build_risk_overview_page()` layout: stat row (Total Equity, Total Margin, Worst DD, Total Unrealized PnL), margin utilization chart, drawdown comparison chart, thresholds table, alert history. Acceptance: renders with aggregate metrics from all accounts.
- [x] 12.2 Wire Risk Overview callback: aggregate metrics from SessionManager, render charts. Margin bar colors: green <50%, yellow 50-80%, red >80%. Acceptance: charts update on poll.

## 13. Integration & Smoke Test

- [x] 13.1 Add `--mock` flag to dashboard startup (`src/dashboard/app.py`) that registers a `MockGateway` account with 2 mock sessions, enabling full war room testing without broker credentials. Acceptance: `uv run python -m src.dashboard.app --mock` shows war room with mock data.
- [x] 13.2 Verify graceful degradation: start dashboard with account configured but no network. Confirm DISCONNECTED badges, grayed-out data, no crashes. Acceptance: dashboard loads and shows disconnected state cleanly.
- [x] 13.3 Run full test suite: `uv run pytest tests/test_broker_gateway.py tests/test_trading_session.py -v`. Acceptance: all tests green.
