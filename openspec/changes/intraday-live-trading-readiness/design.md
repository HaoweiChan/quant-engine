## Context

The current quant-engine architecture is strong for research and simulation, but intraday live trading readiness requires stricter guarantees on latency, execution behavior, and fault recovery. The critical path currently risks interference from API and UI workloads because multiple concerns run in the same runtime context. The target deployment for this change is a single host, with readiness to scale out later.

This change addresses four production blockers identified in the technical critique:
- Event-loop coupling that can delay quote-to-order handling under CPU pressure.
- Missing adaptive cancel-replace mechanics for intraday fill quality.
- Incomplete startup recovery for uncertain order/fill continuity.
- Risk tolerances (especially feed staleness) that are too loose for TAIFEX intraday trading.

Stakeholders:
- Trader/operator (Willy): requires predictable execution quality and bounded downside.
- Strategy runtime: must preserve alpha under a P99 tick-to-order SLO of 200 ms.
- Risk/operations: must enforce hard stop conditions and controlled restart behavior.

Proposed runtime shape:

```
Shioaji quote stream
        |
        v
+----------------------+      IPC (pub/sub, local)      +----------------------+
| Market Data Process  | -----------------------------> | Strategy Process     |
| (normalization + ts) |                                | (signal generation)  |
+----------------------+                                +----------+-----------+
                                                                   |
                                                                   | IPC (command queue)
                                                                   v
                                                        +----------------------+
                                                        | Execution Process    |
                                                        | (router + broker IO) |
                                                        +----------+-----------+
                                                                   |
                                                                   v
                                                         Sinopac / TAIFEX API

Independent watcher: Risk Monitor process (reads broker/account + feed health, can halt/close)
```

## Goals / Non-Goals

**Goals:**
- Enforce a single-host, multi-process critical path for quotes -> signals -> orders.
- Meet P99 tick-to-order dispatch budget of 200 ms in live runtime.
- Enforce fill-quality monitoring against a 2 bps slippage benchmark.
- Implement adaptive-by-volatility execution with cancel-replace and partial-fill handling.
- Enforce hard daily loss cap at 2% AUM with liquidate-and-halt behavior.
- Enforce feed staleness trip in seconds (intraday-safe) with immediate protective actions.
- Require startup reconciliation and manual confirmation before resuming live order flow.
- Deliver a rollout path from shadow mode to micro-size live trading within one week.

**Non-Goals:**
- Multi-host distributed deployment in this phase.
- New broker integrations beyond TAIFEX via Sinopac.
- Strategy alpha model redesign.
- Full autonomous restart without operator confirmation.

## Decisions

### D1: Runtime isolation via single-host multi-process + local IPC

Decision:
- Split critical path into three processes: market data, strategy, and execution.
- Use local IPC channels for quote events and order intents.
- Keep FastAPI/dashboard concerns outside the execution-critical process path.

Why:
- Process separation prevents prediction or API/UI workloads from blocking execution timing.
- Local IPC supports the one-week timeline and single-host constraint.

Alternatives considered:
- Keep single process with asyncio task prioritization: rejected due residual GIL contention risk.
- Introduce Redis as mandatory runtime bus: rejected for this phase due extra operational overhead.

### D2: Adaptive-by-volatility execution router with bounded chase behavior

Decision:
- Implement a state machine that selects initial order aggressiveness by short-horizon volatility regime.
- Start less aggressive in calm conditions and more aggressive in high-volatility conditions.
- Apply bounded cancel-replace loops with per-order chase limits and explicit timeout handling.

Why:
- Intraday slippage is path-dependent; static market-only or limit-only policies are structurally weak.
- Bounded chase logic reduces both missed fills and uncontrolled adverse price drift.

Alternatives considered:
- Market-only: rejected for expected slippage drag.
- Limit-only with fixed waits: rejected for high miss risk during fast markets.

### D3: Hard risk rails for intraday deployment

Decision:
- Daily loss cap fixed at 2% AUM. Breach triggers forced liquidation and trade halt.
- Feed staleness threshold reduced to seconds-level (<= 3 s during active session).
- Staleness breach triggers immediate halt of new entries and cancellation of open orders.

Why:
- Intraday derivatives require rapid fail-safe behavior; minute-level staleness is unacceptable.
- Hard stop policies must be deterministic and machine-enforced.

Alternatives considered:
- Alert-only on feed staleness: rejected as insufficient protection.
- Softer staged loss reduction before halt: deferred to future phase.

### D4: Controlled resume with mandatory reconciliation and operator gate

Decision:
- On startup/reconnect, runtime enters a frozen state before strategy evaluation.
- Reconciliation sequence: query open positions + open orders + recent fills, cancel stale open orders, align local state, then request manual operator confirmation.
- Only after manual confirmation does the strategy process unfreeze and emit new order intents.

Why:
- Eliminates ambiguous state after process crash or disconnect windows.
- Aligns local and broker truth before taking new risk.

Alternatives considered:
- Auto-resume after reconcile: rejected for initial live phase due operational risk.

### D5: One-week phased go-live path with hard acceptance gates

Decision:
- Phase A (shadow mode): live data, no real orders, full latency and signal observability.
- Phase B (micro-size live): TMF-scale sizing only, capped exposure and strict kill switch.
- Promotion to larger size is explicitly out of this change.

Why:
- Matches timeline and reduces first-live execution risk.

Alternatives considered:
- Immediate full-size live: rejected as unacceptable risk for current readiness level.

## Risks / Trade-offs

- [IPC complexity] -> Multiple processes increase orchestration and debugging complexity. Mitigation: strict message contracts, monotonic event IDs, and replayable logs.
- [Cancel-replace churn] -> Aggressive chasing can increase cancel rates and fee/friction. Mitigation: per-order chase cap and volatility-aware throttles.
- [Manual gate operational load] -> Human confirmation can delay recovery. Mitigation: concise recovery checklist and one-command confirmation flow.
- [Single-host failure domain] -> One host remains a SPOF. Mitigation: this phase focuses on state correctness and fast recoverability; multi-host is a future phase.
- [SLO observability drift] -> Latency targets may appear green without end-to-end measurement points. Mitigation: timestamp instrumentation at quote-ingest, signal-emit, order-send, and broker-ack milestones.

## Migration Plan

1. Add runtime orchestrator entrypoint for three-process topology behind a feature flag.
2. Implement IPC schemas and adapters, then wire strategy/execution process contracts.
3. Integrate adaptive execution state machine and bounded cancel-replace behavior.
4. Tighten RiskMonitor thresholds and hard-stop actions.
5. Implement controlled startup reconcile + manual resume flow.
6. Run shadow mode acceptance tests for latency, reconciliation, and risk trips.
7. Enable micro-size live mode and run controlled dry sessions.

Rollback strategy:
- Keep legacy single-process execution path behind a toggle.
- If any acceptance gate fails in shadow or micro-live, revert to shadow-only mode and disable live order submission.

## Open Questions

- Should the manual confirmation gate support only CLI approval in phase 1, or also FastAPI/admin UI approval?
- What exact volatility regime thresholds should be used for adaptive routing defaults on TAIFEX TMF?
