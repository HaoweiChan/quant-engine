## 1. Config Loading (`quant_engine/pipeline/config.py`)

- [x] 1.1 Create `config/engine.toml` with PyramidConfig defaults, risk thresholds (margin_ratio_threshold, signal_staleness_window, feed_staleness_window, spread_spike_multiplier, max_loss), check_interval — acceptance: all values parseable by tomllib
- [x] 1.2 Create `config/prediction.toml` with model hyperparameters, freshness windows, horizon — acceptance: all values parseable
- [x] 1.3 Implement typed TOML config loader: load and validate engine.toml → PyramidConfig + risk thresholds — acceptance: ValueError on invalid config, correct dataclass construction
- [x] 1.4 Implement prediction config loader: load prediction.toml → model params dict — acceptance: dict contains all expected keys
- [x] 1.5 Implement layered config: load top-level config that references sub-configs — acceptance: single entry point loads all configs

## 2. Structured Logging (`quant_engine/pipeline/`)

- [x] 2.1 Set up structlog configuration: JSON output, timestamp, log level, module context — acceptance: structured log entries emitted from any module
- [x] 2.2 Add structlog integration to RiskMonitor, ExecutionEngine, and PipelineRunner — acceptance: all risk events, fills, and pipeline steps emit structured logs

## 3. Risk Monitor (`quant_engine/risk/monitor.py`)

- [x] 3.1 Implement `RiskMonitor.__init__` with configurable thresholds loaded from config — acceptance: all thresholds configurable, defaults from TOML
- [x] 3.2 Implement `check(account: AccountState) -> RiskAction`: evaluate drawdown, margin, staleness, anomalies — acceptance: returns correct RiskAction for each condition
- [x] 3.3 Implement drawdown circuit breaker: return CLOSE_ALL when drawdown >= max_loss / capital — acceptance: triggers at exact threshold
- [x] 3.4 Implement margin ratio monitoring: return REDUCE_HALF when margin_ratio < threshold — acceptance: triggers at configured threshold
- [x] 3.5 Implement signal staleness detection: degrade to rule_only when signal older than freshness window — acceptance: mode change triggered on stale signal
- [x] 3.6 Implement price feed staleness detection: return HALT_NEW_ENTRIES when feed older than threshold during trading hours — acceptance: triggers only during trading hours
- [x] 3.7 Implement spread spike anomaly detection: return HALT_NEW_ENTRIES when spread exceeds multiplier — acceptance: triggers at configured spike multiplier
- [x] 3.8 Implement `set_position_engine_mode()` and `force_close_all()` interface methods — acceptance: mode changes immediately, force close generates close-all orders
- [x] 3.9 Implement async check loop: periodic check at configurable interval as asyncio task — acceptance: loop runs at configured interval, stops cleanly on cancellation
- [x] 3.10 Implement alert dispatch via structlog: log all non-NORMAL risk actions with full context — acceptance: structured log includes account state, action, trigger reason
- [x] 3.11 Verify module isolation: RiskMonitor has no imports from position_engine, prediction, or execution — acceptance: static import check passes

## 4. Execution Engine (`quant_engine/execution/`)

- [x] 4.1 Implement `ExecutionResult` dataclass: order_ref, status, fill_price, expected_price, slippage, fill_qty, remaining_qty, rejection_reason — acceptance: all fields present
- [x] 4.2 Implement `ExecutionEngine` ABC with `execute(orders) -> list[ExecutionResult]` and `get_fill_stats() -> dict` — acceptance: ABC enforces method implementation
- [x] 4.3 Implement `PaperExecutor`: simulate fills at current price ± configurable slippage — acceptance: fills generated with correct adverse slippage
- [x] 4.4 Implement slippage tracking in PaperExecutor: record expected vs fill price per order — acceptance: slippage correctly computed as fill - expected
- [x] 4.5 Implement `get_fill_stats()`: aggregate slippage statistics (mean, median, P95, max) — acceptance: stats computed from fill history
- [x] 4.6 Implement order validation: margin check before submission — acceptance: insufficient margin rejected locally
- [x] 4.7 Implement execution logging via structlog: log submit, fill, reject events — acceptance: structured logs for all execution events

## 5. Pipeline Runner (`quant_engine/pipeline/runner.py`)

- [x] 5.1 Implement `PipelineRunner.__init__` accepting all module instances (adapter, prediction_engine, position_engine, executor, risk_monitor) — acceptance: all modules wired together
- [x] 5.2 Implement `run_step(bar)`: single-bar pipeline step: data → prediction → position → execution — acceptance: one bar processed end-to-end
- [x] 5.3 Implement `run_historical(bars)`: iterate historical bars through pipeline for backtesting — acceptance: processes all bars sequentially, collects results
- [x] 5.4 Implement risk monitor integration: call risk_monitor.check() each step, apply RiskAction — acceptance: risk actions applied (mode changes, close-all, reduce)
- [x] 5.5 Implement equity curve and trade log tracking across pipeline run — acceptance: equity curve and trade log available after run
- [x] 5.6 Implement pipeline state snapshot: expose current positions, equity, signal, mode for dashboard — acceptance: snapshot dict contains all required fields

## 6. Sequential Optimizer (`quant_engine/pipeline/optimizer.py`)

- [x] 6.1 Implement Stage 1: train prediction models, evaluate on model_val split — acceptance: trained models + validation metrics returned
- [x] 6.2 Implement Stage 2: freeze signals via predict_batch, sweep position params via parameter scanner — acceptance: results DataFrame with one row per param combination
- [x] 6.3 Implement robustness test: degrade model accuracy, verify Sharpe holds — acceptance: degraded run completes, Sharpe compared to baseline
- [x] 6.4 Implement final OOS evaluation: one-shot run on held-out 10% data — acceptance: OOS metrics computed without data leakage
- [x] 6.5 Implement full optimization orchestration: Stage 1 → Stage 2 → robustness → OOS in sequence — acceptance: end-to-end optimization completes, best config returned

## 7. Dashboard (`quant_engine/dashboard/app.py`)

- [x] 7.1 Implement Streamlit app skeleton with page navigation: Live/Paper, Backtest, Monte Carlo, Risk — acceptance: 4 pages navigable
- [x] 7.2 Implement Live/Paper page: equity curve chart, current positions table, signal display, engine mode — acceptance: all components render with mock data
- [x] 7.3 Implement Backtest page: run backtest form, equity curve, trade log table, metrics summary — acceptance: backtest results displayable
- [x] 7.4 Implement Monte Carlo page: run simulation form, PnL distribution chart, percentiles table — acceptance: Monte Carlo results displayable
- [x] 7.5 Implement Risk page: margin ratio gauge, drawdown chart, alert history table, mode display — acceptance: risk status displayable

## 8. Tests

- [x] 8.1 Risk Monitor tests: verify each RiskAction trigger condition, verify staleness detection, verify module isolation — acceptance: all risk rules covered
- [x] 8.2 Execution Engine tests: verify paper fills with slippage, verify fill stats, verify order validation — acceptance: paper executor behavior verified
- [x] 8.3 Pipeline Runner tests: verify end-to-end single-step, verify risk integration, verify equity tracking — acceptance: pipeline step produces correct output
- [x] 8.4 Config loading tests: verify TOML parsing, verify validation errors on bad config — acceptance: valid/invalid config paths tested
- [x] 8.5 Optimizer tests: verify Stage 1 + Stage 2 sequence on synthetic data — acceptance: optimization completes with result

## 9. Quality Gates

- [x] 9.1 `ruff check` passes with zero errors
- [x] 9.2 `mypy --strict` passes with zero errors
- [x] 9.3 All pytest tests pass
