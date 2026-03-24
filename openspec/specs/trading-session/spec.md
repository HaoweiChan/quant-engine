## Purpose

Binds a strategy to a broker account for live trading. Each `TradingSession` tracks its own performance state independently, allowing multiple strategies to run on the same account without interfering with each other's equity and P&L metrics.

## Requirements

### Requirement: TradingSession dataclass
The system SHALL define a `TradingSession` dataclass that binds a strategy to a specific broker account and tracks the session's isolated performance state.

```python
@dataclass
class TradingSession:
    session_id: str
    account_id: str
    strategy_slug: str
    symbol: str
    status: str  # "active" | "paused" | "stopped"
    started_at: datetime
    initial_equity: float
    current_snapshot: SessionSnapshot | None
    peak_equity: float = 0.0
    deployed_candidate_id: int | None = None  # links to param_candidates.id
```

#### Scenario: Session created with unique ID
- **WHEN** a new `TradingSession` is created
- **THEN** it SHALL have a unique `session_id` (UUID v4), `status="stopped"`, and `started_at` set to the creation timestamp

#### Scenario: Session tracks deployed params
- **WHEN** params are deployed to a session
- **THEN** `deployed_candidate_id` SHALL be set to the candidate's ID from `param_candidates`

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
The system SHALL provide a `SessionManager` class that manages the lifecycle of all `TradingSession` instances: creation, polling, snapshotting, persistence, and state transitions.

#### Scenario: Create session from config
- **WHEN** `SessionManager.create_session(account_id, strategy_slug, symbol)` is called
- **THEN** it SHALL create a new `TradingSession` with `status="stopped"`, register it, persist it to DB, and return the session

#### Scenario: Start/stop/pause session
- **WHEN** `SessionManager.set_status(session_id, "active"|"paused"|"stopped")` is called
- **THEN** it SHALL update the session's status, persist the change to DB, and log via structlog

#### Scenario: Poll all active sessions
- **WHEN** `SessionManager.poll_all()` is called
- **THEN** it SHALL call `get_account_snapshot()` on each active session's broker gateway, compute a `SessionSnapshot`, and update the session's `current_snapshot`

#### Scenario: Get all sessions for dashboard
- **WHEN** `SessionManager.get_all_sessions()` is called
- **THEN** it SHALL return all registered sessions (active, paused, stopped) with their current snapshots

#### Scenario: Restore sessions on startup
- **WHEN** `SessionManager` is initialized
- **THEN** it SHALL load all sessions from the `sessions` table in `trading.db`, then check `AccountConfig` for new strategy bindings not yet in the DB and create sessions for them

### Requirement: Session lifecycle API
The system SHALL provide REST endpoints to control session state transitions.

```python
@router.post("/sessions/{session_id}/start")
async def start_session(session_id: str) -> dict: ...

@router.post("/sessions/{session_id}/stop")
async def stop_session(session_id: str) -> dict: ...

@router.post("/sessions/{session_id}/pause")
async def pause_session(session_id: str) -> dict: ...
```

#### Scenario: Start a stopped session
- **WHEN** `POST /api/sessions/{session_id}/start` is called and the session status is "stopped"
- **THEN** the status SHALL change to "active" and polling SHALL resume for this session
- **AND** the response SHALL include `{"session_id": "...", "status": "active"}`

#### Scenario: Stop an active session
- **WHEN** `POST /api/sessions/{session_id}/stop` is called and the session status is "active"
- **THEN** the status SHALL change to "stopped" and the session SHALL stop participating in `poll_all()`
- **AND** any open positions SHALL NOT be auto-closed (stop only halts new signals)

#### Scenario: Pause an active session
- **WHEN** `POST /api/sessions/{session_id}/pause` is called and the session status is "active"
- **THEN** the status SHALL change to "paused"
- **AND** the session SHALL continue receiving snapshots but SHALL NOT generate new trading signals

#### Scenario: Invalid state transition
- **WHEN** `POST /api/sessions/{session_id}/start` is called and the session is already "active"
- **THEN** the endpoint SHALL return HTTP 409 with detail "Session already active"

#### Scenario: Unknown session
- **WHEN** any lifecycle endpoint is called with a non-existent session_id
- **THEN** it SHALL return HTTP 404 with detail "Session not found"

### Requirement: Session persistence to trading.db
The system SHALL persist `TradingSession` records to a `sessions` table in `trading.db` so sessions survive process restarts.

```sql
CREATE TABLE IF NOT EXISTS sessions (
    session_id            TEXT PRIMARY KEY,
    account_id            TEXT NOT NULL,
    strategy_slug         TEXT NOT NULL,
    symbol                TEXT NOT NULL,
    status                TEXT NOT NULL DEFAULT 'stopped',
    started_at            TEXT NOT NULL,
    initial_equity        REAL NOT NULL DEFAULT 0,
    peak_equity           REAL NOT NULL DEFAULT 0,
    deployed_candidate_id INTEGER,
    updated_at            TEXT NOT NULL
);
```

#### Scenario: Session created and persisted
- **WHEN** a new `TradingSession` is created (via deploy or restore)
- **THEN** a row SHALL be inserted into the `sessions` table

#### Scenario: Session status update persisted
- **WHEN** a session's status changes (start/stop/pause)
- **THEN** the `sessions` table row SHALL be updated with the new status and `updated_at`

#### Scenario: Sessions restored on startup
- **WHEN** `SessionManager` initializes
- **THEN** it SHALL load all sessions from the `sessions` table
- **AND** supplement with any new strategies from `AccountConfig` that are not yet in the DB

#### Scenario: Deployed candidate persisted
- **WHEN** `deployed_candidate_id` is set via the deploy endpoint
- **THEN** the `sessions` table row SHALL be updated with the new candidate_id

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
