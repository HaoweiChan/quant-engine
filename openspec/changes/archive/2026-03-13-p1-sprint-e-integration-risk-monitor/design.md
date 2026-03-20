## Context

Sprints A-D deliver all core modules independently. Sprint E wires them into a working system: data flows from Sinopac through the prediction pipeline into the Position Engine, orders go to a paper executor, and the Risk Monitor watches everything. A Streamlit dashboard provides real-time visibility.

This sprint also implements the sequential optimization pipeline that finds the best parameter configuration across the full stack.

## Goals / Non-Goals

**Goals:**
- Risk Monitor running as an independent component with all safety rules
- Paper trading execution engine with slippage simulation
- End-to-end pipeline: Data -> Prediction -> Position -> Execution (paper)
- Monitoring dashboard with real-time visibility into all modules
- Sequential optimization pipeline (Stage 1 prediction + Stage 2 position params)
- TOML-based configuration for all modules
- Structured logging (structlog) across the entire system

**Non-Goals:**
- Live order execution to broker (Phase 2)
- Telegram/notification integration (Phase 2 -- Risk Monitor logs alerts, dispatch is pluggable)
- Multi-market support (Phases 3-5)
- Production deployment, systemd services, Docker (Phase 2)

## Decisions

### Package layout

```
quant_engine/
  core/                   # Sprint A
  data/                   # Sprint B
  simulator/              # Sprint C
  prediction/             # Sprint D
  risk/
    __init__.py
    monitor.py            # RiskMonitor
  execution/
    __init__.py
    engine.py             # ExecutionEngine base + routing
    paper.py              # PaperExecutor
  dashboard/
    __init__.py
    app.py                # Streamlit dashboard
  pipeline/
    __init__.py
    runner.py             # End-to-end pipeline orchestrator
    optimizer.py          # Sequential optimization
    config.py             # TOML config loading
  config/
    taifex.toml           # From Sprint B
    engine.toml           # PyramidConfig, risk thresholds
    prediction.toml       # Model hyperparameters, freshness windows
```

### Risk Monitor: component, not process (Phase 1)

In Phase 1, Risk Monitor runs as a separate async task within the same process, checking account state on a configurable schedule. In Phase 2, it will be extracted into a truly independent process with direct broker API access.

**Rationale:** Running as a separate process requires IPC (Redis/ZMQ) which adds infrastructure complexity. For paper trading in Phase 1, an async task within the same process is sufficient and simpler to develop/debug.

### Paper Executor: implements ExecutionEngine interface

`PaperExecutor` implements the same `ExecutionEngine` interface as the future live executor. Orders are "filled" at the current market price with configurable slippage. All fills are logged identically to how live fills would be.

**Rationale:** The pipeline code is identical for paper and live -- only the executor implementation changes. This ensures paper trading is a faithful simulation.

### Dashboard: Streamlit with polling

The Streamlit dashboard reads state from the pipeline (via shared state or file-based snapshots). It polls on a configurable interval. Pages:
1. **Live / Paper** -- equity curve, positions, current signal, engine mode
2. **Backtest** -- run backtests, view results, equity curves, trade logs
3. **Monte Carlo** -- run simulations, view PnL distributions
4. **Risk** -- margin ratio, drawdown, alert history, engine mode

**Rationale:** Streamlit is the fastest path to a functional dashboard with Python. No frontend framework needed. The dashboard is a viewer -- it does not control the engine.

### Sequential optimization: orchestrated by optimizer module

The `optimizer.py` module coordinates the 2-stage sequential optimization:
1. Stage 1: Train prediction models, evaluate on model_val split
2. Stage 2: Freeze signals (precompute via `predict_batch`), sweep position params via scanner on pos_train+val split
3. Robustness test: degrade model accuracy, verify Sharpe holds
4. Final OOS: one-shot evaluation on the held-out 10%

**Rationale:** This follows the architecture doc's Optimization Protocol. Keeping it as an orchestrator module makes it reusable and testable.

### Config: layered TOML

All configuration loads from TOML files. A `config.py` module provides typed loading that validates and constructs the appropriate dataclasses (PyramidConfig, risk thresholds, model params, etc.).

**Rationale:** TOML is human-readable and well-supported in Python 3.12+ (tomllib in stdlib). Typed loading ensures config errors are caught at startup.

## Risks / Trade-offs

- **[Risk] Streamlit dashboard may be slow with large datasets** -> Mitigation: Paginate trade logs, downsample equity curves for display, use st.cache for expensive computations.
- **[Risk] Risk Monitor as async task may not catch issues fast enough** -> Mitigation: Configurable check interval (default 30s). Upgrade to separate process in Phase 2.
- **[Risk] Sequential optimization is computationally expensive** -> Mitigation: Cache Stage 1 signals (precompute once). Stage 2 scanner uses Ray parallelization from Sprint C.
- **[Risk] TOML config proliferation** -> Mitigation: Keep config files minimal and well-documented. Use a single top-level config that references sub-configs.
