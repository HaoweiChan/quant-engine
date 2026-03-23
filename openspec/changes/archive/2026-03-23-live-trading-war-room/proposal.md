## Why

The Trading tab in the dashboard currently renders entirely mocked data — fake equity curves, hardcoded positions, and synthetic signals. It has zero connection to any real broker account. For the engine to be useful beyond backtesting, we need a live trading "war room" that connects to real accounts, shows true equity curves, monitors running strategies in real time, and is architected to scale across multiple brokers (Sinopac, US brokers, crypto exchanges), multiple accounts per broker, and multiple strategies per account.

## What Changes

- Introduce a **Broker Gateway** abstraction layer (`src/broker_gateway/`) that provides a unified interface for account data (equity, positions, margin, P&L) across any broker. First implementation: Sinopac via shioaji.
- Introduce a **Trading Session** concept that binds a strategy to a specific broker account, tracks its isolated performance, and exposes a real-time state snapshot (equity curve, open positions, signals, fills).
- Redesign the **Trading tab** in the dashboard from a single mock page into a multi-panel war room with:
  - An **Accounts** management page — a table of all configured broker accounts (like the Open Alice UI), with "+ Add Account" flow and per-account detail modal for entering credentials (API Key, Secret, optional Password), toggling Sandbox/Demo mode, and configuring risk guards.
  - An **Account Overview / War Room** panel showing all connected accounts and their aggregate equity, plus per-session strategy monitors.
  - A **Strategy Monitor** panel per active trading session (strategy × account), each with its own equity curve, positions, and signal feed.
  - An **Activity Feed / Blotter** showing a unified, time-ordered log of all fills, signals, and risk events across all sessions.
  - A **Risk Overview** panel aggregating risk metrics across all accounts and strategies.
- Wire the Sinopac account to the dashboard so it displays the real equity curve, real positions, and real margin utilization from the live broker.
- Build a **session registry** that stores active and historical trading sessions with their performance snapshots, enabling session-level replay and comparison.
- Provide **in-dashboard credential management** — users can input API keys and secrets directly in the UI, saved straight to Google Secret Manager with zero secrets on disk.

## Capabilities

### New Capabilities
- `broker-gateway`: Unified broker account data interface — login, equity query, position query, margin query, fill history. Broker-agnostic ABC with Sinopac as first implementation.
- `trading-session`: Strategy-to-account binding that isolates per-strategy performance tracking, stores equity snapshots, and provides a real-time state feed for the dashboard.
- `war-room-dashboard`: Multi-panel live trading dashboard — accounts management page, account overview, per-session strategy monitors, unified blotter, aggregated risk view. Replaces the current mock Trading tab.
- `credential-store`: GSM write capabilities for the dashboard — extends `SecretManager` with `set()`/`delete()`/`exists()` so the UI can save broker credentials directly to Google Secret Manager. Zero secrets on disk.

### Modified Capabilities
- `dashboard`: Trading tab sub-navigation changes from [Live/Paper, Risk Monitor] to [Accounts, War Room, Blotter, Risk]. New sub-tab routing and layout.
- `market-adapters`: TaifexAdapter gains an `account_snapshot()` method for live equity/margin/position queries (extends BaseAdapter).

## Impact

- **New code**: `src/broker_gateway/` (ABC + sinopac impl), `src/trading_session/` (session manager, state store), dashboard war room pages
- **Modified code**: `src/dashboard/callbacks.py` (trading tab routing), `src/dashboard/app.py` (new page builders), `src/dashboard/helpers.py` (new data helpers), `src/core/adapter.py` (extend BaseAdapter), `src/adapters/taifex.py` (account queries)
- **New dependencies**: None required (shioaji already optional via `taifex` extra)
- **New data**: `trading.db` SQLite database for account metadata (no secrets) and session snapshots
- **Config**: Account metadata in SQLite (managed via dashboard UI), credentials in GSM (managed via dashboard UI)
- **Breaking**: Trading tab UI completely redesigned — old sub-tab IDs (`trd-live`, `trd-risk`) will be replaced
