# kill-switch

## Purpose
TBD — synced from change `production-dashboard-overhaul`.

## Requirements

### Requirement: Kill switch API endpoints
The backend SHALL expose two emergency endpoints that bypass standard order queues:

1. `POST /api/kill-switch/halt` — sets a global `HALT` flag, pausing all active trading sessions and preventing new order submissions.
2. `POST /api/kill-switch/flatten` — for each account with open positions, submits immediate market-order closes via the execution engine with `urgent=True` to skip throttling.

Both endpoints SHALL require a `confirm` field in the request body set to the string `"CONFIRM"`.

#### Scenario: Halt all trading
- **WHEN** `POST /api/kill-switch/halt` is called with `{ "confirm": "CONFIRM" }`
- **THEN** all active trading sessions SHALL transition to `paused` state, and no new orders SHALL be submitted until the halt is lifted

#### Scenario: Halt rejected without confirmation
- **WHEN** `POST /api/kill-switch/halt` is called without `confirm: "CONFIRM"`
- **THEN** the server SHALL return HTTP 400 with error message "Confirmation required"

#### Scenario: Flatten all positions
- **WHEN** `POST /api/kill-switch/flatten` is called with `{ "confirm": "CONFIRM" }`
- **THEN** for each connected account, the server SHALL submit market-order closes for all open positions and return a summary of actions taken per account

#### Scenario: Flatten with disconnected broker
- **WHEN** flatten is called and one broker account is disconnected
- **THEN** the response SHALL include a per-account status: `{ "sinopac-main": "flattened 2 positions", "binance-futures": "error: broker disconnected" }`

#### Scenario: Flatten idempotent when no positions
- **WHEN** flatten is called and no accounts have open positions
- **THEN** the response SHALL return success with `{ "message": "No open positions to flatten" }`

### Requirement: Kill switch resume endpoint
The backend SHALL expose `POST /api/kill-switch/resume` to lift the global halt flag and allow trading sessions to resume.

#### Scenario: Resume after halt
- **WHEN** `POST /api/kill-switch/resume` is called with `{ "confirm": "CONFIRM" }`
- **THEN** the global halt flag SHALL be cleared, and previously-paused sessions SHALL remain paused (operator must manually restart them)

#### Scenario: Resume when not halted
- **WHEN** resume is called and no halt is active
- **THEN** the response SHALL return HTTP 200 with `{ "message": "No active halt" }`

### Requirement: Kill switch UI controls
The War Room top bar SHALL display two prominent emergency buttons: "HALT ALL" (amber) and "FLATTEN ALL" (red). Both buttons SHALL require a confirmation dialog where the user types "CONFIRM" before the action is dispatched.

#### Scenario: HALT ALL button triggers confirmation
- **WHEN** the user clicks the "HALT ALL" button
- **THEN** a modal SHALL appear with text "Type CONFIRM to halt all trading" and an input field

#### Scenario: FLATTEN ALL button triggers confirmation
- **WHEN** the user clicks the "FLATTEN ALL" button
- **THEN** a modal SHALL appear with text "Type CONFIRM to flatten all positions" and an input field

#### Scenario: Confirmation accepted
- **WHEN** the user types "CONFIRM" and clicks submit in the kill switch dialog
- **THEN** the frontend SHALL POST to the corresponding endpoint and display a success/error toast

#### Scenario: Confirmation rejected
- **WHEN** the user types anything other than "CONFIRM" and clicks submit
- **THEN** the dialog SHALL show an inline error "You must type CONFIRM exactly" and SHALL NOT dispatch the API call

#### Scenario: Kill switch buttons always visible
- **WHEN** the War Room tab is active
- **THEN** the HALT ALL and FLATTEN ALL buttons SHALL be visible in the top bar regardless of scroll position
