## Why

Phase 1 delivered a working backtest + paper trading system. Phase 2 takes it live: real order execution via shioaji, position reconciliation against the broker, Telegram alerting, and gradual rollout controls. This is the gate between "validates on paper" and "trades real money."

## What Changes

- **Async pipeline**: `ExecutionEngine.execute()` becomes async; `PipelineRunner` becomes fully async to support live order flow with callback-based fill confirmations
- **Live executor**: New `LiveExecutor` that places real TAIFEX futures orders via shioaji's `place_order()` API, bridging C++ thread callbacks to asyncio
- **Position reconciliation**: Periodic (60s) comparison of engine state vs broker state via `api.list_positions()` and `api.margin()`, with alert on mismatch
- **Telegram alerting**: Trade notifications, risk alerts, and daily P&L summaries via Telegram Bot API
- **Gradual rollout**: Config-driven max position size limits to scale from 1 contract to planned allocation
- **Live fill comparison**: Track and compare live fill slippage against backtest expectations
- **Structlog migration**: Replace remaining `logging.getLogger()` calls with structlog across all modules

## Capabilities

### New Capabilities
- `alerting`: Telegram notifications for trade events, risk alerts, and daily P&L summaries
- `reconciliation`: Periodic engine-vs-broker position and account state reconciliation

### Modified Capabilities
- `execution-engine`: Async interface, live executor via shioaji, gradual rollout controls, live fill comparison

## Impact

- **src/execution/engine.py**: `ExecutionEngine` ABC becomes async; `execute()` → `async def execute()`
- **src/execution/paper.py**: `PaperExecutor.execute()` wrapped as async (trivial)
- **src/execution/live.py**: New file — `LiveExecutor` with shioaji integration
- **src/pipeline/runner.py**: `PipelineRunner.run_step()` and `run_historical()` become async
- **src/alerting/**: New module — `NotificationDispatcher` + formatters
- **src/reconciliation/**: New module — `PositionReconciler` + `AccountReconciler`
- **All modules**: Migrate `logging.getLogger()` → `structlog.get_logger()`
- **config/engine.toml**: New sections for `[rollout]`, `[alerting]`, `[reconciliation]`
- **config/secrets.toml**: New entry for `telegram.bot_token`
- **Dependencies**: `httpx` (async Telegram API), `shioaji` (already present)
