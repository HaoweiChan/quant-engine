## 1. State Management Update

- [x] 1.1 Add `activeAccountId` to Zustand global store (`useTradingStore`).
- [x] 1.2 Create selectors to filter sessions, active positions, and recent fills by `activeAccountId`.
- [x] 1.3 Add an initialization action to auto-select the account with highest margin utilization (or first connected) on app load if `activeAccountId` is null.

## 2. UI Refactoring: Account Overview

- [x] 2.1 Refactor the Account Overview section to use interactive `shadcn/ui` cards instead of a static display.
- [x] 2.2 Add click handlers to Account cards to dispatch `activeAccountId` updates.
- [x] 2.3 Apply dynamic Tailwind classes (`ring-2 ring-[#69f0ae]` for selected, `opacity-50 hover:opacity-80` for unselected) to Account cards based on global state.
- [x] 2.4 Ensure the "All Accounts" or specific account filter dropdown is removed from the sidebar.

## 3. Command Center Isolation

- [x] 3.1 Update `CommandCenter` component to only subscribe to data filtered by `activeAccountId` via the new selectors.
- [x] 3.2 Update `LiveChartPane` to use `activeAccountId` as its React `key` to force clean recreation on account switch.
- [x] 3.3 Update `EquityCurvePane` to use `activeAccountId` as its React `key`.
- [x] 3.4 Verify Strategy Cards inside the Command Center only render for the selected account.

## 4. Blotter and Order Log Integration

- [x] 4.1 Update Blotter components (Alerts / Order Log) to respect the active account filter natively instead of requiring manual selection.
- [x] 4.2 Validate that the unified activity feed properly isolates to the active margin pool.

## 5. Testing and Validation

- [x] 5.1 Test switching between multiple active accounts (e.g., Sinopac and Binance) to ensure data doesn't bleed.
- [x] 5.2 Validate chart unmount/remount performance and lack of ghost data.
- [x] 5.3 Verify edge case when no accounts are connected (empty state handling).
