## Why

The current dashboard layout does not adequately separate risk and margin pools across different brokerage accounts (e.g., Sinopac, Binance, Schwab). Mixing strategies from entirely separate capital bases on the same view is mathematically incoherent from a risk-management perspective. We need a Master-Detail "War Room" architecture that enforces strict margin isolation, ensuring the user only views the exposure, positions, and equity curve for a single selected account at a time.

## What Changes

- Replaces the dropdown filter for accounts with highly visual "Account Overview" cards as the primary navigational filter.
- Introduces an active account selection state (`activeAccountId`) to isolate the risk book.
- Updates the "Command Center" to only show data (Session Bar, Live Chart, Strategy Cards, Equity Curve, Open Positions, Alerts/Order Log) relevant to the actively selected account card.
- Auto-selects the account with the highest margin utilization or the first connected account on load to prevent a blank Command Center.
- Adds visual hierarchy styling (e.g., standard accent rings for the selected card, dimmed/inactive states for unselected cards).
- Optimizes rendering to prevent heavy re-renders across the dashboard when switching accounts (e.g., passing `key={activeAccountId}` to charts).

## Capabilities

### New Capabilities
- `war-room-dashboard`: Re-architecting the frontend dashboard to use a Master-Detail pattern with Account Cards for margin isolation and a filtered Command Center.

### Modified Capabilities
- `dashboard-ui`: Modifying the current dashboard requirements to enforce account-level data filtering on all components.

## Impact

- Frontend state management (Zustand) needs updating to include `activeAccountId` and relevant selectors.
- `CommandCenter` component and its children (`LiveChartPane`, `EquityCurvePane`, strategy cards, blotter) must be updated to consume only filtered session data.
- UI styling will be updated with Tailwind CSS to handle selected/unselected states for the new account cards.
- Chart lifecycle management will require adjustments to seamlessly unmount/remount lightweight-charts when switching accounts.
