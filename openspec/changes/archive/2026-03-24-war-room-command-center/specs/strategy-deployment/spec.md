## ADDED Requirements

### Requirement: Deploy params to a trading session
The system SHALL provide a `POST /api/deploy/{account_id}` endpoint that binds a `param_candidates` entry to a `TradingSession`. The endpoint SHALL accept a JSON body with `strategy_slug`, `symbol`, and `candidate_id`. It SHALL create a new session if none exists for that account+strategy+symbol combination, or update the existing session's `deployed_candidate_id`.

```python
@router.post("/deploy/{account_id}")
async def deploy(account_id: str, body: DeployRequest) -> DeployResponse: ...

@dataclass
class DeployRequest:
    strategy_slug: str
    symbol: str
    candidate_id: int

@dataclass
class DeployResponse:
    session_id: str
    deployed_candidate_id: int
    params: dict[str, Any]
    status: str  # "deployed" (session exists but stopped) or "ready"
```

#### Scenario: Deploy to existing session
- **WHEN** `POST /api/deploy/sinopac-main` is called with `strategy_slug="intraday/trend_following/ema_trend_pullback"`, `symbol="TX"`, `candidate_id=5`
- **AND** a session for that account+strategy+symbol already exists
- **THEN** the session's `deployed_candidate_id` SHALL be updated to 5
- **AND** a `deployment_log` entry SHALL be recorded
- **AND** the response SHALL include the candidate's params and session status

#### Scenario: Deploy creates new session
- **WHEN** `POST /api/deploy/sinopac-main` is called and no session exists for the given combination
- **THEN** a new `TradingSession` SHALL be created with `status="stopped"` and `deployed_candidate_id=5`
- **AND** the response `status` SHALL be "ready"

#### Scenario: Deploy with invalid candidate
- **WHEN** `candidate_id` references a non-existent candidate
- **THEN** the endpoint SHALL return HTTP 404 with detail "Candidate not found"

#### Scenario: Deploy with invalid account
- **WHEN** `account_id` does not match any configured account
- **THEN** the endpoint SHALL return HTTP 404 with detail "Account not found"

### Requirement: Deployment log persistence
The system SHALL maintain a `deployment_log` table in `trading.db` recording each deployment action.

```sql
CREATE TABLE IF NOT EXISTS deployment_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    deployed_at  TEXT NOT NULL,
    account_id   TEXT NOT NULL,
    session_id   TEXT NOT NULL,
    strategy     TEXT NOT NULL,
    symbol       TEXT NOT NULL,
    candidate_id INTEGER NOT NULL,
    params       TEXT NOT NULL,  -- JSON
    source       TEXT NOT NULL DEFAULT 'dashboard'
);
```

#### Scenario: Log entry created on deploy
- **WHEN** a deployment succeeds
- **THEN** a row SHALL be inserted into `deployment_log` with the current ISO timestamp, account, session, strategy, candidate_id, and JSON-serialized params

#### Scenario: Query deployment history
- **WHEN** `GET /api/deploy/history/{account_id}` is called
- **THEN** it SHALL return the most recent 20 deployment log entries for that account, sorted by `deployed_at` descending

#### Scenario: Query deployment history for all accounts
- **WHEN** `GET /api/deploy/history` is called without an account_id
- **THEN** it SHALL return the most recent 20 deployment log entries across all accounts

### Requirement: Stale deployment notification
The system SHALL detect when a session's deployed params differ from the strategy's currently active params in `param_registry`.

#### Scenario: Active params updated after deployment
- **WHEN** a session has `deployed_candidate_id=5` but the strategy's active candidate in `param_registry` is now `candidate_id=8`
- **THEN** the session's deployment info SHALL include `is_stale: true` and `active_candidate_id: 8`

#### Scenario: Deployed params match active
- **WHEN** the session's `deployed_candidate_id` matches the active candidate in `param_registry`
- **THEN** `is_stale` SHALL be `false`

### Requirement: Deployment panel shows backtest provenance
When displaying a deployed session, the system SHALL resolve the `deployed_candidate_id` back to its `param_runs` entry and include the backtest metrics (sharpe, total_pnl, win_rate, max_drawdown_pct, profit_factor) in the response.

#### Scenario: Deployed session includes backtest metrics
- **WHEN** the War Room fetches session data
- **THEN** each session with a `deployed_candidate_id` SHALL include a `backtest_metrics` object with at minimum `sharpe`, `total_pnl`, `win_rate`, and `max_drawdown_pct`

#### Scenario: Candidate without backtest metrics
- **WHEN** a candidate was created manually (no associated trial metrics)
- **THEN** `backtest_metrics` SHALL be `null` and a `"Unvalidated params"` warning SHALL be included
