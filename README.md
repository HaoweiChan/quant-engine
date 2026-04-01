# Quant Engine

Quant Engine is a market-oriented trading platform with:

- A FastAPI backend for simulation, optimization, and runtime APIs.
- A React dashboard for backtest, strategy, and trading workflows.
- An MCP server for agent-driven strategy iteration.

## Current status

- Backend API, simulator, optimizer, and MCP server are implemented.
- Frontend dashboard is implemented under `frontend/`.
- Strategy system is organized by timeframe and category under `src/strategies/`.
- Runtime hardening and live operations controls are in progress (see runbooks).

## Repository layout

| Area | Path | Purpose |
|---|---|---|
| Backend package | `src/` | Core engine, API, runtime, risk, simulator, MCP tools |
| Frontend app | `frontend/` | React + Vite dashboard |
| Config | `config/` | Runtime TOML configs |
| Specs and change tracking | `openspec/` | Domain specs, active changes, archived changes |
| Documentation | `docs/` | Architecture, operations, deployment, and reference notes |
| Tests | `tests/` | Unit and e2e coverage |

## Key backend modules

- `src/api/` - FastAPI app, routes, API helpers, websocket endpoints.
- `src/core/` - core types, policies, position engine.
- `src/simulator/` and `src/monte_carlo/` - backtesting and simulation workflows.
- `src/risk/` and `src/reconciliation/` - risk controls and broker/state reconciliation.
- `src/broker_gateway/` and `src/trading_session/` - gateway integration and session management.
- `src/mcp_server/` - MCP facade, tools, validation, history.
- `src/strategies/` - strategy implementations, registry, scaffold helpers.

## Strategy layout

```text
src/strategies/
├── daily/
│   ├── breakout/
│   └── trend_following/
├── intraday/
│   ├── breakout/
│   ├── mean_reversion/
│   └── trend_following/
└── registry.py
```

## Quick start

### 1) Install Python dependencies

```bash
uv sync
```

Optional extras:

```bash
uv sync --extra mcp
uv sync --extra taifex
```

### 2) Install frontend dependencies

```bash
npm --prefix frontend install
```

### 3) Run backend and frontend

```bash
# Backend
uv run uvicorn src.api.main:app --reload

# Frontend (new terminal)
npm --prefix frontend run dev
```

- Backend: `http://localhost:8000`
- Frontend: `http://localhost:5173`

## MCP server

Run the MCP server directly:

```bash
uv run --extra mcp python -m src.mcp_server.server
```

## Testing and quality

```bash
uv run pytest
uv run pytest -m "not integration"
uv run ruff check src tests
uv run mypy src
```

Frontend tests:

```bash
npm --prefix frontend run test:run
```

## Deployment

Private always-on deployment (systemd + Caddy + Tailscale):

```bash
bash scripts/setup-tailscale-dashboard.sh --tailscale-host <your-magicdns-host>
```

Detailed guide: `docs/tailscale-setup.md`

## Documentation

- Docs index: `docs/docs-map.md`
- Architecture: `docs/architecture.md`
- Project structure: `docs/structure.md`
- Tech stack: `docs/tech-stack.md`
- Strategy notes: `docs/strategies.md`
- Live operations: `docs/intraday-live-operations.md`
