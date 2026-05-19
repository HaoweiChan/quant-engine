---
Status: DEFERRED at end of 2026-05-08 forensic session.
File written but not committed. Hook blocked direct push to main;
decision was to bundle with deploy.sh uv-fix session where the
mode-aware guard implementation lives.
---

# TODO — Mode-aware session guard

## Background

Current `scripts/deploy.sh` and orchestrator STOP triggers hardcode TAIFEX session hours (08:45–13:45 / 15:00–05:00) for restart blocking. The guard exists to protect broker-side state during live trading. During paper/shadow/development phases this guard is over-protective: it blocks legitimate dev work without protecting any real broker state.

## Proposed change

Make session guard mode-aware via `TRADE_MODE` env var in `.env`:

| TRADE_MODE | Session guard | Restart allowed |
|---|---|---|
| `paper` | none | any time |
| `shadow` | none | any time |
| `micro-live` | strict | only 13:45–15:00 / 05:00–08:45 TPE; require open-position count == 0 |
| `production` | strict + alert | as micro-live + dual-confirm |

## Implementation

- `scripts/deploy.sh`: read `TRADE_MODE` from `.env`, branch session-guard logic accordingly
- `.claude/agents/orchestrator.md`: add STOP trigger T7 — any broker-facing operation must verify TRADE_MODE before applying guard logic; quote current value to user

## Constraints

- Must NOT be implemented in same session as SEGV mitigation (separate change, separate review)
- Must be implemented in same session as deploy.sh uv-fix (currently P1) — the deploy.sh rewrite is the natural place to introduce the mode dispatch
- Default `TRADE_MODE=paper` until first `micro-live` deployment is approved
