## Purpose

Binds a strategy to a broker account for live trading. Each `TradingSession` tracks its own performance state independently, allowing multiple strategies to run on the same account without interfering with each other's equity and P&L metrics.

## Requirements

### Requirement: TradingSession dataclass
The system SHALL define a `TradingSession` dataclass that binds a strategy to a specific broker account and tracks the session's isolated performance state.

```python
@dataclass
class TradingSession:
    session_id: str                  # unique ID (uuid4)
    account_id: str                  # references broker_accounts.toml
    strategy_slug: str               # e.g. "atr_mean_reversion"
    symbol: str                      # e.g. "TX"
    status: str                      # "active" | "paused" | "stopped"
    started_at: datetime
    initial_equity: float
    current_snapshot: SessionSnapshot | None
```

#### Scenario: Session created with unique ID
- **WHEN** a new `TradingSession` is created
- **THEN** it SHALL have a unique `session_id` (UUID v4), `status="active"`, and `started_at` set to the creation timestamp

#### Scenario: Session tracks its own equity independently
- **WHEN** two sessions run on the same account with different strategies
- **THEN** each session SHALL maintain its own equity curve, P&L, and position tracking independent of the other

### Requirement: SessionSnapshot for real-time state
The system SHALL define a `SessionSnapshot` dataclass capturing a point-in-time view of a trading session's performance.

```python
@dataclass
class SessionSnapshot:
    timestamp: datetime
    equity: float
    unrealized_pnl: float
    realized_pnl: float
    drawdown_pct: float
    peak_equity: float
    positions: list[LivePosition]
    last_signal: dict | None
    trade_count: int
```

#### Scenario: Snapshot computes drawdown from peak
- **WHEN** a `SessionSnapshot` is created with `equity=950_000` and `peak_equity=1_000_000`
- **THEN** `drawdown_pct` SHALL be `5.0`

#### Scenario: Snapshot includes current positions filtered by strategy
- **WHEN** the snapshot is computed for a session trading symbol "TX"
- **THEN** `positions` SHALL only include `LivePosition` entries for symbol "TX" from the account's full position list

### Requirement: SessionManager orchestrates all sessions
The system SHALL provide a `SessionManager` class that manages the lifecycle of all `TradingSession` instances: creation, polling, snapshotting, and persistence.

#### Scenario: Create session from config
- **WHEN** `SessionManager.create_session(account_id, strategy_slug, symbol)` is called
- **THEN** it SHALL create a new `TradingSession`, register it, and return the session

#### Scenario: Poll all active sessions
- **WHEN** `SessionManager.poll_all()` is called
- **THEN** it SHALL call `get_account_snapshot()` on each session's broker gateway, compute a `SessionSnapshot` for each active session, and update the session's `current_snapshot`

#### Scenario: Get all sessions for dashboard
- **WHEN** `SessionManager.get_all_sessions()` is called
- **THEN** it SHALL return all registered sessions (active, paused, stopped) with their current snapshots

#### Scenario: Restore sessions on startup
- **WHEN** `SessionManager` is initialized
- **THEN** it SHALL read `config/broker_accounts.toml`, instantiate sessions for each account+strategy pair, and restore historical equity data from the snapshot store

### Requirement: Equity snapshot persistence
The system SHALL persist `SessionSnapshot` data to a SQLite database (`trading.db`) for building historical equity curves per session.

#### Scenario: Snapshot written on each poll cycle
- **WHEN** `SessionManager.poll_all()` updates a session's snapshot
- **THEN** the new snapshot SHALL be persisted to the `session_snapshots` table with columns: `session_id`, `timestamp`, `equity`, `unrealized_pnl`, `realized_pnl`, `drawdown_pct`, `peak_equity`, `trade_count`

#### Scenario: Historical equity curve query
- **WHEN** `SnapshotStore.get_equity_curve(session_id, days=30)` is called
- **THEN** it SHALL return a list of `(timestamp, equity)` tuples from the last 30 days for that session

#### Scenario: Database created on first use
- **WHEN** `trading.db` does not exist
- **THEN** the system SHALL create it with the required schema on first write

### Requirement: Aggregate metrics across sessions
The system SHALL compute aggregate metrics across all active sessions for the dashboard's account overview and risk panels.

#### Scenario: Total equity across all sessions
- **WHEN** the dashboard requests aggregate metrics
- **THEN** it SHALL sum `equity` from each unique account's latest `AccountSnapshot` (not per-session, to avoid double-counting)

#### Scenario: Worst drawdown across sessions
- **WHEN** the dashboard requests aggregate risk metrics
- **THEN** it SHALL report the maximum `drawdown_pct` across all active sessions

#### Scenario: Total unrealized PnL
- **WHEN** the dashboard requests aggregate P&L
- **THEN** it SHALL sum `unrealized_pnl` from all active session snapshots
