## Why

The current frontend is structurally broken for production quantitative trading. Two independent code reviews (`docs/risk-and-execution-overhaul.md`, `docs/research-suite-integration.md`) identified the same core failures: parameters are invisible across research tabs (curve-fitting hazard), the War Room lacks emergency controls and real-time exposure monitoring, the Backtest page is isolated from the Strategy research pipeline, and simulation methods use naive i.i.d. bootstrap instead of block-bootstrap or GARCH-aware sampling. Deploying capital through this interface means flying blind.

## What Changes

- **Unify the research pipeline**: Merge the standalone Backtest page into Strategy as a "Tear Sheet" sub-tab. Combine Optimizer + Grid Search into a single "Param Sweep" tab. Rename Monte Carlo to "Stress Test".
- **Global parameter context**: Add a persistent left-pane parameter panel on the Strategy page holding the full parameter vector θ, symbol, date range, and cost assumptions (slippage bps, commission bps). All sub-tabs inherit from this single source of truth.
- **Run provenance**: Every execution (backtest, sweep, stress test) logs an immutable record of the exact parameter dict, data range, cost assumptions, and code commit hash.
- **War Room emergency controls**: Add a global kill switch (HALT_ALL_TRADING + FLATTEN_ALL_POSITIONS), an API heartbeat/latency monitor, and a real-time slippage tracker comparing expected vs actual fill prices.
- **Execution exposure matrix**: Add a real-time position matrix with asset, direction, size, entry price, current price, unrealized PnL, and net beta exposure. Add an order blotter streaming submissions, fills, and rejections.
- **Risk engine panel**: Add active risk limiter display (max daily loss current vs limit), drawdown guardrails, and automated halt triggers when slippage exceeds backtested assumptions.
- **Fix Monte Carlo methodology**: Replace naive i.i.d. bootstrap with block-bootstrap (and optionally GARCH-filtered residual bootstrap). Add VaR and Expected Shortfall outputs.
- **Remove hardcoded state**: Eliminate all hardcoded `symbol: "TX"`, `start`, `end` values from view-layer components; bind everything to the global parameter context.

## Capabilities

### New Capabilities
- `global-param-context`: Zustand-based global parameter state (θ vector, symbol, date range, cost assumptions) shared across all Strategy sub-tabs, with run provenance logging.
- `kill-switch`: Emergency halt-all-trading and flatten-all-positions control, bypassing standard queues, with broker API integration.
- `execution-monitor`: Real-time API heartbeat/latency monitor and slippage tracker (expected vs actual fill price) with alerting thresholds.
- `block-bootstrap-mc`: Block-bootstrap and GARCH-filtered Monte Carlo simulation replacing the naive i.i.d. sampler, with VaR/CVaR output.

### Modified Capabilities
- `react-frontend`: Tab structure changes — remove standalone Backtest tab, restructure Strategy sub-tabs to (Code Editor → Tear Sheet → Param Sweep → Stress Test), add global parameter sidebar to Strategy page.
- `war-room-dashboard`: Add kill switch bar, position/exposure matrix, order blotter stream, risk limiter display, and heartbeat monitor to the War Room layout.
- `strategy-optimizer`: Unify Grid Search and Optimizer into a single "Param Sweep" tab; locked parameters inherit from global context rather than having independent local state.

## Impact

- **Frontend**: Major restructuring of `Strategy.tsx` (new sidebar + tab layout), deletion of standalone `Backtest.tsx` page, refactor of `MonteCarlo.tsx`, `GridSearch.tsx`, `Optimizer.tsx` into new components. New Zustand store for global param context.
- **Backend API**: New endpoints for kill-switch actions (`POST /api/kill-switch`), heartbeat/latency polling, slippage tracking feed. Modified backtest endpoint to accept and log cost assumptions + provenance hash.
- **WebSocket**: New WS channel for real-time order blotter events and heartbeat telemetry.
- **Python engine**: New `BlockBootstrapMC` simulator class alongside existing Monte Carlo. Backend slippage/commission injection into backtest pipeline.
- **Dependencies**: `arch` package (already present) for GARCH model; no new external deps expected.
