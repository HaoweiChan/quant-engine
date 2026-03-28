## 1. Global Parameter Context (Frontend)

- [x] 1.1 Create `frontend/src/stores/strategyStore.ts` Zustand store with fields: `strategy`, `symbol`, `startDate`, `endDate`, `slippageBps`, `commissionBps`, `params`, and actions `setStrategy`, `setSymbol`, `setDates`, `setCosts`, `setParam`, `resetParams`. **Acceptance**: store exports type-safe hook, defaults populated from first strategy.
- [x] 1.2 Create `StrategyParamSidebar` component (`frontend/src/components/StrategyParamSidebar.tsx`) rendering: strategy dropdown, symbol selector, date range pickers, slippage/commission inputs, and dynamic param inputs from `useStrategyStore`. **Acceptance**: sidebar renders all params for selected strategy with correct min/max/step from `param_grid`.
- [x] 1.3 Wire `StrategyParamSidebar` into `Strategy.tsx` as a persistent left pane (234px), visible across all sub-tabs. **Acceptance**: sidebar remains visible when switching between Code Editor, Tear Sheet, Param Sweep, Stress Test.
- [x] 1.4 Add param locking behavior: disable all sidebar inputs when `useBacktestStore.loading` is true or a sweep/stress-test is in progress. **Acceptance**: inputs show disabled state during execution, re-enable on completion/error.

## 2. Tab Restructure (Frontend)

- [x] 2.1 Update `uiStore.ts`: change `PrimaryTab` to `"datahub" | "strategy" | "trading"` (remove `"backtest"`). Change `StrategySubTab` to `"editor" | "tearsheet" | "paramsweep" | "stresstest"`. **Acceptance**: TypeScript compiles with no type errors.
- [x] 2.2 Update primary tab bar in `App.tsx` (or equivalent layout component) to show three tabs: Data Hub, Strategy, Trading. Remove Backtest tab. Add redirect from `/backtest` → `/strategy?tab=tearsheet`. **Acceptance**: clicking old Backtest link navigates to Tear Sheet.
- [x] 2.3 Move `Backtest.tsx` content into a new `TearSheet.tsx` component under `frontend/src/pages/strategy/`. Refactor to read strategy/symbol/dates/params/costs from `useStrategyStore` instead of local state. Remove the standalone sidebar (now handled by global `StrategyParamSidebar`). **Acceptance**: Tear Sheet renders backtest results using global params, run history panel works.
- [x] 2.4 Create `ParamSweep.tsx` component (`frontend/src/pages/strategy/ParamSweep.tsx`) combining Grid Search + Optimizer. Add method selector dropdown (Grid/Random/Walk-Forward). Sweep variables selected from global param list; non-swept params locked to global values. **Acceptance**: grid search with 2 swept params renders heatmap; random search renders ranked table.
- [x] 2.5 Rename `MonteCarlo.tsx` → `StressTest.tsx`, refactor to call `POST /api/monte-carlo` instead of running simulation client-side. Read params from `useStrategyStore`. Add method selector (Block Bootstrap / Circular / GARCH-Filtered). Display VaR/CVaR stat cards. **Acceptance**: stress test runs server-side and displays path fan chart + risk stat cards.
- [x] 2.6 Update `Strategy.tsx` sub-tab definitions to `[editor, tearsheet, paramsweep, stresstest]` and wire new components. Delete old `GridSearch.tsx` and `Optimizer.tsx`. **Acceptance**: all 4 sub-tabs render correctly under Strategy.

## 3. Run Provenance (Frontend + Backend)

- [x] 3.1 Add `GET /api/meta` endpoint in `src/api/routes/` returning `{ "git_commit": "<short-sha>", "version": "<semver>" }`. Handle non-git environments gracefully. **Acceptance**: endpoint returns JSON with valid commit hash or "unknown".
- [x] 3.2 Add `computeParamHash()` utility in `frontend/src/lib/provenance.ts` using `crypto.subtle.digest('SHA-256', ...)` on JSON-serialized sorted param dict. **Acceptance**: same params produce identical hash across runs.
- [x] 3.3 Update `runBacktest()` API call to include `provenance: { param_hash, date_range, cost_model, git_commit }` in the request body. Update the backend `/api/backtest/run` handler to accept and store provenance in `param_runs`. **Acceptance**: provenance record persisted for each backtest run.

## 4. Kill Switch (Backend + Frontend)

- [x] 4.1 Create `src/api/routes/kill_switch.py` with three endpoints: `POST /api/kill-switch/halt`, `POST /api/kill-switch/flatten`, `POST /api/kill-switch/resume`. Implement confirmation validation (`confirm == "CONFIRM"`). **Acceptance**: halt pauses all sessions, flatten sends market closes, resume lifts halt flag. Missing confirmation returns 400.
- [x] 4.2 Add global halt flag to the trading session manager (e.g., `SessionManager.halt_active: bool`). When halted, `submit_order()` SHALL reject new orders. **Acceptance**: orders submitted during halt are rejected with "trading halted" error.
- [x] 4.3 Create `KillSwitchBar` component in `frontend/src/components/KillSwitchBar.tsx` with HALT ALL (amber) and FLATTEN ALL (red) buttons. Add confirmation modal with "type CONFIRM" input. **Acceptance**: buttons appear in War Room top bar, confirmation flow works, API called on confirm.

## 5. Heartbeat & Execution Monitor (Backend + Frontend)

- [x] 5.1 Add `GET /api/heartbeat` endpoint that pings each connected broker gateway and returns `HeartbeatResponse` with per-broker latency and status. **Acceptance**: returns latency for connected brokers, `null` for disconnected.
- [x] 5.2 Add `HeartbeatIndicator` component in `frontend/src/components/HeartbeatIndicator.tsx` polling `/api/heartbeat` every 5s. Display latency with color badge (green < 100ms, yellow < 500ms, red >= 500ms). **Acceptance**: indicator updates in War Room top bar with correct coloring.
- [x] 5.3 Create `/ws/blotter` WebSocket endpoint in `src/api/ws/blotter.py` streaming `BlotterEvent` messages for fills, submissions, and rejections. **Acceptance**: WebSocket broadcasts events in real-time as orders flow through execution engine.
- [x] 5.4 Create `useBlotter` React hook in `frontend/src/hooks/useBlotter.ts` managing `/ws/blotter` WebSocket connection with reconnection. **Acceptance**: hook provides `events: BlotterEvent[]` array, auto-reconnects on disconnect.
- [x] 5.5 Implement slippage tracking: compute trailing-average slippage over last 20 fills. Fire risk alert when trailing avg exceeds 2× cost model assumption. **Acceptance**: alert appears in risk tab when slippage spikes.

## 6. War Room Layout Restructure (Frontend)

- [x] 6.1 Create `WarRoomTopBar` component combining equity summary, margin ratio, `HeartbeatIndicator`, and `KillSwitchBar`. Style as sticky header. **Acceptance**: top bar renders above command center and stays fixed on scroll.
- [x] 6.2 Refactor `WarRoomTab` layout to match updated wireframe: top bar → account cards → command center (chart + strategy cards → position matrix → blotter + risk limiters). **Acceptance**: layout matches the design wireframe grid structure.
- [x] 6.3 Create `RiskLimiterPanel` component showing active risk guards as labeled progress bars (green/yellow/red based on utilization). **Acceptance**: guards from account config render with correct values and colors; breached guards show red "BREACHED" badge.
- [x] 6.4 Create `OrderBlotterPane` component rendering live blotter events from `useBlotter` hook with slippage columns. **Acceptance**: events stream in real-time, slippage calculated and displayed per fill.

## 7. Block-Bootstrap Monte Carlo (Backend)

- [x] 7.1 Create `src/monte_carlo/block_bootstrap.py` with `BlockBootstrapMC` class implementing `fit()` and `simulate()`. Support `method="stationary"` (Politis-Romano block length) and `method="circular"`. **Acceptance**: simulate() returns `MCSimulationResult` with correct VaR/CVaR/prob_ruin; lag-1 autocorrelation preserved within 20% of input.
- [x] 7.2 Add `method="garch"` to `BlockBootstrapMC`: fit GARCH(1,1) via `arch` package, extract standardized residuals, block-resample residuals, reconstruct returns. Fallback to stationary on convergence failure. **Acceptance**: GARCH method produces paths with fatter tails than stationary; convergence failure logs warning and falls back.
- [x] 7.3 Create `POST /api/monte-carlo` endpoint accepting strategy, params, date range, cost model, and simulation config. Run baseline backtest → extract daily returns → call `BlockBootstrapMC` → return `MCSimulationResult`. **Acceptance**: endpoint returns paths + summary stats; 404 for invalid strategy; 422 for insufficient GARCH data.
- [x] 7.4 Add tests for `BlockBootstrapMC`: test deterministic seeding, test autocorrelation preservation, test VaR/CVaR calculations against known distributions, test GARCH fallback. **Acceptance**: all tests pass with `pytest`.

## 8. Backend Cost Model Integration

- [x] 8.1 Extend `POST /api/backtest/run` to accept optional `slippage_bps` and `commission_bps` parameters. Pass through to the simulator's fill model. **Acceptance**: backtest with slippage=10 produces worse metrics than slippage=0 for the same strategy/params.
- [x] 8.2 Extend `StrategyOptimizer.__init__()` to accept `slippage_bps` and `commission_bps`. Apply to every trial. Store in `OptimizerResult.cost_model`. **Acceptance**: optimizer results include cost_model; trials reflect transaction costs.
- [x] 8.3 Extend optimizer API endpoint (`POST /api/optimizer/run`) to accept and forward cost model params. **Acceptance**: sweep results from API include cost-adjusted metrics.

## 9. Cleanup & Integration Testing

- [x] 9.1 Delete standalone `frontend/src/pages/Backtest.tsx`. Verify no dead imports remain. **Acceptance**: `npm run build` succeeds with no unused import warnings.
- [x] 9.2 End-to-end test: select strategy → set params in global sidebar → run Tear Sheet → run Param Sweep (grid, 2 params) → run Stress Test (block bootstrap) → verify all use same global params. **Acceptance**: manual or automated verification that param_hash matches across all three runs.
- [x] 9.3 End-to-end test: War Room with kill switch → click HALT ALL → verify sessions paused → click RESUME → verify halt lifted. **Acceptance**: session status transitions correctly.
- [x] 9.4 End-to-end test: War Room heartbeat + blotter → verify heartbeat updates every 5s → trigger a fill → verify blotter event appears in real-time. **Acceptance**: latency displays correctly, fill event appears within 1s.
