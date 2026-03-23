## Purpose

A multi-panel live trading command center within the Trading tab of the dashboard. Provides a real-time view of all connected broker accounts, active trading sessions, blotter activity, and aggregated risk metrics in a single dark-themed war room interface.

## Requirements

### Requirement: Accounts management page
The Trading tab SHALL include an Accounts sub-tab (the default active sub-tab) that displays a table of all configured broker accounts and provides CRUD operations for managing them.

The accounts table SHALL display columns: Account (with colored avatar initials), Connection (broker type), and Guards (count of active guards or "—"). Below the table, a "+ Add Account" link SHALL open the account creation flow.

#### Scenario: Accounts page loads with existing accounts
- **WHEN** the Accounts sub-tab is active and accounts exist in `trading.db`
- **THEN** the page SHALL display a table listing all accounts with their broker type and guard count

#### Scenario: No accounts configured
- **WHEN** the Accounts sub-tab is active and no accounts exist
- **THEN** the page SHALL display the empty table header and the "+ Add Account" link only

#### Scenario: Account row shows colored avatar
- **WHEN** an account row renders
- **THEN** it SHALL show a 2-letter avatar (first letters of broker and type, e.g., "SP" for sinopac) with a distinct background color per broker type

### Requirement: Account detail modal
Clicking an account row SHALL open a modal dialog with editable account settings. The modal SHALL contain:

1. **CONNECTION** section: Type dropdown (Sinopac/Binance/Schwab/CCXT), Exchange name input
2. **Mode toggles**: Sandbox Mode (on/off), Demo Trading (on/off)
3. **CREDENTIALS** section: API Key (password-masked input), API Secret (password-masked input), Password (optional, placeholder text)
4. **GUARDS** section: Max Drawdown % (number input), Max Margin % (number input), Max Daily Loss (number input)
5. **STRATEGIES** section: list of bound strategies with checkboxes, "+ Add Strategy" button
6. **Actions**: "Reconnect" button (tests connection), "Save" button (persists changes), "Delete" button (removes account)

#### Scenario: Open modal for existing account
- **WHEN** the user clicks an account row
- **THEN** a modal SHALL open pre-populated with that account's current settings, with credentials masked as dots

#### Scenario: Save credentials from modal
- **WHEN** the user enters API Key and Secret and clicks "Save"
- **THEN** credentials SHALL be written to GSM via `SecretManager` and non-secret metadata persisted to `trading.db`, and a success message SHALL appear

#### Scenario: Credential presence indicated
- **WHEN** the modal opens for an account whose credentials already exist in GSM
- **THEN** the credential fields SHALL show a status badge (e.g., "✓ Stored in GSM") instead of empty inputs, so the user knows secrets are already configured

#### Scenario: Reconnect tests connection
- **WHEN** the user clicks "Reconnect"
- **THEN** the system SHALL attempt to connect using the current credentials, showing a "Connecting..." message, then "Connected" (green) or "Failed: {error}" (red)

#### Scenario: Delete account with confirmation
- **WHEN** the user clicks "Delete"
- **THEN** a confirmation prompt SHALL appear ("Delete sinopac-main? This removes all credentials and history.")
- **WHEN** the user confirms
- **THEN** the account, credentials, and session history SHALL be deleted and the modal SHALL close

#### Scenario: Add new account flow
- **WHEN** the user clicks "+ Add Account"
- **THEN** the modal SHALL open with empty fields, a generated account ID suggestion, and the broker type dropdown focused

#### Scenario: Guards display on account table
- **WHEN** an account has 2 guards configured (e.g., max_drawdown_pct=15, max_margin_pct=80)
- **THEN** the Guards column SHALL show "2"
- **WHEN** an account has no guards configured
- **THEN** the Guards column SHALL show "—"

### Requirement: War Room sub-tab as default Trading view
The Trading primary tab SHALL display a War Room sub-tab as its second sub-tab. The War Room SHALL present a multi-panel layout showing all connected accounts and their active strategy sessions in a single view.

#### Scenario: War Room auto-refreshes via polling
- **WHEN** the War Room is displayed
- **THEN** a `dcc.Interval` component SHALL trigger a refresh every 15 seconds, updating all account snapshots and session states

### Requirement: Account Overview panel
The War Room SHALL display an Account Overview panel at the top — a horizontal row of account cards, one per registered broker account.

Each account card SHALL display:
- Broker display name (e.g., "Sinopac TAIFEX")
- Connection status badge (LIVE in green, DISCONNECTED in red, MOCK in cyan)
- Total equity with day-over-day change
- Margin utilization as a percentage bar
- Number of active sessions

#### Scenario: Connected account shows live data
- **WHEN** a Sinopac account is connected and `get_account_snapshot()` returns `connected=True`
- **THEN** the account card SHALL show the LIVE badge in green, display real equity value, and show margin used / margin available as a progress bar

#### Scenario: Disconnected account shows stale data
- **WHEN** a broker gateway returns `connected=False`
- **THEN** the account card SHALL show the DISCONNECTED badge in red, display last-known equity value grayed out, and show a "Last updated: {timestamp}" label

#### Scenario: Mock account shows MOCK badge
- **WHEN** the account uses `MockGateway`
- **THEN** the account card SHALL show the MOCK badge in cyan

### Requirement: Strategy Session Monitor cards
The War Room SHALL display one Strategy Session Monitor card per active `TradingSession`. Each monitor card SHALL be a self-contained panel showing:

- Session header: strategy name, symbol, account name, session status badge (ACTIVE/PAUSED/STOPPED)
- Stat row: Equity, Unrealized PnL, Drawdown %, Trade Count
- Equity curve chart (historical from snapshot store + latest point)
- Current positions table (from `SessionSnapshot.positions`)
- Current signal JSON display (from `SessionSnapshot.last_signal`)

#### Scenario: Single active session renders one monitor card
- **WHEN** there is one active `TradingSession` (ATR Mean Reversion on TX via Sinopac)
- **THEN** the War Room SHALL display one monitor card with that session's equity curve, positions, and signal

#### Scenario: Multiple sessions render multiple cards in grid
- **WHEN** there are 3 active sessions
- **THEN** the War Room SHALL display 3 monitor cards in a responsive CSS grid (2 columns on wide screens, 1 column on narrow)

#### Scenario: Session with no data shows placeholder
- **WHEN** a session has just started and `current_snapshot` is `None`
- **THEN** the monitor card SHALL show "Waiting for first data..." with a pulsing indicator

#### Scenario: Equity curve shows real historical data
- **WHEN** the session has been running for multiple days
- **THEN** the equity curve chart SHALL plot data from the `SnapshotStore` historical records, not mock data

#### Scenario: Positions table updates on poll
- **WHEN** a new `SessionSnapshot` arrives with updated positions
- **THEN** the positions table SHALL update to reflect current open positions with real-time unrealized P&L

### Requirement: Blotter sub-tab with unified activity feed
The Trading tab SHALL include a Blotter sub-tab showing a unified, time-ordered feed of all events across all sessions: fills, signals, risk alerts, and session state changes.

#### Scenario: Blotter shows fills across all accounts
- **WHEN** the Blotter sub-tab is active
- **THEN** it SHALL display a table of all recent fills from all connected accounts, sorted by timestamp descending, with columns: Time, Account, Strategy, Symbol, Side, Price, Qty, Fee

#### Scenario: Blotter updates on poll
- **WHEN** new fills arrive in any account's snapshot
- **THEN** the blotter table SHALL update to include the new fills on the next poll cycle

#### Scenario: Blotter supports filtering by account
- **WHEN** the user selects a specific account from the blotter filter dropdown
- **THEN** only fills from that account SHALL be displayed

### Requirement: Risk Overview sub-tab
The Trading tab SHALL include a Risk Overview sub-tab displaying aggregated risk metrics across all accounts and sessions.

The Risk Overview SHALL display:
- Stat row: Total Equity, Total Margin Used, Worst Drawdown, Total Unrealized PnL
- Per-account margin utilization chart (horizontal bar chart, one bar per account)
- Per-session drawdown comparison chart (grouped bar chart)
- Risk thresholds table (configurable per account: max drawdown %, max margin %)
- Alert history table (from risk monitor events)

#### Scenario: Risk Overview shows aggregate metrics
- **WHEN** the Risk Overview sub-tab is active with 2 connected accounts
- **THEN** Total Equity SHALL be the sum of both accounts' equity, and Worst Drawdown SHALL be the maximum drawdown across all sessions

#### Scenario: Margin utilization chart per account
- **WHEN** the margin chart renders
- **THEN** each account SHALL have a horizontal bar showing `margin_used / (margin_used + margin_available)` as a percentage, colored green below 50%, yellow 50-80%, red above 80%

#### Scenario: Risk Overview refreshes on poll
- **WHEN** the `dcc.Interval` fires
- **THEN** all risk metrics SHALL update from the latest session snapshots

### Requirement: War Room dark theme consistency
All War Room panels, monitor cards, and charts SHALL use the existing dashboard dark theme (`src/dashboard/theme.py`): navy backgrounds, JetBrains Mono for values, IBM Plex Serif for headings, standard accent colors.

#### Scenario: Account card uses dark card surface
- **WHEN** an account card renders
- **THEN** its background SHALL be `#0d0d26` with border `1px solid #1a1a38`, consistent with existing stat cards

#### Scenario: Session monitor equity chart uses standard Plotly theme
- **WHEN** an equity curve chart renders in a session monitor
- **THEN** it SHALL use `DARK_CHART_LAYOUT` from `theme.py` with `#69f0ae` for the equity line

### Requirement: Sidebar controls for War Room
The War Room sidebar SHALL contain:
- Polling interval selector (5s, 15s, 30s, 60s)
- Account filter (All / specific account)
- Session status filter (Active / Paused / All)

#### Scenario: Changing poll interval updates dcc.Interval
- **WHEN** the user selects 30s polling interval
- **THEN** the `dcc.Interval` component SHALL update its interval to 30000ms

#### Scenario: Filtering by account hides other sessions
- **WHEN** the user selects "Sinopac TAIFEX" from the account filter
- **THEN** only session monitor cards for that account SHALL be visible
