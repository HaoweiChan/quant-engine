## Context

The frontend currently has four primary tabs: Data Hub, Strategy, Backtest, Trading. The Strategy page holds sub-tabs (Code Editor, Optimizer, Grid Search, Monte Carlo), each with isolated local state for symbol, dates, and parameters. The standalone Backtest page duplicates strategy selection and parameter inputs. The Trading/War Room shows account equity and strategy cards but lacks emergency controls, position exposure, latency monitoring, and live order streaming.

Each sub-tab fetches its own strategy list and manages parameters independently. There is no shared state for the full parameter vector θ, meaning results across tabs cannot be compared or reproduced. The Monte Carlo simulation uses a naive i.i.d. bootstrap (`Math.random() * dailyReturns.length`) that underestimates tail risk.

### Current Frontend Architecture

```
App
├── DataHub
├── Strategy
│   ├── CodeEditor      (local state: strategy)
│   ├── Optimizer       (local state: strategy, symbol, dates, params)
│   ├── GridSearch      (local state: strategy, symbol, dates, xParam, yParam)
│   └── MonteCarlo      (local state: strategy, symbol, dates, nPaths, nDays)
├── Backtest            (local state: strategy, symbol, dates, params) ← SEPARATE PAGE
└── Trading
    ├── Accounts
    ├── WarRoom          (polling /api/war-room every 15s)
    ├── Blotter
    └── Risk
```

## Goals / Non-Goals

**Goals:**
- Eliminate parameter opacity by creating a single global parameter context for the entire Strategy page
- Merge Backtest into Strategy as "Tear Sheet" tab; combine Optimizer + Grid Search into "Param Sweep"
- Add production-grade War Room controls: kill switch, heartbeat monitor, slippage tracker, exposure matrix
- Replace naive MC bootstrap with block-bootstrap; add VaR/CVaR quantile outputs
- Log immutable run provenance (param hash, dates, costs, commit) for every execution

**Non-Goals:**
- Building a full OMS (Order Management System) — we use the existing execution engine
- Implementing a real-time P&L attribution engine (portfolio analytics beyond position-level)
- Adding new broker integrations — existing Sinopac/Binance/Schwab adapters are sufficient
- Migrating away from React/Zustand/Vite — we extend the existing stack
- Building GARCH model fitting UI — the backend GARCH sampler is used transparently by the stress test

## Decisions

### D1: Zustand store for global parameter context (`useStrategyStore`)

**Decision**: Create a new `strategyStore.ts` Zustand store holding `{ strategy, symbol, startDate, endDate, slippageBps, commissionBps, params: Record<string, number> }`. All Strategy sub-tabs read from this store instead of local state.

**Why not React Context?** Zustand is already the state library. Context causes full subtree re-renders on any change; Zustand's selector pattern avoids this. Consistency with existing `useUiStore`, `useBacktestStore`, `useTradingStore`.

**Why not Redux/Jotai?** Adding a new state library is unnecessary complexity. Zustand handles this cleanly.

### D2: Tab restructuring — merge Backtest into Strategy, unify sweep tabs

**Decision**: Remove `Backtest` from the primary tab bar. New Strategy sub-tabs:

```
Strategy
├── Code Editor     (view/edit strategy source code)
├── Tear Sheet      (single backtest with full metrics — formerly Backtest page)
├── Param Sweep     (unified Grid Search + Optimizer)
└── Stress Test     (Monte Carlo with block-bootstrap, VaR, CVaR)
```

**Why unify Grid Search + Optimizer?** They solve the same problem (navigate parameter space) with different algorithms. The UI selects the sweep method (grid, random, genetic) and displays results uniformly as heatmaps + ranked trials table. This matches the critique in `research-suite-integration.md`.

**Why "Tear Sheet" not "Backtest"?** Institutional convention. A tear sheet is the artifact produced by a single backtest run — equity curve, drawdown, trade log, and key metrics. The name signals this is an evaluation output, not a separate workflow.

### D3: Run provenance logging

**Decision**: Every backtest/sweep/stress-test execution sends a provenance record to `POST /api/backtest` alongside the existing request payload:

```json
{
  "provenance": {
    "param_hash": "sha256 of sorted JSON param dict",
    "date_range": ["2025-08-01", "2026-03-14"],
    "cost_model": { "slippage_bps": 5, "commission_bps": 2 },
    "git_commit": "abc123f"
  }
}
```

Stored in `param_runs` table (already exists). The frontend computes `param_hash` client-side using `crypto.subtle.digest`. Git commit comes from a `/api/meta` endpoint returning `HEAD` short-sha.

**Alternative considered**: Server-side-only provenance. Rejected because the client knows the exact UI state; server would have to trust the payload contains the right params.

### D4: Kill switch architecture

**Decision**: Two-button control in the War Room top bar:

1. **HALT ALL** — `POST /api/kill-switch/halt` → sets a global `HALT` flag in the trading session manager, preventing new order submissions. All active sessions transition to `paused` state.
2. **FLATTEN ALL** — `POST /api/kill-switch/flatten` → for each open position, submits immediate market-order close via the execution engine, bypassing the position engine's normal signal flow.

Both buttons require a confirmation dialog ("Type CONFIRM to proceed"). The backend uses the existing `ExecutionEngine.submit_order()` with `OrderType.MARKET` and `urgent=True` flag to skip queue throttling.

**Why not a single button?** Halting (stop new orders) and flattening (close existing positions) are operationally distinct. A flash crash may warrant halting new entries while letting profitable positions run. Separate controls give the operator granularity.

### D5: Block-bootstrap Monte Carlo (backend)

**Decision**: Add `BlockBootstrapMC` class in `src/monte_carlo/block_bootstrap.py`:

```
BlockBootstrapMC
├── fit(daily_returns: ndarray) → self
├── simulate(n_paths, n_days, initial_equity) → paths: ndarray
└── summary() → { var_95, var_99, cvar_95, cvar_99, median_final, prob_ruin }
```

Block length selected via Politis-Romano automatic block-length selection (stationary bootstrap variant). Optionally supports GARCH(1,1) filtered residuals via the `arch` package — fit GARCH, extract standardized residuals, block-resample those, then re-apply volatility dynamics.

**Why not frontend JS bootstrap?** The current `simulatePaths` runs in the browser. For 1000 paths × 252 days with GARCH filtering, Python + numpy is 10-100x faster and avoids blocking the UI thread. The frontend calls `POST /api/monte-carlo` and receives pre-computed paths + summary stats.

### D6: War Room layout restructure

**Decision**: New War Room layout:

```
┌──────────────────────────────────────────────────────────┐
│ TOP BAR: Equity │ Margin% │ Heartbeat(ms) │ [HALT] [FLATTEN] │
├──────────────┬───────────────────────────────────────────┤
│              │  LIVE CHART + EQUITY CURVE                │
│  ACCOUNT     ├───────────────────────────────────────────┤
│  SELECTOR    │  POSITION MATRIX (real-time exposure)     │
│              ├─────────────────────┬─────────────────────┤
│              │  ORDER BLOTTER      │  RISK LIMITERS      │
│              │  (live stream)      │  (guardrails status) │
└──────────────┴─────────────────────┴─────────────────────┘
```

The heartbeat monitor polls `/api/heartbeat` every 5 seconds, returning `{ broker: "sinopac", latency_ms: 47, timestamp: "..." }`. Displayed as a colored badge: green < 100ms, yellow < 500ms, red ≥ 500ms.

The slippage tracker is a column in the order blotter: `Expected Price`, `Fill Price`, `Slippage (bps)`. When trailing-average slippage exceeds 2× the cost model assumption, an alert fires.

### D7: Backend cost model injection

**Decision**: Extend the backtest API to accept `slippage_bps` and `commission_bps` as optional parameters (default 0). The simulator applies costs per-trade:

```
effective_entry = entry_price * (1 + slippage_bps/10000 * direction)
commission = notional * commission_bps / 10000
```

This feeds into tear sheet metrics (net Sharpe, net PnL). The global param context sidebar displays these prominently so the user never runs a zero-cost backtest unknowingly.

## Risks / Trade-offs

- **[Kill switch bypasses normal flow]** → Flatten-all sends raw market orders through the execution engine. Mitigation: the endpoint validates broker connectivity before submitting; if a broker is disconnected, it returns an error per-account rather than silently failing.

- **[Block-bootstrap adds backend latency]** → 1000-path × 252-day simulation with GARCH takes ~2-5 seconds. Mitigation: run as async task with WebSocket progress streaming (reuse existing `ws/backtest` pattern); cache results keyed by param_hash + date_range.

- **[Tab restructure breaks bookmarks/links]** → Users with saved URLs to `/backtest` will 404. Mitigation: add a redirect from `/backtest` → `/strategy?tab=tearsheet` in the router.

- **[Global param state may desync]** → If a user modifies params mid-sweep, results become inconsistent. Mitigation: lock param inputs while a sweep/stress-test is running (disabled state + visual indicator).

- **[Scope is large]** → This is a multi-week change touching frontend, backend, and engine. Mitigation: implement in phases — (1) global param context + tab restructure, (2) kill switch + War Room layout, (3) block-bootstrap MC, (4) provenance logging. Each phase is independently deployable.

## Open Questions

1. Should the heartbeat monitor ping all connected brokers simultaneously, or only the active account's broker?
2. What block-length selection method for the bootstrap — fixed (e.g., 10 days), Politis-Romano automatic, or user-configurable?
3. Should the kill switch require 2FA/password confirmation in addition to the "type CONFIRM" dialog for production accounts?
