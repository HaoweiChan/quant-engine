## Why

Current stress testing runs stationary block bootstrap with zero transaction costs, producing misleadingly optimistic metrics (e.g., P(Ruin) = 0.0%). Before any strategy can be promoted to live trading, we need a multi-layer risk evaluation framework that tests regime robustness, parameter sensitivity, adversarial scenarios, walk-forward validation, and realistic friction — all as mandatory gates in the sign-off checklist. Without this, we risk deploying curve-fitted strategies that collapse under real market conditions.

## What Changes

- **Default transaction costs**: Enforce slippage (0.1%) and commission (NT$40 MTX / NT$100 TX round-trip) as defaults across all backtest, Monte Carlo, parameter sweep, and stress test runs. Zero-cost runs require explicit opt-in.
- **Parameter sensitivity analysis**: Automated ±20% grid sweep around active params with cliff-edge detection and stability scoring (CV of Sharpe across grid). Flags overfitting when Sharpe degrades >30%.
- **Regime-conditioned Monte Carlo**: Fit 2–3 state HMM on TAIEX daily returns; bootstrap within each regime. Report per-regime P50 Sharpe, MDD, and win rate instead of aggregate-only.
- **Adversarial scenario injection**: Inject existing stress scenarios (gap_down, slow_bleed, flash_crash, vol_regime_shift, liquidity_crisis) at random positions within Monte Carlo paths. Report worst-case terminal equity under embedded stress events.
- **Walk-forward OOS validation**: Expanding-window walk-forward with 3 folds. Report OOS Sharpe separately, flag overfit when OOS/IS ratio < 0.7, reject below 0.3. Validate day and night sessions independently.
- **Unified risk report**: Aggregate all five layers into a single sign-off report accessible via MCP tools and FastAPI endpoints, displayed in the frontend Stress Test tab.

## Capabilities

### New Capabilities
- `transaction-cost-model`: Default slippage/commission configuration for all simulation paths, per-instrument cost schedules, and cost-aware metric reporting
- `parameter-sensitivity`: Automated ±20% grid sweep, cliff-edge detection, stability scoring, overfitting flags
- `regime-conditioned-mc`: HMM regime labeling on TAIEX daily returns, within-regime bootstrap, per-regime performance metrics
- `adversarial-scenario-injection`: Stress scenario embedding into Monte Carlo paths at random insertion points, worst-case terminal equity reporting
- `walk-forward-validation`: Expanding-window OOS validation with configurable folds, IS/OOS ratio analysis, per-session validation
- `risk-sign-off-report`: Unified multi-layer risk report aggregating all evaluation layers for strategy promotion decisions

### Modified Capabilities
- `block-bootstrap-mc`: Monte Carlo must accept regime-conditioned paths and adversarial injections; cost model must be applied to all simulated paths
- `mc-param-sensitivity`: Extend with cliff-edge detection and stability scoring; integrate cost model into sweep runs
- `backtest-mcp-server`: New MCP tools for walk-forward validation and risk report generation; default cost params injected into all existing tools

## Impact

- **`src/simulator/`**: New modules for regime HMM, walk-forward engine, adversarial injection. Modifications to `stress.py`, Monte Carlo, and backtester to enforce cost defaults.
- **`src/mcp_server/facade.py`**: New tool registrations (`run_walk_forward`, `run_risk_report`). Default cost params injected into existing tools (`run_backtest`, `run_monte_carlo`, `run_parameter_sweep`, `run_stress_test`).
- **`src/core/types.py`**: Cost configuration types, per-instrument commission schedule.
- **`src/api/routes/`**: New endpoints for walk-forward results and risk reports.
- **`frontend/`**: Enhanced Stress Test tab with regime breakdown, parameter heatmaps, walk-forward charts, and unified sign-off dashboard.
- **`configs/`**: Default cost configuration added to strategy TOML files.
- **Dependencies**: `hmmlearn` for regime detection (new dependency).
