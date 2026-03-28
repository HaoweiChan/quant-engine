## 1. MonteCarloReport Dataclass & MDD/Ruin Utilities

- [ ] 1.1 Create `MonteCarloReport` dataclass in `src/monte_carlo/report.py` with fields: `mode`, `initial_capital`, `n_paths`, `n_days`, `bands`, `var_95`, `var_99`, `cvar_95`, `cvar_99`, `prob_ruin`, `method`, `mdd_values`, `mdd_p95`, `mdd_median`, `ruin_thresholds`, `param_sensitivity`, `sharpe_values`, `sortino_values`, `final_pnls`. Add `to_dict()` method for JSON serialization. Acceptance: dataclass imports cleanly, round-trip preserves all fields, mypy passes.
- [ ] 1.2 Implement `compute_mdd(equity_curve: list[float]) -> float` in `src/monte_carlo/mdd_analysis.py` returning maximum peak-to-trough drawdown as a fraction. Acceptance: `compute_mdd([100, 110, 90, 95])` returns ~0.1818.
- [ ] 1.3 Implement `compute_mdd_distribution(paths: list[list[float]]) -> tuple[list[float], float, float]` returning `(mdd_values, mdd_p95, mdd_median)`. Acceptance: returns correct P95 and median for a known set of paths.
- [ ] 1.4 Implement `compute_ruin_probability(paths: list[list[float]], initial_capital: float, thresholds: list[float]) -> dict[str, float]` in `src/monte_carlo/ruin_probability.py` returning fraction of paths breaching each drawdown threshold. Acceptance: 100% ruin for threshold 0.0, 0% for threshold -2.0 on non-negative paths. Default thresholds: [-0.30, -0.50, -1.00].

## 2. Trade-Level P&L Resampling

- [ ] 2.1 Implement `run_trade_resampling(trade_pnls: list[float], n_paths: int, initial_capital: float, block_size: int = 1) -> list[list[float]]` in `src/monte_carlo/trade_resampling.py`. Simple bootstrap when `block_size=1`, block bootstrap otherwise. Acceptance: returns `n_paths` equity curves each of length `len(trade_pnls) + 1`, starting from `initial_capital`.
- [ ] 2.2 Add validation: raise `ValueError` when `trade_pnls` is empty. Acceptance: pytest raises on empty input.

## 3. GBM Synthetic Price Path Generation

- [ ] 3.1 Implement `generate_gbm_paths(historical_prices: list[float], n_paths: int, n_days: int, fat_tails: bool = False, df: int = 5) -> list[list[float]]` in `src/monte_carlo/gbm_paths.py`. Calibrate μ and σ from historical log-returns, generate paths using GBM with optional Student-t innovations. Acceptance: all paths start from `historical_prices[-1]`, length is `n_days`.
- [ ] 3.2 Implement `build_synthetic_ohlcv(close_series: list[float], mean_volume: float) -> list[dict]` to construct OHLCV bars from GBM close prices. Acceptance: each bar has `open`, `high`, `low`, `close`, `volume` keys.
- [ ] 3.3 Add validation: raise `ValueError` when `historical_prices` has fewer than 30 data points. Acceptance: pytest raises on short input.

## 4. Parameter Sensitivity Engine

- [ ] 4.1 Implement `run_param_sensitivity(strategy: str, symbol: str, start: str, end: str, base_params: dict, param_schema: list[dict], bar_agg: int, initial_capital: float, offsets: list[float] | None = None) -> dict[str, list[dict]]` in `src/monte_carlo/param_sensitivity.py`. For each numeric param, perturb by ±offsets, run backtest, collect Sortino. Include baseline (offset=0) entry. Acceptance: result dict has one key per numeric param, each value is a list of `{"offset", "value", "sortino"}` dicts.
- [ ] 4.2 Ensure integer params are rounded and all perturbed values are clamped to `[min, max]` from param_schema. Acceptance: no perturbation exceeds schema bounds.

## 5. Monte Carlo Mode Dispatcher

- [ ] 5.1 Implement `run_monte_carlo_enhanced(...)` in `src/monte_carlo/dispatcher.py` that dispatches to `BlockBootstrapMC` (existing), `run_trade_resampling`, `generate_gbm_paths`, or `run_param_sensitivity` based on `mode` parameter. Apply `compute_mdd_distribution` and `compute_ruin_probability` to all path-producing modes. Return a `MonteCarloReport`. Acceptance: each mode returns a valid `MonteCarloReport` with all applicable fields populated.
- [ ] 5.2 For bootstrap mode, wrap existing `BlockBootstrapMC` result into `MonteCarloReport` format, adding MDD distribution and multi-threshold ruin probability fields. Acceptance: default mode returns same `bands`/`var`/`cvar` as current endpoint plus new fields.

## 6. API Endpoint Extension

- [ ] 6.1 Extend `POST /api/monte-carlo` in `src/api/routes/monte_carlo.py` to accept `mode` parameter (default "bootstrap") and mode-specific fields. Route through `run_monte_carlo_enhanced`. Acceptance: existing requests without `mode` return identical results (backward compatible); new modes return extended response.
- [ ] 6.2 Add MCP facade function in `src/mcp_server/facade.py` wrapping the dispatcher. Acceptance: MCP tool call returns same structure as API endpoint.

## 7. Frontend — Mode Selector & Controls

- [ ] 7.1 Add top-level mode dropdown to `StressTest.tsx` with options: "Block Bootstrap" (default), "Trade Resampling", "GBM Price Simulation", "Parameter Sensitivity". Acceptance: mode selection updates visible controls and is sent in API request.
- [ ] 7.2 Add mode-specific controls: existing method sub-selector for Block Bootstrap, "Block Size" for trade resampling, "Fat Tails" toggle + "Degrees of Freedom" for GBM, "Perturbation Offsets" checkboxes for sensitivity. Acceptance: controls appear/disappear based on selected mode.
- [ ] 7.3 Update `POST /api/monte-carlo` call to include `mode` and mode-specific fields. Acceptance: clicking Run sends correct request for each mode.

## 8. Frontend — MDD Distribution Chart

- [ ] 8.1 Create `MddDistributionChart` SVG component rendering a histogram of `mdd_values` from the MC report, with vertical dashed line at P95 and solid line at median. Dark theme styling. Acceptance: chart renders with correct lines when `mdd_values` is provided.
- [ ] 8.2 Integrate `MddDistributionChart` into Stress Test page below fan chart for all path-producing modes. Acceptance: visible for bootstrap, trade resampling, and GBM modes.

## 9. Frontend — Multi-Threshold Ruin Probability Display

- [ ] 9.1 Create ruin probability stat cards showing each threshold's probability with color coding (green <5%, gold 5-20%, red >20%). Acceptance: cards render from `ruin_thresholds` dict.
- [ ] 9.2 Handle empty/zero ruin thresholds with "No ruin risk detected" message. Acceptance: message displays when all probabilities are 0.

## 10. Frontend — Parameter Sensitivity Heatmap

- [ ] 10.1 Create `ParamSensitivityHeatmap` SVG component with parameters on Y-axis, offsets on X-axis, Sortino as cell color (diverging green/red scale from baseline). Acceptance: heatmap renders from `param_sensitivity` data.
- [ ] 10.2 Add hover tooltip showing param name, offset %, perturbed value, and Sortino. Acceptance: tooltip appears on cell hover.
- [ ] 10.3 Conditionally render heatmap only when `mode="sensitivity"`. Acceptance: heatmap hidden for other modes.

## 11. Frontend — Sharpe/Sortino Distribution

- [ ] 11.1 Render Sharpe and Sortino ratio distribution histograms with median lines when `sharpe_values` and `sortino_values` are present in the report. Acceptance: histograms render for modes that produce ratio distributions.

## 12. Tests

- [ ] 12.1 Unit tests for `compute_mdd`, `compute_mdd_distribution`, `compute_ruin_probability` with known inputs. Acceptance: all assertions pass.
- [ ] 12.2 Unit tests for `run_trade_resampling` covering empty input, single trade, block bootstrap. Acceptance: all edge cases pass.
- [ ] 12.3 Unit tests for `generate_gbm_paths` covering normal and Student-t innovations, short input validation. Acceptance: path shapes and validation errors correct.
- [ ] 12.4 Unit tests for `run_param_sensitivity` with a mock strategy backtest. Acceptance: result structure matches spec.
- [ ] 12.5 Integration test for `run_monte_carlo_enhanced` exercising all four modes. Acceptance: each mode returns a valid `MonteCarloReport`.
- [ ] 12.6 API test for extended `POST /api/monte-carlo` with each mode. Acceptance: 200 response with all required fields for each mode. Backward compatibility: request without `mode` returns same structure as before.
