# Quant Engine

A market-agnostic quantitative trading engine with a React dashboard, FastAPI backend, and MCP server for AI-driven strategy optimization.

---

## Architecture

Three principles govern every design decision:

1. **Market-agnostic core** — Position Engine, Risk Monitor, and Simulator know nothing about which market they trade. Market-specific logic lives exclusively in Adapters.
2. **One-way dependency** — Prediction Engine outputs signals to Position Engine, never the reverse. Risk Monitor reads account state independently and can override everything.
3. **Graceful degradation** — Every module has a fallback. If prediction fails, the engine continues in rule-only mode. If execution fails, the risk monitor can force-close via direct broker API.

```
Data Layer → Prediction Engine → Position Engine → Execution Engine → Market Adapters
                                        ↑
                              Risk Monitor (independent)
                                        ↑
                    FastAPI Backend ←→ React Dashboard
                                        ↑
                              MCP Server (AI agents)
```

## Modules

| Module | Path | Description |
|---|---|---|
| Core Types | `src/core/` | `PyramidConfig`, `EngineConfig`, policy ABCs, `PositionEngine` |
| Strategies | `src/strategies/` | User-editable policy implementations and engine configs |
| Bar Simulator | `src/bar_simulator/` | Bar-level OHLCV price simulation for backtesting |
| Simulator | `src/simulator/` | Full backtest loop — feeds bar data through the engine |
| Prediction | `src/prediction/` | Direction model, regime classifier, volatility forecaster |
| Execution | `src/execution/` | Order routing, slippage control, broker adapter interface |
| Market Adapters | `src/adapters/` | Sinopac (TAIFEX), US equity, crypto connectors |
| Data Layer | `src/data/` | OHLCV storage, feature store, normalization pipeline |
| Risk Monitor | `src/risk/` | Circuit breaker, margin monitor, anomaly detection |
| FastAPI Backend | `src/api/` | REST API, WebSocket feeds, param registry endpoints |
| MCP Server | `src/mcp_server/` | AI agent integration via stdio MCP protocol |
| Secrets | `src/secrets/` | Credential management via Google Secret Manager |
| Broker Gateway | `src/broker_gateway/` | Unified broker interface layer |
| Trading Session | `src/trading_session/` | Live and paper trading session management |
| Reconciliation | `src/reconciliation/` | Position and trade reconciliation |
| Alerting | `src/alerting/` | Notification and alerting pipeline |

## Dashboard

The dashboard is a React + Vite frontend backed by a FastAPI server.

```bash
# Start the FastAPI backend
uv run uvicorn src.api.main:app --reload
# http://localhost:8000

# Start the React frontend (separate terminal)
cd frontend && npm install && npm run dev
# http://localhost:5173
```

Five lifecycle-ordered tabs:

- **Data Hub** — Browse historical OHLCV data with TradingView charts and client-side indicators (MA, EMA, ATR, Bollinger Bands)
- **Strategy** — Sub-tabs: Code Editor (in-browser strategy file editing with 3-level validation), Optimizer, Grid Search, Monte Carlo
- **Backtest** — Run backtests with configurable position engine parameters; loads active params from the registry automatically
- **Trading** — Sub-tabs: Accounts, War Room, Blotter, Risk — live and paper trading monitor via WebSocket

## MCP Server (AI Agent Integration)

The backtest engine is exposed as an MCP server for AI-driven strategy optimization. Compatible with Claude Code and Cursor.

```bash
# Run standalone (for testing)
uv run --extra mcp python -m src.mcp_server.server
```

MCP config lives in `.claude/mcp.json` (symlinked from `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "backtest-engine": {
      "command": "uv",
      "args": ["run", "--extra", "mcp", "python", "-m", "src.mcp_server.server"]
    }
  }
}
```

Available tools: `run_backtest`, `run_monte_carlo`, `run_parameter_sweep`, `run_stress_test`, `get_parameter_schema`, `read_strategy_file`, `write_strategy_file`, `get_optimization_history`.

## Strategy Development

Edit strategy files from the dashboard (Strategy → Code Editor) or directly in `src/strategies/`:

```
src/strategies/
├── example_entry.py      # Extend EntryPolicy — controls when to open positions
├── example_add.py        # Extend AddPolicy — controls pyramiding logic
├── example_stop.py       # Extend StopPolicy — controls stop-loss and trailing
└── configs/
    └── default.toml      # Engine parameters (max_loss, ATR multipliers, etc.)
```

Core files (`src/core/`, `src/bar_simulator/`) are read-only from the dashboard.

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/). Requires Node.js 18+ for the frontend.

```bash
# Install Python dependencies
uv sync

# Install with MCP server support
uv sync --extra mcp

# Install with broker connectivity (Sinopac/TAIFEX)
uv sync --extra taifex

# Install frontend dependencies
cd frontend && npm install

# Run tests
uv run pytest

# Lint
uv run ruff check src/
```

## Testing

```bash
# All tests
uv run pytest

# Skip integration tests (require live broker)
uv run pytest -m "not integration"

# Type checking
uv run mypy src/
```

## Tech Stack

- **Python 3.12** with strict type checking (`mypy --strict`)
- **FastAPI + uvicorn** for the backend API and WebSocket feeds
- **React 18 + Vite + TypeScript** for the browser dashboard
- **shadcn/ui + Tailwind CSS** for UI components
- **TradingView Lightweight Charts** for all financial charts
- **Zustand** for frontend state management
- **Polars** for data manipulation, **PyArrow** for columnar storage
- **LightGBM** for direction model, **Optuna** for hyperparameter search
- **mcp** (stdio) for AI agent integration
- **Ruff** for linting, **pytest** for testing
- **uv** for dependency management
