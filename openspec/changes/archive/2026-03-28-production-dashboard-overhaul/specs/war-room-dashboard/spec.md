## ADDED Requirements

### Requirement: War Room top bar with emergency controls
The War Room SHALL display a persistent top bar above the command center containing: account equity summary, total margin ratio, broker heartbeat indicator (latency in ms with color badge), and two emergency buttons — "HALT ALL" (amber background) and "FLATTEN ALL" (red background). The top bar SHALL remain visible regardless of page scroll.

#### Scenario: Top bar renders with live metrics
- **WHEN** the War Room loads with an active account selected
- **THEN** the top bar SHALL display: total equity, margin ratio %, heartbeat latency, and both kill switch buttons

#### Scenario: Top bar fixed on scroll
- **WHEN** the user scrolls down the War Room content
- **THEN** the top bar SHALL remain pinned to the top of the viewport (sticky/fixed positioning)

#### Scenario: Heartbeat indicator updates
- **WHEN** the heartbeat poll returns 47ms for the active broker
- **THEN** the indicator SHALL display "47ms" with a green dot

### Requirement: Position exposure matrix
The War Room command center SHALL include a Position Exposure Matrix table showing all open positions for the active account. Columns: Asset, Direction (Long/Short), Size, Entry Price, Current Price, Unrealized PnL, Strategy, and Net Beta Exposure (if available).

#### Scenario: Positions render in matrix
- **WHEN** the active account has 3 open positions
- **THEN** the matrix SHALL display 3 rows with all column values populated from the account snapshot

#### Scenario: PnL color coding
- **WHEN** a position has positive unrealized PnL
- **THEN** the PnL cell SHALL be green; negative PnL SHALL be red

#### Scenario: Empty state
- **WHEN** the active account has no open positions
- **THEN** the matrix SHALL display "No open positions" with a muted style

#### Scenario: Matrix updates on poll
- **WHEN** a new account snapshot arrives with changed position data
- **THEN** the matrix SHALL update prices and PnL values without a full page refresh

### Requirement: Live order blotter pane
The War Room command center SHALL include an Order Blotter pane streaming real-time order events via the `/ws/blotter` WebSocket. Each row SHALL display: Time, Strategy, Symbol, Side, Type (submission/fill/rejection), Expected Price, Fill Price, Slippage (bps), Quantity, Fee.

#### Scenario: Fill event appears in real-time
- **WHEN** a fill event arrives via WebSocket
- **THEN** a new row SHALL be prepended to the blotter table with fill details and computed slippage

#### Scenario: Rejection highlighted
- **WHEN** a rejection event arrives
- **THEN** the row SHALL be highlighted in red with the rejection reason displayed in the last column

#### Scenario: Blotter scrolls with new entries
- **WHEN** more than 50 events are in the blotter
- **THEN** the pane SHALL be scrollable, showing the most recent events at the top

### Requirement: Risk limiter display panel
The War Room command center SHALL include a Risk Limiter panel showing the status of active risk guards for the selected account. Each guard SHALL display: parameter name, current value, limit value, and a visual progress bar.

#### Scenario: Daily loss guard within limits
- **WHEN** the account's max daily loss guard is set to $10,000 and current daily loss is $2,000
- **THEN** the panel SHALL display "Max Daily Loss: $2,000 / $10,000" with a green progress bar at 20%

#### Scenario: Guard approaching limit
- **WHEN** current daily loss is $8,500 out of $10,000 limit
- **THEN** the progress bar SHALL be yellow/amber at 85%

#### Scenario: Guard breached
- **WHEN** current drawdown exceeds the max drawdown guard
- **THEN** the progress bar SHALL be red and a "BREACHED" badge SHALL appear next to the guard name

## MODIFIED Requirements

### Requirement: Master-Detail Visual Wireframe
The overall War Room dashboard layout MUST match the updated visual structure with emergency controls and exposure monitoring:

```text
====================================================================================================
[  Logo  ]   Home   |   Data Hub   |   Strategy   |   [ TRADING ]                        [ ⚙️ ] [👤]
====================================================================================================
         |
         |  [ Accounts ]   [ WAR ROOM ]   [ Blotter ]   [ Risk Overview ]
         |  ------------------------------------------------------------------------------------
         |
         |  ┌────────────────────────────────────────────────────────────────────────────────────┐
         |  │ TOP BAR: $105,240 │ Margin: 45% │ ♥ 47ms │ [HALT ALL] [FLATTEN ALL]              │
         |  └────────────────────────────────────────────────────────────────────────────────────┘
         |
         |  [ ACCOUNT MARGIN OVERVIEW ] (Click a card to isolate risk book)
         |  +=========================+  +-------------------------+  +-------------------------+
         |  | [SP] Sinopac TAIFEX     |  | [BN] Binance Futures    |  | [SB] Schwab MOCK        |
         |  | [◉ SELECTED ]           |  | Status: [● LIVE]        |  | Status: [○ MOCK]        |
         |  +=========================+  +-------------------------+  +-------------------------+
         |
         |  [ COMMAND CENTER: Sinopac TAIFEX ]
         |  ┌────────────────────────────────┬──────────────────────────────────────────────────┐
         |  │  LIVE CHART                    │  STRATEGY CARDS                                  │
         |  │  + EQUITY CURVE                │                                                  │
         |  ├────────────────────────────────┴──────────────────────────────────────────────────┤
         |  │  POSITION EXPOSURE MATRIX (Asset, Dir, Size, Entry, Current, UnPnL, Beta)        │
         |  ├──────────────────────────────────┬───────────────────────────────────────────────┤
         |  │  ORDER BLOTTER (live stream)      │  RISK LIMITERS (guard status bars)            │
         |  └──────────────────────────────────┴───────────────────────────────────────────────┘
====================================================================================================
```

#### Scenario: Visual layout conforms to wireframe
- **WHEN** the user navigates to the War Room dashboard
- **THEN** the UI layout, grouping, and hierarchy SHALL explicitly match the structure demonstrated in the updated Master-Detail wireframe, including the top bar with emergency controls
