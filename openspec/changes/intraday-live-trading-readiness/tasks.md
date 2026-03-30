## 1. Runtime topology and IPC contracts

- [x] 1.1 Add runtime orchestrator entrypoint that starts Market Data, Strategy, and Execution processes under one supervisor. Acceptance: orchestrator starts/stops all three processes cleanly from a single command.
- [x] 1.2 Implement typed IPC payloads (`QuoteEvent`, `SignalIntent`, `ExecutionCommand`) with version field and monotonic sequence handling. Acceptance: serialization/deserialization round-trip tests pass and stale sequence events are rejected.
- [x] 1.3 Add queue backpressure guards for quote and execution channels. Acceptance: saturation test triggers guard behavior and emits structured alerts without process crash.

## 2. Execution engine adaptive routing

- [x] 2.1 Add volatility regime classifier inputs for execution policy selection (`calm`, `normal`, `high`). Acceptance: policy selection unit test maps expected regime inputs to expected policy outputs.
- [x] 2.2 Implement cancel-replace state machine with configurable wait budgets and `max_retries`. Acceptance: integration test verifies bounded chase loop and terminal state handling.
- [x] 2.3 Implement partial-fill-aware replacement sizing that preserves parent-child order linkage. Acceptance: simulated partial fill test confirms only remaining quantity is replaced.
- [x] 2.4 Extend live execution result schema with slippage bps and quality benchmark fields. Acceptance: `get_fill_stats()` returns `pct_over_2bps` and existing metrics remain backward compatible.

## 3. Risk monitor hard rails

- [x] 3.1 Add `daily_loss_limit_pct` config with default `0.02` and wire to Risk Monitor checks. Acceptance: breach simulation triggers `CLOSE_ALL` and mode transition to `halted`.
- [x] 3.2 Tighten feed staleness threshold to seconds-level (`<=3s`) for active TAIFEX sessions. Acceptance: stale feed simulation over 3 seconds blocks new entries and emits critical alert.
- [x] 3.3 Implement stale-feed protective behavior for open positions (allow protective exits, block new entries). Acceptance: scenario test confirms exits remain possible while entries are rejected.

## 4. Startup reconciliation and controlled resume

- [x] 4.1 Add startup freeze mode that blocks strategy order emission until reconciliation completes. Acceptance: startup integration test confirms no order intent emitted before freeze release.
- [x] 4.2 Extend reconciliation startup flow to compare positions, open orders, and recent fills against local state. Acceptance: mismatch fixtures produce expected unsafe-state flags.
- [x] 4.3 Implement startup open-order cleanup for unmapped working orders. Acceptance: broker mock verifies cancellation requests are sent before resume is allowed.
- [x] 4.4 Add manual operator confirmation gate for resume after successful reconciliation. Acceptance: runtime stays paused until explicit confirm action is received and logged.

## 5. Broker gateway continuity support

- [x] 5.1 Extend broker gateway snapshot types to include `open_orders` and `continuity_cursor`. Acceptance: snapshot contract tests verify populated fields for connected state.
- [x] 5.2 Add `get_order_events_since(cursor)` continuity API to Sinopac gateway implementation. Acceptance: mocked event stream returns deterministic ordering and cursor advancement.
- [x] 5.3 Add fail-safe behavior when continuity data is unavailable. Acceptance: startup reconciliation marks state unsafe and blocks resume in gateway failure test.

## 6. Observability and SLO enforcement

- [x] 6.1 Add stage timestamps for quote-ingest, signal-emit, order-dispatch, and broker-ack. Acceptance: telemetry output includes all stage timestamps for each tracked order.
- [x] 6.2 Implement rolling P99 tick-to-order metric and threshold alerting at 200 ms. Acceptance: synthetic latency load test triggers breach alert above threshold.
- [x] 6.3 Add execution quality monitor against 2 bps benchmark. Acceptance: degraded fill-quality scenario triggers warning and status flag update.

## 7. Rollout controls and operations

- [x] 7.1 Add explicit run modes (`shadow`, `micro_live`) with mode-appropriate order submission behavior. Acceptance: `shadow` mode produces zero broker orders while full signal and latency telemetry are produced.
- [x] 7.2 Add micro-size limits for TAIFEX phase-1 trading (TMF-scale exposure caps). Acceptance: order above configured limits is rejected with rollout-limit reason.
- [x] 7.3 Create operator runbook for startup reconcile, manual resume, halt conditions, and rollback-to-shadow procedure. Acceptance: runbook includes executable command sequence and incident response checklist.

## 8. Tests and final verification

- [x] 8.1 Add unit tests for IPC sequencing/idempotency and queue guard behavior. Acceptance: duplicate and stale sequence test cases pass.
- [x] 8.2 Add execution integration tests for adaptive routing, cancel-replace bounds, timeout, and partial fills. Acceptance: all execution state machine paths reach deterministic terminal outcomes.
- [x] 8.3 Add risk monitor tests for 2% daily loss liquidation and 3-second feed staleness handling. Acceptance: both scenarios produce expected actions and alerts.
- [x] 8.4 Add startup reconciliation tests for orphan/ghost positions, open-order cleanup, and manual resume gate. Acceptance: unsafe states block resume and safe states require explicit confirmation.
- [x] 8.5 Run end-to-end shadow dry run and micro-size readiness checklist. Acceptance: P99 tick-to-order <= 200 ms and fill-quality metrics are captured before enabling micro-live capital.
