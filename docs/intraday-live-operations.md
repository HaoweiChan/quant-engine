# Intraday Live Operations Runbook

## Scope

This runbook covers phase-1 TAIFEX deployment from `shadow` mode to `micro_live` mode with startup reconciliation, manual resume gating, and rollback to shadow mode.

## Pre-Flight Checklist

- Confirm risk config has `daily_loss_limit_pct = 0.02` and `feed_staleness_seconds = 3.0`.
- Confirm execution config has `run_mode = "shadow"` for dry run.
- Confirm gateway connectivity and credentials are valid.
- Confirm operator on-call channel is available for alerts.

## Execution Baseline (Phase A)

This rollout assumes the realistic execution stack is active:

- Fill model: `MarketImpactFillModel` (replaces naive close/open fill assumptions).
- OMS slicing available: TWAP, VWAP, POV for larger parent orders.
- Pre-trade risk gate enabled for gross exposure and ADV participation controls.

Expected impact versus naive historical assumptions:

- Backtest PnL typically degrades by ~10-30% after market impact, spread, and latency are modeled.
- This is expected and preferred because it reduces simulation-to-live drift.

Verify these metrics are present in backtest outputs before enabling micro-live:

- `total_market_impact`
- `total_spread_cost`
- `avg_latency_ms`
- `partial_fill_count`
- `impact_report`

## Startup Procedure

1. Start isolated runtime supervisor:
   - `python -m src.runtime.orchestrator`
2. Run startup reconciliation gate:
   - invoke reconciler startup workflow (`run_startup_reconciliation()` in runtime boot path)
3. Verify startup status:
   - no unresolved critical mismatches (`ghost`, `orphan`, `quantity`)
   - no continuity failures (`list_recent_fills` and open-order continuity available)
4. Cancel lingering open orders:
   - confirm startup cleanup reports cancellation count
5. Manual resume confirmation:
   - `confirm_resume("<operator_id>")`
   - verify audit record exists with operator and snapshot id

## Shadow Mode Dry Run

1. Set execution mode to `shadow`.
2. Run dry session with live data feed and strategy signal emission enabled.
3. Confirm acceptance gates:
   - `tick_to_order_p99_ms <= 200`
   - telemetry includes quote-ingest, signal-emit, order-dispatch, broker-ack timestamps
   - risk monitor triggers halt on stale feed > 3 seconds
4. Confirm no live broker submissions:
   - place-order count must remain zero in shadow mode

## Micro-Live Enablement

1. Set execution mode to `micro_live`.
2. Enable rollout caps:
   - `max_contracts_per_order` at TMF-scale
   - `max_total_contracts` conservative phase-1 cap
3. Run controlled session with operator present.
4. Confirm live acceptance gates:
   - `tick_to_order_p99_ms <= 200`
   - `pct_over_2bps` monitored and quality state not persistently degraded
   - no unresolved reconciliation mismatches

## Incident Response

- **Daily loss limit breach (2% AUM):**
  - expect force liquidation and engine halt
  - keep halted until manual operator review
- **Feed stale (>3s):**
  - new entries halted
  - open entry orders canceled
  - manual confirmation required after feed recovery window
- **Critical reconcile mismatch:**
  - block resume
  - resolve broker vs local state before re-attempt

## Rollback to Shadow Mode

1. Set execution mode back to `shadow`.
2. Keep runtime running for telemetry and signal validation.
3. Disable new live submissions until issue is resolved.
4. Record incident details and resume decision in operations log.

## Orphan Order Recovery (Persistent Order State)

Live order state is now persisted via `src/oms/order_state_store.py` to
`data/trading.db` (`orders` table). Every state transition (`pending →
ack → partial → filled | rejected | cancelled`) is committed before
the next executor action. This means a Python crash mid-order leaves a
deterministic trail the reconciler can match against the broker.

### On startup

The startup reconciler (existing) now extends its scan to:

1. Read non-terminal rows: `OrderStateStore.list_open()`.
2. Cross-reference with broker continuity feed:
   `gateway.get_order_events_since(continuity_cursor)`.
3. For each non-terminal local row:
   - **Broker reports it as filled** → record fill, transition to
     `filled`, surface to operator audit.
   - **Broker reports it as cancelled / rejected** → record terminal
     state, no further action.
   - **Broker reports it as still working** → cancel via
     `gateway.cancel_order()`, mark local as `cancelled` with reason
     `startup_orphan_cancel`, surface to operator.
   - **Broker has no record** → mark local as `rejected` with reason
     `broker_unknown`, surface to operator.
4. Block manual resume gate until every non-terminal row resolves.

### Operator workflow when orphans are detected

1. The startup banner lists orphan order_ids and their last known
   status. Do NOT confirm resume yet.
2. Inspect each row in `trading.db.orders` to confirm symbol/side/lots
   match the operator's expectations.
3. If any row's resolution looks unsafe (broker says filled but local
   says pending and the strategy didn't intend to enter), open the
   incident channel before confirming resume.
4. Use `confirm_resume("<operator_id>")` once every orphan is in a
   terminal state and the operator accepts the outcome.

### Observability

- Logs: `order_state_pending`, `order_state_transition`,
  `order_state_fill` per transition; `order_state_write_failed` if the
  DB write itself errors (executor continues, but flag the row).
- Periodic operator check: `sqlite3 data/trading.db "SELECT order_id,
  symbol, side, status, updated_at FROM orders WHERE status NOT IN
  ('filled','rejected','cancelled') ORDER BY created_at"` should
  return no rows during quiet windows.
