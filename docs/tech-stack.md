# Quant Engine Tech Stack

This file summarizes the current stack used by the repository.

## Backend

- Python 3.12+
- FastAPI + Uvicorn
- WebSocket support via `websockets`
- Data stack: Polars, Pandas, NumPy, PyArrow
- ML/stat stack: LightGBM, Optuna, hmmlearn, arch, scikit-learn, SciPy
- Config and persistence helpers: SQLAlchemy, `tomli-w`
- Observability and APIs: structlog, httpx
- Secrets: Google Secret Manager client

## Frontend

- React 18
- TypeScript
- Vite
- Zustand
- TradingView Lightweight Charts

## Integration and runtime

- MCP integration via optional `mcp` dependency extra
- Broker connectivity via optional `taifex` extra (`shioaji`)
- Runtime supervision/orchestration in `src/runtime`
- Reconciliation and risk controls in `src/reconciliation` and `src/risk`

## Tooling

- Dependency and env management: `uv`
- Linting: `ruff`
- Type checking: `mypy`
- Testing: `pytest`, `pytest-asyncio`

## Packaging

- Build backend: Hatchling
- Python package root: `src/`
