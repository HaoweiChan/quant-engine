## MODIFIED Requirements

### Requirement: Account Overview panel
The War Room SHALL display an Account Overview panel at the top — a horizontal row of account cards, one per registered broker account.

Each account card SHALL act as the primary navigational filter for the Command Center. Clicking a card SHALL set it as the `activeAccountId` in the global state, isolating all downstream data (charts, strategies, PnL) to that specific account's margin pool.

Each account card SHALL display:
- Broker display name (e.g., "Sinopac TAIFEX")
- Connection status badge (LIVE in green, DISCONNECTED in red, MOCK in cyan)
- Total equity with day-over-day change
- Margin utilization as a percentage bar
- Visual selection state:
  - **Selected Card**: Distinct accent ring (e.g., `ring-2 ring-[#69f0ae]`) and full opacity
  - **Unselected Cards**: Dimmed (e.g., `opacity-50`) but interactive on hover

#### Scenario: Connected account shows live data
- **WHEN** a Sinopac account is connected and `get_account_snapshot()` returns `connected=True`
- **THEN** the account card SHALL show the LIVE badge in green, display real equity value, and show margin used / margin available as a progress bar

#### Scenario: Disconnected account shows stale data
- **WHEN** a broker gateway returns `connected=False`
- **THEN** the account card SHALL show the DISCONNECTED badge in red, display last-known equity value grayed out, and show a "Last updated: {timestamp}" label

#### Scenario: Mock account shows MOCK badge
- **WHEN** the account uses `MockGateway`
- **THEN** the account card SHALL show the MOCK badge in cyan

#### Scenario: Clicking an account card isolates view
- **WHEN** the user clicks an unselected account card
- **THEN** the system SHALL set that account as the `activeAccountId`
- **AND** the Command Center (strategy cards, charts, blotter) SHALL update to show only data for the selected account
- **AND** the clicked card SHALL visually highlight as selected while other cards dim

#### Scenario: Auto-selection on initial load
- **WHEN** the War Room loads and `activeAccountId` is null
- **THEN** the system SHALL auto-select the account with the highest margin utilization
- **AND** if no margin data is available, it SHALL fall back to selecting the first connected account
- **AND** it SHALL NOT show a blank Command Center


## ADDED Requirements

### Requirement: Master-Detail Visual Wireframe
The overall War Room dashboard layout MUST match the visual structure and hierarchy of the provided Master-Detail wireframe exactly. The layout separates the top account filter cards from the downstream Command Center.

```text
=================================================================================================
[  Logo  ]   Home   |   Data Hub   |   Strategy   |   [ TRADING ]                     [ ⚙️ ] [👤]
=================================================================================================
          |
[SIDEBAR] |  [ Accounts ]   [ WAR ROOM ]   [ Blotter ]   [ Risk Overview ]
          |  ------------------------------------------------------------------------------------
 POLL:    | 
 [ 15s ▼] |  [ ACCOUNT MARGIN OVERVIEW ] (Click a card to isolate risk book)
          |  +=========================+  +-------------------------+  +-------------------------+
 FILTERS: |  | [SP] Sinopac TAIFEX     |  | [BN] Binance Futures    |  | [SB] Schwab MOCK        |
          |  | [◉ SELECTED ]           |  | Status: [● LIVE]        |  | Status: [○ MOCK]        |
 Status:  |  | Equity: $105,240        |  | Equity: $52,100         |  | Equity: $10,000         |
 [ All ▼] |  | Margin: [====||       ] |  | Margin: [==||         ] |  | Margin: [||           ] |
          |  +=========================+  +-------------------------+  +-------------------------+
          |      ▲ (Active Glow / Ring)       (Dimmed/Inactive)            (Dimmed/Inactive)
          |
          |  [ COMMAND CENTER: Sinopac TAIFEX ] (Showing 2 Configured Strategies)
          |  ┌──────────────────────────────────────────────────────────────────────────────────┐
          |  │ SESSION BAR: Acct Equity: $105,240 | Acct PnL: +$320 | Open Pos: 2 | Margin: 45% │
          |  ├──────────────────────────────────┬───────────────────────────────────────────────┤
          |  │                                  │  STRATEGY CARDS (Filtered by Sinopac)         │
          |  │  LIVE CHART (Lightweight Charts) │  [ ATR Mean Rev. ]                            │
          |  │  Symbol: TX / MTX                │  [ Stage 2/4 | UnPnL: +$320 | 🟢 ACTIVE ]     │
          |  │                                  │                                               │
          |  │     |                            │  [ Trend Following ]                          │
          |  │    -+-  <-- Entry Marker         │  [ Flat      | UnPnL: $0    | ⏸ PAUSED ]      │
          |  │     |                            │                                               │
          |  │    _|_                           │                                               │
          |  │   (ATR Stop Band: $19,450)       │                                               │
          |  │                                  │                                               │
          |  ├──────────────────────────────────┼───────────────────────────────────────────────┤
          |  │  EQUITY CURVE (Sinopac Only)     │  OPEN POSITIONS TABLE (Sinopac Only)          │
          |  │            _.-/                  │  Sym | Strategy | Stage | Entry  | PnL | Stop │
          |  │         .-'                      │  TX  | ATR Mean | 2/4   | 19500  | +320| 19450│
          |  │  ___.-''                         │                                               │
          |  ├──────────────────────────────────┴───────────────────────────────────────────────┤
          |  │  ALERTS / ORDER LOG (Unified Blotter - Filtered to Sinopac TAIFEX)               │
          |  │  17:15:02 | TX  | FILL  | BUY 1 @ 19,500 | Strategy: ATR Mean Rev                │
          |  └──────────────────────────────────────────────────────────────────────────────────┘
=================================================================================================
```

#### Scenario: Visual layout conforms to wireframe
- **WHEN** the user navigates to the War Room dashboard
- **THEN** the UI layout, grouping, and hierarchy SHALL explicitly match the structure demonstrated in the Master-Detail wireframe


## REMOVED Requirements

### Requirement: Sidebar controls for War Room
**Reason**: The Account filter dropdown is replaced by the visual Account Overview cards as the primary navigational filter, per the Master-Detail architecture redesign. The polling interval and session status filters are retained in the UI but moved out of a dedicated sidebar.
**Migration**: Use the Account Overview cards at the top of the War Room to filter by account.
