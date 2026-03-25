## 1. Core Event Types

- [ ] 1.1 Add `EventType` enum and event dataclasses (`Event`, `MarketEvent`, `SignalEvent`, `OrderEvent`, `FillEvent`, `RiskEvent`) to `src/core/types.py`. Acceptance: all types importable, mypy clean.
- [ ] 1.2 Add `AuditRecord`, `AuditConfig`, `EventEngineConfig` dataclasses to `src/core/types.py`. Acceptance: instantiable with defaults, validation on construction.

## 2. Event Engine

- [ ] 2.1 Create `src/simulator/event_engine.py` with `EventEngine` class — `deque`-based queue, `register_handler()`, `push()`, `run()`. Acceptance: events dispatched to correct handlers, queue drains completely per bar.
- [ ] 2.2 Implement event priority ordering for same-timestamp events: RISK > FILL > MARKET > SIGNAL > ORDER > AUDIT. Acceptance: verified in tests.
- [ ] 2.3 Implement handler chaining — handler returns `list[Event]` → pushed to queue. Acceptance: MarketEvent → cascade through signal → order → fill.
- [ ] 2.4 Implement `run_backtest()` — converts bars to MarketEvents, registers default handler chain, collects results into `BacktestResult`. Acceptance: produces valid BacktestResult.
- [ ] 2.5 Implement intra-bar tick drill-down — when `(high - low) > tick_drill_atr_mult × daily_atr`, generate synthetic ticks via `price_sequence.py`. Acceptance: volatile bars produce multiple sub-events.
- [ ] 2.6 Add `EventEngineConfig` support from TOML — `tick_drill_atr_mult`, `tick_drill_enabled`, `latency_delay_ms`, `audit_enabled`. Acceptance: config toggleable.
- [ ] 2.7 Write tests: handler dispatch, event chaining, priority ordering, queue draining, tick drill-down, normal bar passthrough, disabled drill-down. Acceptance: all tests green.

## 3. BacktestRunner Refactor

- [ ] 3.1 Refactor `BacktestRunner.run()` to delegate to `EventEngine.run_backtest()` internally. Acceptance: existing method signature and return type unchanged.
- [ ] 3.2 Register handler chain: MarketEvent → PositionEngine → OrderEvent → OMS → FillModel → FillEvent. Acceptance: full chain produces fills from market data.
- [ ] 3.3 Backtest equivalence test — compare EventEngine output vs. old bar-loop output for identical inputs (using same fill model). Acceptance: identical equity curves and trade logs.
- [ ] 3.4 Write tests: API preservation, result format, precomputed signals as SignalEvents. Acceptance: all existing backtest tests pass without modification.

## 4. Audit Trail

- [ ] 4.1 Create `src/audit/__init__.py` and `src/audit/trail.py` with `AuditTrail` class — `append()`, `verify_chain()`, `get_state_at()`, `replay()`. Acceptance: hash chain verifiable.
- [ ] 4.2 Create `src/audit/store.py` with `SQLiteAuditStore` using separate `audit.db` file. Acceptance: INSERT succeeds, UPDATE/DELETE rejected.
- [ ] 4.3 Implement SHA-256 hash chain — `record_hash = SHA256(sequence_id || timestamp || ... || prev_hash)`. Genesis: `prev_hash = "0"*64`. Acceptance: chain verification passes for valid chain.
- [ ] 4.4 Implement tamper detection — `verify_chain()` returns False when any record modified. Acceptance: single bit flip detected.
- [ ] 4.5 Wire audit record creation into EventEngine handlers for `order_generated`, `fill_executed`, `risk_action`, `mode_change`. Acceptance: records created for all specified events.
- [ ] 4.6 Add git commit hash tracking via `subprocess.run(["git", "rev-parse", "HEAD"])`. Acceptance: populated in repo, None otherwise.
- [ ] 4.7 Implement deterministic replay — load audit chain + PIT data, replay through EventEngine, verify state match. Acceptance: 100% match for valid chain.
- [ ] 4.8 Write tests: hash chain integrity, tamper detection, append-only enforcement, sequence continuity, git commit, replay determinism. Acceptance: all tests green.

## 5. Integration

- [ ] 5.1 End-to-end test: bars → EventEngine → OMS → fill model → audit trail → verify chain integrity. Acceptance: single test exercises full Phase D stack.
- [ ] 5.2 Performance benchmark: compare EventEngine backtest time vs. old bar-loop. Acceptance: <10% overhead documented.
