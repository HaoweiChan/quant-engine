# Closed-Loop Optimizer Hardening Rollout

## Scope

This runbook covers phased rollout and rollback for optimizer hardening changes:

- Phase 0: governance + promotion safety rails.
- Phase 1: real-evaluation fidelity for sequential optimizer and MCP sweeps.
- Phase 2: structural intraday seed strategy onboarding.

## Prerequisites

- `param_runs` migration is applied (new governance columns available).
- Regression suites pass for optimizer, registry, simulator, and MCP server.
- Operators can manually activate candidates via MCP/API after review.

## Phase 0 - Governance Activation

1. Deploy code with `mode` support and gate-aware activation checks.
2. Run `run_parameter_sweep` in `research` mode to verify no regressions.
3. Run `run_parameter_sweep` in `production_intent` mode on a known symbol/date range.
4. Confirm output includes:
   - `mode`, `promotable`, `gate_results`, `gate_details`, `disqualified_trials`.
   - `auto_activation_disabled = true`.
5. Verify candidate activation is blocked when `promotable=false`.

Rollback:

- Revert deployment to prior release.
- Keep existing DB rows; older code ignores unknown governance columns.

## Phase 1 - Evaluation Fidelity

1. Validate Stage-2 scoring uses split returns (not proxy Sharpe).
2. Verify robustness and final OOS consume frozen Stage-2 best params.
3. For production-intent sweeps, verify walk-forward summary appears (grid search path).
4. Confirm registry rows persist governance metadata.

Rollback:

- Switch MCP usage to `mode=research`.
- Temporarily disable production activation workflows.
- Revert deployment if scoring or sweep outputs are inconsistent.

## Phase 2 - Structural Seed Strategy

1. Confirm strategy discovery for `intraday/breakout/structural_orb`.
2. Validate schema bounds and clamp behavior through registry/MCP.
3. Run smoke sweeps in `research` mode, then `production_intent` with real data.
4. Promote only candidates that pass all production gates.

Rollback:

- Stop creating new runs for `structural_orb`.
- Keep historical runs; do not activate new candidates.
- Remove strategy alias/reference in operational tooling if needed.

## Operator Checklist

- [ ] `research` and `production_intent` paths both return expected fields.
- [ ] No implicit activation occurred.
- [ ] Activation block path tested (`promotable=false`).
- [ ] Activation success path tested (`promotable=true`).
- [ ] Sequential optimizer propagation tests green.
- [ ] Structural seed strategy tests green.
