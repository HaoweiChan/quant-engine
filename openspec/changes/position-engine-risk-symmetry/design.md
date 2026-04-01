## Context

The teardown in `docs/archive/engine-tear-down-risk-and-symmetry.md` identifies three production blockers in the current TAIFEX position pipeline:
- Entry policy effectively behaves long-only, suppressing short-side opportunity and directional symmetry.
- Entry sizing relies on static loss assumptions, which can over-risk the account as equity changes.
- Position engine can emit entry orders before validating available margin, causing avoidable broker rejections.

This is a cross-cutting change spanning policy interfaces, position engine gating, shared type/config contracts, and alerting behavior. The target scope is one-week implementation with a migration-safe feature flag for compatibility.

Current logical flow:

```
MarketSnapshot + MarketSignal
        |
        v
EntryPolicy.should_enter(snapshot, signal, engine_state)
        |
        v
PositionEngine emits Order
        |
        v
ExecutionEngine submits to broker
```

Target flow:

```
MarketSnapshot + MarketSignal + AccountState
        |
        v
EntryPolicy.should_enter(..., account)
  - symmetric long/short mapping
  - equity-risk sizing (2% default)
  - static max-loss as secondary cap
        |
        v
PositionEngine pre-trade margin gate
  - block on insufficient margin
  - emit explicit risk/alert event
        |
        v
Order emission (or suppression with auditable reason)
```

## Goals / Non-Goals

**Goals:**
- Enforce symmetric long/short entry behavior for all strategies by default.
- Add equity-aware entry sizing at default 2% risk per trade, with static max-loss retained as secondary cap.
- Add explicit pre-trade margin gate before entry orders are emitted.
- Emit explicit risk/alert events when margin gate blocks entries.
- Preserve migration safety via long-only compatibility feature flag.

**Non-Goals:**
- Redesigning prediction models or signal generation.
- Changing execution-router microstructure logic.
- Multi-broker behavior tuning beyond required type/contract compatibility.
- Removing existing static hard-loss safeguards.

## Decisions

### D1: Make policy interface account-aware

Decision:
- Extend `EntryPolicy.should_enter(...)` to accept `account: AccountState | None`.
- Entry policies must refuse blind production sizing when account context is missing.

Why:
- Sizing without current equity/margin is mathematically unsafe in live trading.
- This keeps sizing logic policy-owned while preserving engine-policy separation.

Alternatives considered:
- Keep account-unaware policy and size in PositionEngine: rejected due policy cohesion loss and duplicated sizing logic.

### D2: Dual-layer risk sizing model

Decision:
- Primary sizing uses `max_equity_risk_pct` (default 2%) against current equity.
- Secondary hard cap keeps static `max_loss` behavior as safety backstop.

Why:
- Equity-relative risk keeps risk-of-ruin behavior stable through drawdowns.
- Static cap remains useful as catastrophic guardrail.

Alternatives considered:
- Replace static cap entirely: rejected per user requirement to keep hard safety layer.

### D3: Enforce pre-trade margin gate before order emission

Decision:
- PositionEngine computes required entry margin from decision lots and `snapshot.margin_per_unit`.
- If `account.margin_available` is insufficient, suppress entry order and emit structured rejection event.

Why:
- Prevents known broker-side rejections and unnecessary execution churn.
- Keeps failures observable and auditable.

Alternatives considered:
- Allow broker rejection and recover downstream: rejected as operationally expensive and noisy.

### D4: Add compatibility feature flag for long-only transition

Decision:
- Introduce policy flag (e.g., `long_only_compat_mode`) defaulting to `False`.
- When enabled, short entries are intentionally suppressed for controlled migration.

Why:
- Provides rollback-safe transition for strategies that assume legacy behavior.

Alternatives considered:
- No feature flag: rejected due migration risk for incumbent strategy behavior.

### D5: Alerting contract for margin gate rejections

Decision:
- Margin gate blocks must emit explicit risk/alert notifications with reason, required margin, available margin, and strategy/symbol context.

Why:
- Operators need immediate visibility into blocked entries and capital constraints.

Alternatives considered:
- Log-only rejections: rejected per requirement for explicit alert events.

## Risks / Trade-offs

- [Behavioral drift in existing strategies] -> Strategies tuned for long-only assumptions may produce unexpected trade frequency. Mitigation: gated compatibility flag and rollout checklist.
- [Over-conservative sizing in volatile sessions] -> Equity-risk sizing can reduce participation during high ATR periods. Mitigation: keep parameters configurable per strategy.
- [Alert volume increase] -> Margin gate events can create noisy alerts in capital-constrained accounts. Mitigation: structured dedup windows and severity levels.
- [Interface churn] -> Policy signature changes can break custom strategy policies. Mitigation: staged migration and clear type-level compile/test failures.

## Migration Plan

1. Add new config and type fields for equity-risk sizing and compatibility flag.
2. Update policy interfaces and concrete policies (`PyramidEntryPolicy`) to use account-aware sizing.
3. Add PositionEngine pre-trade margin gate and explicit rejection event emission.
4. Extend alerting formatter/dispatcher paths for margin rejection events.
5. Roll out with compatibility flag support and strategy-by-strategy validation.
6. Run regression tests for long-only compat mode and symmetric mode.

Rollback strategy:
- Set compatibility flag to long-only mode.
- Keep static hard-loss safeguards active.
- Disable symmetric behavior without reverting unrelated risk/engine changes.

## Open Questions

- Should margin-gate rejection alerts be throttled per symbol to avoid repetitive bursts?
- Should account-missing behavior in live mode hard-fail, or remain soft-block with alert only?
