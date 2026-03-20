## Context

Sprints A and B provide the Position Engine and real TAIFEX data. This sprint builds the validation and experimentation layer: backtesting on historical data, Monte Carlo simulation on synthetic paths, stress testing under extreme conditions, and parameter scanning to find robust configurations.

The key architectural constraint is that the Simulator reuses the **exact same PositionEngine class** as production — no backtest-specific logic in the engine.

## Goals / Non-Goals

**Goals:**
- BacktestRunner that feeds real historical data through the production PositionEngine
- Price path generator with configurable stochastic processes (GBM + GARCH + jumps + mean reversion)
- Monte Carlo runner with risk metrics and optional Ray parallelization
- Stress test framework with predefined extreme scenarios
- Parameter scanner with grid search and robust region detection
- All result types as structured dataclasses for downstream consumption (dashboard in Sprint E)

**Non-Goals:**
- Real-time execution or paper trading — Sprint E
- Prediction model training or walk-forward — Sprint D (though the backtester will be reused there)
- UI/visualization — Sprint E dashboard
- Sequential optimization orchestration — Sprint E (this sprint provides the primitives)

## Decisions

### Package layout

```
quant_engine/
├── core/                        # Sprint A
├── data/                        # Sprint B
├── simulator/
│   ├── __init__.py
│   ├── types.py                 # BacktestResult, MonteCarloResult, StressResult, StressScenario
│   ├── backtester.py            # BacktestRunner
│   ├── metrics.py               # Performance metric computations
│   ├── price_gen.py             # Synthetic price path generator
│   ├── monte_carlo.py           # Monte Carlo runner
│   ├── stress.py                # Stress test framework
│   └── scanner.py               # Parameter grid search
```

**Rationale:** Each simulator concern is a separate module. They share result types via `types.py`. The backtester and scanner are the primary consumer-facing classes; price_gen and stress are utilities.

### Backtester reuses PositionEngine directly

`BacktestRunner` instantiates a fresh `PositionEngine(config)` and calls `on_snapshot()` for each historical bar. Fill simulation (slippage) is handled by a lightweight `FillModel` that wraps the bar close price.

```
for bar in historical_data:
    snapshot = adapter.to_snapshot(bar)
    orders = engine.on_snapshot(snapshot, signal)
    fills = fill_model.simulate(orders, bar)
    # record fills, update equity curve
```

**Rationale:** This ensures zero divergence between backtest and production behavior. The FillModel is the only backtest-specific component.

### Price path generator: composable stochastic processes

The generator composes independent process components:
- Base: GBM (drift + diffusion)
- Volatility: GARCH(1,1) replaces constant diffusion
- Shocks: Student-t(df=5) replaces normal innovations
- Jumps: Poisson(intensity) × jump_size_distribution
- Mean reversion: OU process as additive component

Components are toggled via a `PathConfig` dataclass. Scenario presets are named `PathConfig` instances.

**Rationale:** Composability lets us isolate the effect of each process component. Presets provide convenient starting points without limiting flexibility.

### Metrics: standalone functions, not coupled to backtester

Performance metrics are pure functions in `metrics.py` that take equity curves and trade logs as input. They are usable by both the backtester and Monte Carlo runner.

**Rationale:** Reuse across backtest, Monte Carlo, and future modules.

### Parameter scanner: embarrassingly parallel grid search

Each parameter combination runs an independent backtest. Results are collected into a polars DataFrame. Optional Ray integration for N > threshold.

**Rationale:** Grid search is simple and interpretable. Bayesian optimization (Optuna) is deferred to Sprint D where it's used for model hyperparameters.

## Risks / Trade-offs

- **[Risk] Backtesting is slow on large historical datasets** → Mitigation: Profile early. The PositionEngine processes one bar at a time, so the bottleneck is likely feature computation (cached in Sprint B). Parameter scanner parallelizes via Ray.
- **[Risk] Price path generator may not produce realistic paths** → Mitigation: Validate generated path statistics (mean, vol, kurtosis, autocorrelation) against real TAIFEX data from Sprint B.
- **[Risk] Look-ahead bias in backtest** → Mitigation: BacktestRunner processes bars strictly in order. Features and signals are computed only from data available at each bar's timestamp.
