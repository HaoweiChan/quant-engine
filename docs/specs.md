# Quant Engine Specs Guide

The source of truth for implementation requirements is `openspec/specs/`.

This file maps major domains to where their authoritative specs live.

## Spec source of truth

| Domain | Spec location |
|---|---|
| API backend | `openspec/specs/fastapi-backend` |
| React frontend | `openspec/specs/react-frontend` |
| Strategy system | `openspec/specs/strategies` |
| Strategy optimizer | `openspec/specs/strategy-optimizer` |
| MCP server | `openspec/specs/backtest-mcp-server` |
| Position engine | `openspec/specs/position-engine` |
| Risk monitor and kill switch | `openspec/specs/risk-monitor`, `openspec/specs/kill-switch` |
| Broker gateway | `openspec/specs/broker-gateway` |
| Reconciliation | `openspec/specs/reconciliation` |
| Trading session | `openspec/specs/trading-session` |

## How to use specs

1. Read the relevant domain spec under `openspec/specs/`.
2. Read active change artifacts under `openspec/changes/` for pending or in-flight work.
3. Use docs in `docs/` for operational context, not for requirement authority.

## Related docs

- `docs/architecture.md`
- `docs/structure.md`
- `docs/docs-map.md`
