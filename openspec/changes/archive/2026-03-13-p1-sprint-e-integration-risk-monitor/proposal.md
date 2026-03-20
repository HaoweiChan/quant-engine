## Why

Sprints A–D deliver the core engine, data pipeline, backtester, and prediction models as independent modules. Without wiring them together, paper-trading against live data, and adding the Risk Monitor safety net, the platform cannot operate in a real environment. Sprint E is the integration sprint that makes the platform end-to-end usable — including a monitoring dashboard to visualize everything.

## What Changes

- Implement Risk Monitor: independent watchdog with circuit breaker, margin monitoring, signal/feed staleness detection, anomaly detection, and alert dispatch
- Implement Execution Engine (paper mode): simulate fills against live prices with slippage tracking
- Wire all modules end-to-end: Data Layer → Prediction Engine → Position Engine → Execution (paper)
- Implement monitoring dashboard (Streamlit): equity curve, positions, signals, backtest/Monte Carlo results, risk status
- Implement sequential optimization pipeline: Stage 1 (prediction), Stage 2 (position params), robustness test, final OOS
- Implement TOML config loading for all module configuration
- Implement structured logging across the entire pipeline

## Capabilities

### New Capabilities

_(none — all capabilities already have specs)_

### Modified Capabilities

- `risk-monitor`: Implement from existing spec — circuit breaker, margin monitoring, staleness detection, anomaly detection, alert system
- `execution-engine`: Implement paper trading mode from existing spec — paper executor, slippage tracking, order validation

## Impact

- **New packages**: `quant_engine.risk.monitor`, `quant_engine.execution.engine`, `quant_engine.execution.paper`, `quant_engine.dashboard`, `quant_engine.pipeline`
- **Dependencies**: streamlit, structlog, tomli (TOML loading)
- **Consumes**: All Sprint A–D modules
- **Outcome**: Platform is fully operational for paper trading, backtesting, and monitoring — Phase 1 MVP complete
