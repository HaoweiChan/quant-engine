## 1. Async Pipeline Migration

- [x] 1.1 Convert `ExecutionEngine.execute()` to `async def execute()` in `src/execution/engine.py`
- [x] 1.2 Convert `PaperExecutor.execute()` to `async def` (trivial wrapper, same logic) in `src/execution/paper.py`
- [x] 1.3 Convert `PipelineRunner.run_step()` and `run_historical()` to async in `src/pipeline/runner.py`
- [x] 1.4 Update all tests that call `execute()` or `run_step()` to use `pytest-asyncio` and `await`
- [x] 1.5 Add `pytest-asyncio` to dev dependencies in `pyproject.toml`
- [x] 1.6 Verify `ruff check` and `pytest` pass after async migration

## 2. Live Executor

- [x] 2.1 Create `src/execution/live.py` with `LiveExecutor(ExecutionEngine)` skeleton — constructor accepts shioaji `api` instance and `asyncio.AbstractEventLoop`
- [x] 2.2 Implement `_on_order_event()` and `_on_deal_event()` callbacks that resolve `asyncio.Future` via `loop.call_soon_threadsafe()`
- [x] 2.3 Register callbacks via `api.set_order_callback()` in LiveExecutor constructor
- [x] 2.4 Implement `async execute()` — for each Order: validate, translate to shioaji contract+order, call `place_order()`, await Future with timeout
- [x] 2.5 Implement order timeout handling — cancel via `api.cancel_order()` on timeout, return ExecutionResult with status "cancelled"
- [x] 2.6 Implement stop order translation — emit IOC limit at stop price when order.order_type == "stop"
- [x] 2.7 Implement retry logic with exponential backoff for transient shioaji errors (network timeout, connection reset)
- [x] 2.8 Add simulation mode support — accept `simulation=True` flag to use `sj.Shioaji(simulation=True)`
- [x] 2.9 Write tests for LiveExecutor with mocked shioaji API (mock `place_order`, simulate callbacks)

## 3. Gradual Rollout Controls

- [x] 3.1 Add `RolloutConfig` dataclass to `src/pipeline/config.py` with `max_contracts_per_order`, `max_total_contracts`, `enabled`
- [x] 3.2 Add `[rollout]` section to `config/engine.toml`
- [x] 3.3 Implement rollout validation in LiveExecutor — reject orders exceeding limits before placement
- [x] 3.4 Write tests for rollout limit enforcement (over-limit rejection, disabled bypass)

## 4. Structlog Migration

- [x] 4.1 Replace `logging.getLogger(__name__)` with `structlog.get_logger(__name__)` in all `src/` modules
- [x] 4.2 Add structured context bindings to key log calls (order_id, symbol, trade_id, etc.)
- [x] 4.3 Verify `ruff check` passes after migration

## 5. Alerting (Telegram)

- [x] 5.1 Create `src/alerting/__init__.py` and `src/alerting/dispatcher.py` with `NotificationDispatcher` class
- [x] 5.2 Implement async `dispatch(message)` using `httpx.AsyncClient` POST to Telegram Bot API
- [x] 5.3 Implement failure handling — log errors, never raise on send failure
- [x] 5.4 Add `TELEGRAM_BOT_TOKEN` to `config/secrets.toml` mapping and load via SecretManager
- [x] 5.5 Add `[alerting]` section to `config/engine.toml` with `telegram_chat_id` and `daily_summary_time`
- [x] 5.6 Create `src/alerting/formatters.py` — format functions for entry, exit, add-position, risk alert, and daily summary messages
- [x] 5.7 Wire trade notifications into PipelineRunner — dispatch on each ExecutionResult with status "filled"
- [x] 5.8 Wire risk alert notifications into RiskMonitor — dispatch on any non-NORMAL RiskAction
- [x] 5.9 Implement daily P&L summary — async scheduled task triggered at configured time
- [x] 5.10 Add `httpx` to dependencies in `pyproject.toml`
- [x] 5.11 Write tests for dispatcher (mocked httpx), formatters (snapshot output), and wiring

## 6. Position Reconciliation

- [x] 6.1 Create `src/reconciliation/__init__.py` and `src/reconciliation/reconciler.py` with `PositionReconciler` class
- [x] 6.2 Implement `async start_loop(interval=60)` — periodic asyncio task calling `api.list_positions()` and `api.margin()`
- [x] 6.3 Implement position comparison logic — match by symbol+direction, detect quantity mismatch, ghost, and orphan positions
- [x] 6.4 Implement account state comparison — compare equity and margin_ratio against broker values
- [x] 6.5 Implement mismatch response policy — alert-only (default) and halt-on-mismatch modes via config
- [x] 6.6 Wire reconciler into PipelineRunner — start alongside Risk Monitor's async loop
- [x] 6.7 Add `[reconciliation]` section to `config/engine.toml` with `interval_seconds`, `equity_threshold_pct`, `policy`
- [x] 6.8 Write tests for reconciler with mocked shioaji position/margin responses

## 7. Live Fill Comparison

- [x] 7.1 Add `backtest_expected_price` optional field to `ExecutionResult` in `src/execution/engine.py`
- [x] 7.2 Implement deviation tracking in LiveExecutor — record live vs expected fill price per order
- [x] 7.3 Extend `get_fill_stats()` to include deviation metrics (mean, P95, 2x-slippage count)
- [x] 7.4 Write tests for fill comparison tracking

## 8. Integration & Verification

- [x] 8.1 End-to-end test: async PipelineRunner with PaperExecutor, RiskMonitor, Reconciler, and Alerting all running together
- [x] 8.2 End-to-end test: LiveExecutor in simulation mode against shioaji simulation environment
- [x] 8.3 Run `ruff check src/ tests/` — no errors
- [x] 8.4 Run `pytest tests/` — all tests pass
