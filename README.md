# Quant Engine

A market-agnostic quantitative trading engine with a built-in browser dashboard for strategy development, backtesting, and live/paper trading.

---

## Architecture

Three principles govern every design decision:

1. **Market-agnostic core** — Position Engine, Risk Monitor, and Simulator know nothing about which market they trade. Market-specific logic lives exclusively in Adapters.
2. **One-way dependency** — Prediction Engine outputs signals to Position Engine, never the reverse. Risk Monitor reads account state independently and can override everything.
3. **Graceful degradation** — Every module has a fallback. If prediction fails, the engine continues in rule-only mode. If execution fails, risk monitor can force-close via direct broker API.

```
Data Layer → Prediction Engine → Position Engine → Execution Engine → Market Adapters
                                        ↑
                              Risk Monitor (independent)
                                        ↑
                               Dashboard (monitoring)
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
| Dashboard | `src/dashboard/` | Dash 4 browser dashboard (5 tabs, dark theme) |

## Dashboard

Run the dashboard locally:

```bash
uv run python -m src.dashboard.app
# Opens at http://localhost:8050
```

Five lifecycle-ordered tabs:

- **Data Hub** — Browse and export historical OHLCV data
- **Strategy** — In-browser code editor for `src/strategies/` files with 3-level validation (syntax → lint → engine)
- **Backtest** — Run backtests with configurable position engine parameters
- **Optimization** — Grid search and Monte Carlo analysis across parameter ranges
- **Trading** — Live and paper trading monitor

## Strategy Development

Edit strategy files directly from the dashboard (Strategy tab) or in your IDE. The `src/strategies/` directory is the user-facing sandbox:

```
src/strategies/
├── example_entry.py      # Extend EntryPolicy — controls when to open positions
├── example_add.py        # Extend AddPolicy — controls pyramiding logic
├── example_stop.py       # Extend StopPolicy — controls stop-loss and trailing
└── configs/
    └── default.toml      # Engine parameters (max_loss, ATR multipliers, etc.)
```

Core system files (`src/core/`, `src/bar_simulator/`) are intentionally read-only from the dashboard.

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
# Install all dependencies
uv sync

# Install with dashboard UI
uv sync --extra dashboard

# Install with broker connectivity (Sinopac/TAIFEX)
uv sync --extra taifex

# Run tests
uv run pytest

# Lint
uv run ruff check src/
```

## Testing

```bash
# All tests
uv run pytest

# Editor I/O and validation only
uv run pytest tests/test_editor_io.py -v

# Skip integration tests (require live broker)
uv run pytest -m "not integration"
```

## Tech Stack

- **Python 3.12** with strict type checking (`mypy --strict`)
- **Polars** for data manipulation, **PyArrow** for columnar storage
- **LightGBM** for direction model, **Optuna** for hyperparameter search
- **Dash 4** for the browser dashboard, **Ace Editor** (`dash-ace`) for code editing
- **Ruff** for linting, **pytest** for testing
- **uv** for dependency management
