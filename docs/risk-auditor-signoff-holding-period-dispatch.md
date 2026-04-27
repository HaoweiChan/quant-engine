# Risk Auditor sign-off — holding_period dispatch for session-flat & benchmark

**Date**: 2026-04-26
**Subject**: AGENTS.md (=CLAUDE.md) invariant #7 rewording + `_compute_force_flat_indices` slug guard
**Reviewer agent**: oh-my-claudecode:critic acting as Risk Auditor
**Verdict**: APPROVED WITH FOLLOW-UPS

## What changed

1. **AGENTS.md / CLAUDE.md** — invariant #7 reworded to classify by `holding_period` /
   `stop_architecture`, not bar timeframe. The "Intraday Position and Benchmark Rules"
   section was renamed to "Position and Benchmark Rules" with an explicit dispatch table
   (SHORT_TERM → intraday B&H; MEDIUM_TERM/SWING → daily-bar B&H).

2. **`src/mcp_server/facade.py`** — `_compute_force_flat_indices(timestamps, slug=None)`
   gained an optional `slug` parameter. When provided AND `is_intraday_strategy(slug)`
   returns False, the function short-circuits to `{len(timestamps)-1}` (single
   end-of-window flat). All 5 call sites updated to pass `slug=resolved_slug`.

## Risks reviewed

| # | Risk | Verdict | Note |
|---|---|---|---|
| 1 | Live trading parity | **RAISE** | Live runner / pipeline still force-flat unconditionally |
| 2 | Existing strategy impact (vol_managed_bnh) | CLEAR | Was already excluded from force-flat via stop_architecture; no behavior change |
| 3 | Benchmark choice for SWING-on-5m | CLEAR | Daily B&H matches the holding universe (gap-inclusive) |
| 4 | Documentation completeness | CLEAR | Author can choose SHORT_TERM vs SWING with full understanding of consequences |
| 5 | `slug=None` safety | CLEAR | Default falls through to legacy session-boundary logic — over-flatten = safe direction |

## Required follow-ups before deployment of any SWING-on-5m strategy

- **[BLOCKING]** Patch `src/execution/live_strategy_runner.py:391-401` and
  `src/execution/live_pipeline.py:572-624` to gate force-flat on
  `is_intraday_strategy(strategy_slug)`. Without this, live SWING-on-5m strategies
  will be force-flattened at session boundaries, creating backtest-live divergence
  that invalidates all backtested metrics.
- **[RECOMMENDED]** Commit unit tests for the three branches of
  `_compute_force_flat_indices`: SWING returns final-bar-only, INTRADAY returns
  session boundaries, no-slug preserves legacy behavior. (Run ad-hoc during this
  change but not yet in the repo.)
- **[LOW]** Audit the `medium_term/` prefix fallback in
  `src/strategies/registry.py:207` — all current `medium_term/` strategies declare
  `stop_architecture = SWING`, making the fallback dead code. Decide whether
  `medium_term + INTRADAY` is a valid future combination; if not, remove the
  fallback to prevent confusion.

## Verification evidence

- Unit test (datetime timestamps, in-process):
  - SWING (compounding_trend_long): `[5]`
  - INTRADAY (night_session_long): `[1, 3, 5]`
  - Legacy no-slug: `[1, 3, 5]`
- End-to-end MCP backtest of `night_session_long` on TMF 2025-06-11..2025-09-30:
  `trade_count=79, sharpe=1.97` — unchanged from prior runs.

## Approval scope

This sign-off authorizes the **doc and facade changes only**. It does NOT authorize:
- Live deployment of any SWING-on-5m strategy (gated on the BLOCKING follow-up)
- Removal of the `medium_term/` prefix fallback in registry.py (gated on the LOW follow-up audit)
