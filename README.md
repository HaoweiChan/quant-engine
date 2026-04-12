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
| Backend package | `src/` | Core engine, API, data, runtime, risk, simulator, MCP tools |
| Frontend app | `frontend/` | React + Vite dashboard (War Room) |
| Config | `config/` | Runtime TOML configs (engine, strategies, taifex, prediction, secrets) |
| Scripts | `scripts/` | Operational scripts: daemon runner, optimizer, run-dev/prod, deploy unit files |
| Specs and change tracking | `openspec/` | Domain specs, active changes, archived changes |
| Documentation | `docs/` | Architecture, operations, deployment, and reference notes |
| Tests | `tests/` | Unit and e2e coverage |

## Key backend modules

- `src/api/` — FastAPI app, REST routes (`src/api/routes/`), WebSocket handlers (`src/api/ws/`).
- `src/core/` — types, policies, position engine, portfolio merger, sizing.
- `src/strategies/` — strategy implementations, registry (auto-discovery), scaffold helpers, parameter loader.
- `src/indicators/` — shared technical indicator library (ATR, EMA, RSI, Bollinger, MACD, …; 25+ indicators).
- `src/simulator/` and `src/monte_carlo/` — backtester, walk-forward, stress, optimizer, adversarial, block-bootstrap MC.
- `src/bar_simulator/` — intra-bar price simulation used by the backtester.
- `src/prediction/` — ML prediction engine (regime, direction, volatility, combiner).
- `src/data/` — historical crawl, data daemon, session utils, gap detection, contracts, aggregators.
- `src/broker_gateway/` and `src/trading_session/` — gateway integration, live bar store, session management.
- `src/execution/` — execution engine ABC, live/paper engines, disaster stop monitor.
- `src/oms/` — order management system and volume profiling.
- `src/reconciliation/` — broker/engine position reconciliation.
- `src/risk/` — risk monitor, portfolio risk, pre-trade checks, VaR engine.
- `src/alerting/` — alert dispatcher and formatters.
- `src/audit/` — audit trail store.
- `src/runtime/` — IPC, orchestrator, telemetry.
- `src/secrets/` — credential/secret manager.
- `src/pipeline/` — optimizer pipeline runner and config.
- `src/mcp_server/` — MCP facade, tools, validation, run history.

## Strategy layout

```text
src/strategies/
├── short_term/
│   ├── breakout/       (ta_orb, structural_orb, keltner_vwap_breakout)
│   ├── mean_reversion/ (atr_mean_reversion, bollinger_pinbar, vwap_statistical_deviation)
│   └── trend_following/ (night_session_long)
├── medium_term/
│   ├── breakout/       (ta_orb, structural_orb, keltner_vwap_breakout, volatility_squeeze)
│   ├── mean_reversion/ (bb_mean_reversion)
│   └── trend_following/ (donchian_trend_strength, ema_trend_pullback)
├── swing/
│   ├── breakout/
│   ├── mean_reversion/
│   └── trend_following/ (pyramid_wrapper, vol_managed_bnh)
├── registry.py         # auto-discovery: scans for create_*_engine + PARAM_SCHEMA + STRATEGY_META
├── scaffold.py         # strategy boilerplate generator
├── param_loader.py     # parameter loading from config/strategies/<slug>.toml
├── param_registry.py   # persisted optimization run registry
└── __init__.py         # HoldingPeriod enum, OptimizationLevel L0-L3, quality gate matrix
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
