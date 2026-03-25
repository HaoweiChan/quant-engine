## Context

Currently, the dashboard (Command Center) does not properly isolate margin pools and risk per account. It mixes strategies and data from different capital bases on the same screen, which is risky for a quantitative trading platform handling multiple broker integrations (Sinopac, Binance, Schwab). We need to shift to a Master-Detail pattern where "Account Cards" act as the primary navigational filter, ensuring all subsequent data (charts, strategies, PnL) is restricted to the selected account's margin pool. 

## Goals / Non-Goals

**Goals:**
- Implement a Master-Detail frontend architecture for the War Room dashboard.
- Update Zustand state to track `activeAccountId`.
- Refactor the Command Center to consume and display data exclusively for the `activeAccountId`.
- Prevent heavy re-renders when switching accounts or receiving background ticks from non-selected accounts.
- Ensure lightweight-charts clean up properly when switching contexts.

**Non-Goals:**
- Modifying the backend trading engine, risk monitor, or broker adapters (this is purely a frontend architectural update).
- Changing how data is fetched or pushed over websockets, only how it is filtered and displayed in the React tree.

## Decisions

**1. Zustand State Slicing for `activeAccountId`**
- **Decision:** Introduce `activeAccountId` to the main Zustand store (`useTradingStore` or equivalent) and use targeted selectors to retrieve session data.
- **Rationale:** By using selectors like `state.sessions.filter(s => s.accountId === state.activeAccountId)`, we ensure components like the Command Center only re-render when the *selected* account's data changes, ignoring updates from background accounts. 
- **Alternative:** Filtering data within the components themselves. This was rejected because it would still trigger React renders whenever any account updated, severely degrading performance.

**2. Chart Lifecycle Management via React Keys**
- **Decision:** Pass `key={activeAccountId}` to the wrapper component of the `lightweight-charts` instances (`LiveChartPane` and `EquityCurvePane`).
- **Rationale:** It forces React to destroy the DOM node and recreate it cleanly from scratch when the account switches. This eliminates the risk of "ghost data" or failed cleanup logic when manually attempting to wipe series data.
- **Alternative:** Manually calling `removeSeries()` and `addSeries()` on account change. Rejected because it is error-prone and can lead to memory leaks or rendering artifacts.

**3. Auto-Selection Fallback**
- **Decision:** On initial load, auto-select the account with the highest margin utilization, falling back to the first connected account if margin data isn't available.
- **Rationale:** Prevents the user from seeing a blank screen, maximizing the use of screen real estate and instantly highlighting the most critical risk area.

**4. Visual Hierarchy using Tailwind**
- **Decision:** Use `shadcn/ui` cards with distinct Tailwind classes for selection states. Selected: `ring-2 ring-[#69f0ae] ring-offset-2 ring-offset-[#0d0d26]`, Unselected: `opacity-50 hover:opacity-80 transition-opacity`.
- **Rationale:** Clearly identifies the active context without adding visual clutter to the dark theme (`#0d0d26`).

## Risks / Trade-offs

- **[Risk] Performance hit on initial load or account switch due to full DOM recreation of charts.**
  - **Mitigation:** `lightweight-charts` initializes very quickly. The minor cost of DOM recreation is vastly outweighed by the stability and guarantee of clean data boundaries between accounts.
- **[Risk] Websocket data for non-selected accounts might still cause state updates.**
  - **Mitigation:** Ensure that Zustand updates use immutable patterns correctly and that selectors are strictly memoized or primitive so that non-relevant updates don't cascade down the component tree.
