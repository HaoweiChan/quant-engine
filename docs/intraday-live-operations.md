# Intraday Live Operations Runbook

## Scope

This runbook covers phase-1 TAIFEX deployment from `shadow` mode to `micro_live` mode with startup reconciliation, manual resume gating, and rollback to shadow mode.

## Pre-Flight Checklist

- Confirm risk config has `daily_loss_limit_pct = 0.02` and `feed_staleness_seconds = 3.0`.
- Confirm execution config has `run_mode = "shadow"` for dry run.
- Confirm gateway connectivity and credentials are valid.
- Confirm operator on-call channel is available for alerts.

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
