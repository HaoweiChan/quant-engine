## Why

The current architecture is strong for research and backtesting, but it is not yet safe for intraday live execution under strict latency and slippage targets. This change is needed now to deliver a one-week go-live path from shadow mode to micro-size TAIFEX live trading while preserving execution quality and risk discipline.

## What Changes

- Introduce an isolated live runtime path on a single host, separating market data ingestion, strategy evaluation, and order execution into independent processes connected by local IPC.
- Add adaptive-by-volatility execution behavior with explicit cancel-replace logic, partial-fill handling, and slippage guardrails aligned to a 2 bps benchmark.
- Tighten real-time risk controls with intraday-safe feed staleness enforcement (seconds-level), a hard daily loss cap at 2% AUM, and automatic liquidate-and-halt behavior.
- Require controlled startup recovery and manual confirmation before resuming live order flow after disconnects, restarts, or failover events.
- Define phased readiness gates and acceptance criteria for shadow trading and micro-size live deployment within a one-week implementation window.

## Capabilities

### New Capabilities
- `live-runtime-isolation`: Define process isolation and IPC contracts for the critical path (quotes -> signals -> orders) on a single host.

### Modified Capabilities
- `execution-engine`: Add adaptive volatility-aware routing, cancel-replace state machine behavior, and execution quality constraints.
- `risk-monitor`: Tighten feed staleness controls and enforce daily loss liquidation-and-halt requirements for intraday trading.
- `reconciliation`: Require startup freeze, broker-state reconciliation, and operator-confirmed controlled resume.
- `broker-gateway`: Require deterministic handling for order and fill event continuity needed by controlled resume and reconciliation.

## Impact

- Affected systems: live market data ingestion, strategy runtime loop, execution engine, risk monitor, reconciliation startup flow, and broker gateway integration.
- Affected code areas: `src/quant_engine/execution/`, `src/quant_engine/risk/`, `src/quant_engine/gateway/`, runtime orchestration entrypoints, and related configuration schemas.
- Operational impact: new runtime topology, updated deployment/runbook steps, and additional observability/alerting checks for latency, slippage, and feed health.
