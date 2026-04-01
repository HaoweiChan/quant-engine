# Quant Engine Roadmap

This roadmap is intentionally high-level. Active implementation details and task checklists live in `openspec/changes/`.

## Current phase snapshot

| Phase | Status | Focus |
|---|---|---|
| Foundation platform | In progress | Stable backtesting, optimization, dashboard, and MCP workflows |
| Intraday production hardening | In progress | Runtime supervision, reconciliation, risk gates, execution realism |
| Live operations rollout | In progress | Shadow mode and micro-live rollout via runbooks |
| Multi-market expansion | Planned | Broader adapter support (crypto/equities) with shared risk controls |

## Near-term priorities

1. Tighten production-intent optimizer governance and promotion safety.
2. Keep strategy registry and parameter workflows deterministic and auditable.
3. Harden runtime operations: stale-feed handling, startup reconciliation, manual resume controls.
4. Keep frontend and backend contract parity for charting, backtest, and trading views.
5. Improve docs hygiene so repository state matches implementation state.

## Tracking references

- Specs: `openspec/specs/`
- Active work: `openspec/changes/`
- Operations: `docs/intraday-live-operations.md`
- Optimizer rollout: `docs/closed-loop-optimizer-rollout.md`
