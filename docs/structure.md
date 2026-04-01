# Quant Engine Project Structure

This file reflects the current repository layout.

## Top-level layout

```text
quant-engine/
├── config/        # Runtime config files (TOML)
├── docs/          # Documentation and runbooks
├── frontend/      # React + Vite dashboard
├── openspec/      # Spec system (specs, changes, archive)
├── scripts/       # Operational and utility scripts
├── src/           # Backend Python package
├── tests/         # Unit and integration/e2e tests
├── pyproject.toml # Python project config
└── README.md      # Project overview and quickstart
```

## Backend module layout (`src/`)

```text
src/
├── adapters/         # Market adapter interfaces and helpers
├── alerting/         # Alert pipelines and notifiers
├── api/              # FastAPI routes, app bootstrap, API helpers
├── audit/            # Audit trail and replay integrity
├── bar_simulator/    # Bar-level simulation primitives
├── broker_gateway/   # Broker connectivity and gateway implementations
├── core/             # Core types, policies, position engine
├── data/             # Data models, storage, connectors, PIT/stitching helpers
├── execution/        # Execution engine and live/paper execution flows
├── mcp_server/       # MCP tools and history facade
├── monte_carlo/      # Monte Carlo simulators and analysis helpers
├── oms/              # Order management and scheduling logic
├── pipeline/         # Orchestration and optimization pipelines
├── prediction/       # Feature processing and prediction models
├── reconciliation/   # Broker/local state reconciliation
├── risk/             # Risk monitor, pre-trade checks, VaR/stress logic
├── runtime/          # Runtime orchestrator and supervisor logic
├── secrets/          # Secret loading/management
├── simulator/        # Backtester, fill models, stress/sweep engines
├── strategies/       # Strategy registry, scaffold, strategy implementations
└── trading_session/  # Trading session lifecycle management
```

## Strategy layout (`src/strategies/`)

```text
src/strategies/
├── daily/
│   ├── breakout/
│   └── trend_following/
├── intraday/
│   ├── breakout/
│   ├── mean_reversion/
│   └── trend_following/
├── registry.py
├── scaffold.py
├── _session_utils.py
└── _shared_indicators.py
```

## Documentation conventions

- File names in `docs/` use lowercase kebab-case.
- `docs/docs-map.md` is the entry point for documentation categories.
- Detailed implementation specs live in `openspec/specs/`.
