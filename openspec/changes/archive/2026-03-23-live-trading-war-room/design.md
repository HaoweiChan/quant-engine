## Context

The Trading tab currently renders mocked data via `helpers.generate_equity_curve()` and `helpers.generate_trades()` — zero broker connectivity. The existing execution layer (`src/execution/live.py`) can place orders through shioaji but has no mechanism to query account state (equity, positions, margin). The existing `SinopacConnector` in `src/data/connector.py` handles data fetching only.

We already have:
- `BaseAdapter` in `src/core/adapter.py` — market-agnostic interface for contract specs, margin calc, trading hours
- `TaifexAdapter` in `src/adapters/taifex.py` — TAIFEX-specific implementation
- `LiveExecutor` in `src/execution/live.py` — order placement via shioaji
- `SinopacConnector` in `src/data/connector.py` — data pipeline via shioaji
- Dashboard dark theme, stat cards, charts — all established patterns

The gap: no abstraction for **reading account state** from a broker, and no concept of **binding a strategy to an account** with isolated performance tracking.

## Goals / Non-Goals

**Goals:**
- Define a `BrokerGateway` ABC that any broker can implement for account state queries
- Implement `SinopacGateway` as the first concrete gateway using the existing shioaji session
- Introduce `TradingSession` to bind strategy × account and track per-session equity/P&L
- Replace the mock Trading tab with a multi-panel war room dashboard
- Display real equity curve, positions, and margin from the connected Sinopac account
- Make the architecture trivially extensible for future brokers (Binance, Schwab, etc.)

**Non-Goals:**
- Implementing order placement from the dashboard (execution already exists in `LiveExecutor`)
- Implementing CryptoAdapter or USEquityAdapter gateways (future phases)
- Real-time WebSocket streaming of tick data (polling on `dcc.Interval` is sufficient for v1)
- Strategy auto-start/stop controls from the dashboard (manual process for now)
- PnL attribution or advanced portfolio analytics

## Decisions

### 1. Separate BrokerGateway from BaseAdapter

**Decision**: Create a new `BrokerGateway` ABC in `src/broker_gateway/` rather than extending `BaseAdapter`.

**Rationale**: `BaseAdapter` serves the simulation/backtest pipeline (contract specs, margin math, snapshot conversion). Account state queries (equity, live positions, fill history) are a fundamentally different concern — read-only monitoring vs. trading-time computations. Mixing them violates single-responsibility and forces test doubles to implement account methods they don't need.

**Alternative considered**: Extending `BaseAdapter` with optional account methods. Rejected because it creates a fat interface and confuses the adapter's role in the backtest pipeline.

```
src/broker_gateway/
├── __init__.py
├── abc.py          # BrokerGateway ABC
├── types.py        # AccountSnapshot, Position, Fill dataclasses
└── sinopac.py      # SinopacGateway implementation
```

### 2. Polling over WebSocket for v1

**Decision**: Use `dcc.Interval` polling (every 10–30s) instead of WebSocket push.

**Rationale**: Dash 4 doesn't natively support server-push to individual components. Adding WebSocket infra (Flask-SocketIO or similar) would double the complexity for marginal latency improvement in a monitoring dashboard. 10–30s polling is sufficient for a "war room" display. The `BrokerGateway.get_account_snapshot()` call is lightweight (single API call to shioaji).

**Alternative considered**: Background thread writing to shared state + Dash long polling. Too complex for v1. WebSocket can be added later behind the same ABC.

### 3. TradingSession as in-memory registry + SQLite persistence

**Decision**: `SessionManager` holds active sessions in memory, persists snapshots to SQLite for historical equity curves.

```
src/trading_session/
├── __init__.py
├── session.py      # TradingSession dataclass, SessionManager
└── store.py        # SQLite persistence for equity snapshots
```

**Rationale**: Active sessions need sub-second reads for dashboard polling. SQLite (same DB file or separate `trading_sessions.db`) gives cheap persistence without adding Redis or another service. The store writes snapshots on each poll cycle, building the equity curve over time.

**Alternative considered**: JSON files per session. Too fragile for concurrent writes and no query capability.

### 4. Dashboard war room layout

**Decision**: Replace the Trading tab's 2 sub-tabs (Live/Paper, Risk Monitor) with 3 sub-tabs:

```
Trading
├── War Room     — account cards + strategy session monitors (default)
├── Blotter      — unified activity feed across all sessions
└── Risk         — aggregated risk metrics, margin heatmap
```

The War Room page uses a CSS grid layout:
```
┌──────────────────────────────────────────────┐
│ ACCOUNT OVERVIEW (horizontal card row)        │
│ [Sinopac: $2.1M ▲] [Binance: --] [Schwab: --]│
├─────────────────────┬────────────────────────┤
│ SESSION: ATR MR     │ SESSION: Momentum      │
│ ┌──────────────┐    │ ┌──────────────┐       │
│ │ Equity Curve │    │ │ Equity Curve │       │
│ ├──────────────┤    │ ├──────────────┤       │
│ │ Stats Row    │    │ │ Stats Row    │       │
│ ├──────────────┤    │ ├──────────────┤       │
│ │ Positions    │    │ │ Positions    │       │
│ │ + Signal     │    │ │ + Signal     │       │
│ └──────────────┘    │ └──────────────┘       │
└─────────────────────┴────────────────────────┘
```

Each session monitor is a self-contained card that scales — add more strategies, more cards appear.

### 5. Graceful degradation when broker is offline

**Decision**: Dashboard renders all panels regardless of broker connectivity. Disconnected accounts show a "DISCONNECTED" badge with last-known data grayed out. The gateway returns a sentinel `AccountSnapshot(connected=False)` on connection failure.

**Rationale**: Aligns with the project's "graceful degradation" principle. The war room should never crash because one broker is down.

### 6. In-dashboard account management with GSM-backed credentials

**Decision**: Accounts are configured entirely through the dashboard UI. Account **metadata** (broker type, name, guards, strategy bindings) is stored in `trading.db` (SQLite). Account **credentials** (API keys, secrets, passwords) are written directly to Google Secret Manager — zero secrets on disk.

```
Trading tab sub-tabs:
  Accounts → War Room → Blotter → Risk
```

The Accounts page layout follows the Open Alice pattern:
```
┌──────────────────────────────────────────────┐
│  Trading                                      │
│  Configure your trading accounts.             │
│                                               │
│  ACCOUNT       CONNECTION    GUARDS           │
│  ─────────────────────────────────            │
│  sinopac-main  sinopac       2                │
│  binance-test  binance       —                │
│                                               │
│  + Add Account                                │
└──────────────────────────────────────────────┘

Account Detail Modal:
┌──────────────────────────────────────────┐
│ sinopac-main                          ✕  │
│                                          │
│ CONNECTION                               │
│ Type: [Sinopac]                          │
│ Exchange: [sinopac]                      │
│                                          │
│ ○ Sandbox Mode   ○ Demo Trading          │
│                                          │
│ CREDENTIALS                              │
│ API Key: [••••••••]                      │
│ API Secret: [••••••••]                   │
│ Password: [optional]                     │
│                                          │
│ GUARDS                                   │
│ Max Drawdown %: [15]                     │
│ Max Margin %: [80]                       │
│ Max Daily Loss: [100000]                 │
│                                          │
│ STRATEGIES                               │
│ [✓] ATR Mean Reversion on TX             │
│ [ ] + Add Strategy                       │
│                                          │
│           [Reconnect]  [Save]            │
└──────────────────────────────────────────┘
```

**Rationale**: Zero secrets on disk is the strongest security posture. The existing `SecretManager` already handles GSM reads with caching. Extending it with `set()` / `delete()` / `exists()` methods enables the dashboard to write credentials directly to GSM. The naming convention `{ACCOUNT_ID}_{FIELD}` (e.g., `SINOPAC_MAIN_API_KEY`) keeps secrets organized per account.

```
src/broker_gateway/
├── __init__.py
├── abc.py           # BrokerGateway ABC
├── types.py         # AccountSnapshot, LivePosition, Fill, AccountConfig
├── sinopac.py       # SinopacGateway implementation
├── mock.py          # MockGateway for dev
├── registry.py      # GatewayRegistry — loads from SQLite + GSM
└── account_db.py    # SQLite CRUD for non-secret account metadata
```

**Alternative considered**: Local Fernet-encrypted credential store in SQLite. Rejected because it still leaves encrypted blobs on disk, and a compromised master key exposes all credentials. GSM provides proper key management, audit logging, and IAM-based access control with no local attack surface.

## Risks / Trade-offs

- **[Shioaji rate limits]** → Polling every 10s across multiple queries (equity, positions, margin) may hit API limits. Mitigation: batch queries in a single `get_account_snapshot()` call, cache for 10s.
- **[Session state consistency]** → If the dashboard process restarts, in-memory sessions are lost. Mitigation: `SessionManager.restore()` rebuilds from SQLite + TOML config on startup.
- **[Mock mode for development]** → Developers without Sinopac credentials can't test the war room. Mitigation: `MockGateway` implementation that returns synthetic data (same pattern as current mock helpers).
- **[Dashboard performance with many sessions]** → Each session monitor has its own equity chart + positions table. 10+ sessions could slow rendering. Mitigation: lazy-load session details on click, collapse inactive sessions.

## Open Questions

- Should historical equity snapshots share `taifex_data.db` or use a separate `trading.db`? (Leaning toward separate to avoid mixing market data with account data.)
- What polling interval works best? 10s feels aggressive for a monitoring dashboard, 60s feels too slow for a "war room" vibe. Starting with 15s, configurable.
