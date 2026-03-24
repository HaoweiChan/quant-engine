## ADDED Requirements

### Requirement: Strategy Deployment Panel
The War Room SHALL display a Strategy Deployment Panel below the Account Overview. The panel SHALL show one deployment tile per active or deployed session, grouped by account.

Each deployment tile SHALL display:
- Strategy name (human-readable from registry)
- Symbol
- Deployed params summary (key values like `bar_agg=5, lots=4`)
- Backtest metrics badge: sharpe, PnL from the deployed candidate
- Session status badge (ACTIVE/PAUSED/STOPPED/NOT DEPLOYED)
- Stale-params indicator when deployed params differ from active params in param_registry
- Action buttons: Deploy (if not deployed), Start, Stop, Pause, Compare

#### Scenario: Session with deployed params shows metrics
- **WHEN** a session has a deployed candidate with backtest metrics
- **THEN** the tile SHALL show the strategy name, symbol, param summary, sharpe badge, PnL badge, and the session status

#### Scenario: No sessions for an account
- **WHEN** an account has no configured strategies
- **THEN** the deployment panel for that account SHALL show "No strategies deployed. Use the Backtest page to activate params, then deploy here."

#### Scenario: Stale params indicator
- **WHEN** the deployed candidate differs from the active candidate in param_registry
- **THEN** the tile SHALL show an orange "New params available" badge with the new sharpe value

### Requirement: Session lifecycle controls
Each deployment tile SHALL include Start, Stop, and Pause buttons that control the session's status via REST API calls.

#### Scenario: Start a stopped session
- **WHEN** the user clicks "Start" on a stopped session
- **THEN** the UI SHALL call `POST /api/sessions/{session_id}/start`
- **AND** the status badge SHALL update to ACTIVE after the next poll

#### Scenario: Stop an active session
- **WHEN** the user clicks "Stop" on an active session
- **THEN** the UI SHALL call `POST /api/sessions/{session_id}/stop`
- **AND** the status badge SHALL update to STOPPED after the next poll

#### Scenario: Pause an active session
- **WHEN** the user clicks "Pause" on an active session
- **THEN** the UI SHALL call `POST /api/sessions/{session_id}/pause`
- **AND** the status badge SHALL update to PAUSED (session continues monitoring but does not place new orders)

#### Scenario: Start requires deployed params
- **WHEN** the user clicks "Start" on a session with no deployed candidate
- **THEN** the button SHALL be disabled with tooltip "Deploy params first"

### Requirement: Deployment history table
The War Room SHALL include a collapsible "Deployment History" section below the deployment panel, showing the most recent 20 deployments across all accounts.

Each row SHALL display: Timestamp, Account, Strategy, Symbol, Sharpe (from deployed candidate), and a "Revert" action to re-deploy a previous candidate.

#### Scenario: History shows recent deployments
- **WHEN** the Deployment History section is expanded
- **THEN** it SHALL display the most recent 20 entries from `deployment_log`, sorted by timestamp descending

#### Scenario: Revert to previous deployment
- **WHEN** the user clicks "Revert" on a history entry
- **THEN** the system SHALL call `POST /api/deploy/{account_id}` with the previous entry's candidate_id
- **AND** a new log entry SHALL be created marking it as a revert

## MODIFIED Requirements

### Requirement: War Room sub-tab as default Trading view
The Trading primary tab SHALL display a War Room sub-tab as its second sub-tab. The War Room SHALL present a multi-panel layout showing all connected accounts, their active strategy sessions, and the Strategy Deployment Panel in a single view.

#### Scenario: War Room auto-refreshes via polling
- **WHEN** the War Room is displayed
- **THEN** a polling interval (default 15s, configurable) SHALL trigger a refresh, updating all account snapshots, session states, and deployment status

### Requirement: Account Overview panel
The War Room SHALL display an Account Overview panel at the top — a horizontal row of account cards, one per registered broker account.

Each account card SHALL display:
- Broker display name (e.g., "Sinopac TAIFEX")
- Connection status badge (LIVE in green, DISCONNECTED in red, MOCK in cyan)
- Total equity with day-over-day change
- Margin utilization as a percentage bar
- Number of active sessions
- Number of deployed strategies (new)

#### Scenario: Connected account shows live data
- **WHEN** a Sinopac account is connected and `get_account_snapshot()` returns `connected=True`
- **THEN** the account card SHALL show the LIVE badge in green, display real equity value, show margin used / margin available as a progress bar, and show the count of deployed strategies

#### Scenario: Disconnected account shows stale data
- **WHEN** a broker gateway returns `connected=False`
- **THEN** the account card SHALL show the DISCONNECTED badge in red, display last-known equity value grayed out, and show a "Last updated: {timestamp}" label
