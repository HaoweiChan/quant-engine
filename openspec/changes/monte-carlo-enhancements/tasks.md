## 1. Core Types & Result Dataclass

- [ ] 1.1 Add `MonteCarloReport` dataclass to `src/core/types.py` with fields: `mode`, `initial_capital`, `sim_days`, `n_paths`, `paths`, `final_pnls`, `percentiles`, `mdd_values`, `mdd_p95`, `mdd_median`, `ruin_thresholds`, `param_sensitivity`, `sharpe_values`, `sortino_values`. Acceptance: dataclass imports cleanly, mypy passes.
- [ ] 1.2 Add `to_dict()` method on `MonteCarloReport` for JSON serialization. Acceptance: round-trip `MonteCarloReport(**report.to_dict())` preserves all fields.

## 2. MDD & Ruin Probability Utilities

- [ ] 2.1 Implement `compute_mdd(equity_curve: list[float]) -> float` in `src/simulator/monte_carlo.py` returning maximum peak-to-trough drawdown as a fraction. Acceptance: `compute_mdd([100, 110, 90, 95])` returns ~0.1818.
- [ ] 2.2 Implement `compute_mdd_distribution(paths: list[list[float]]) -> tuple[list[float], float, float]` returning `(mdd_values, mdd_p95, mdd_median)`. Acceptance: returns correct P95 and median for a known set of paths.
- [ ] 2.3 Implement `compute_ruin_probability(paths: list[list[float]], initial_capital: float, thresholds: list[float]) -> dict[str, float]` returning fraction of paths breaching each drawdown threshold. Acceptance: 100% ruin for threshold 0.0, 0% for threshold -2.0 on non-negative paths.

## 3. Trade-Level P&L Resampling

- [ ] 3.1 Implement `run_trade_resampling(trade_pnls: list[float], n_paths: int, initial_capital: float, block_size: int = 1) -> list[list[float]]` in `src/simulator/monte_carlo.py`. Simple bootstrap when `block_size=1`, block bootstrap otherwise. Acceptance: returns `n_paths` equity curves each of length `len(trade_pnls) + 1`, starting from `initial_capital`.
- [ ] 3.2 Add validation: raise `ValueError` when `trade_pnls` is empty. Acceptance: pytest raises on empty input.

## 4. GBM Synthetic Price Path Generation

- [ ] 4.1 Implement `generate_gbm_paths(historical_prices: list[float], n_paths: int, n_days: int, fat_tails: bool = False, df: int = 5) -> list[list[float]]` in `src/simulator/monte_carlo.py`. Calibrate μ and σ from historical log-returns, generate paths using GBM with optional Student-t innovations. Acceptance: all paths start from `historical_prices[-1]`, length is `n_days`.
- [ ] 4.2 Implement `build_synthetic_ohlcv(close_series: list[float], mean_volume: float) -> list[dict]` to construct OHLCV bars from GBM close prices. Acceptance: each bar has `open`, `high`, `low`, `close`, `volume` keys.
- [ ] 4.3 Add validation: raise `ValueError` when `historical_prices` has fewer than 30 data points. Acceptance: pytest raises on short input.

## 5. Parameter Sensitivity Engine

- [ ] 5.1 Implement `run_param_sensitivity(strategy: str, symbol: str, start: str, end: str, base_params: dict, param_schema: list[dict], bar_agg: int, initial_capital: float, offsets: list[float] | None = None) -> dict[str, list[dict]]` in `src/simulator/monte_carlo.py`. For each numeric param, perturb by ±offsets, run backtest, collect Sortino. Include baseline (offset=0) entry. Acceptance: result dict has one key per numeric param, each value is a list of `{"offset", "value", "sortino"}` dicts.
- [ ] 5.2 Ensure integer params are rounded and all perturbed values are clamped to `[min, max]` from `PARAM_SCHEMA`. Acceptance: no perturbation exceeds schema bounds.

## 6. Monte Carlo Mode Dispatcher

- [ ] 6.1 Implement `run_monte_carlo_enhanced(...)` in `src/simulator/monte_carlo.py` that dispatches to bootstrap, trade_resampling, gbm, or sensitivity based on `mode` parameter, runs the simulation, then applies `compute_mdd_distribution` and `compute_ruin_probability` to all generated paths, and returns a `MonteCarloReport`. Acceptance: each mode returns a valid `MonteCarloReport` with all core fields populated.
- [ ] 6.2 Implement path downsampling: when `n_paths > 200`, downsample `paths` list to 200 for the report while computing stats on all paths. Acceptance: `report.paths` has at most 200 entries even when `n_paths=1000`.

## 7. API & MCP Wiring

- [ ] 7.1 Add `POST /api/mc/run` endpoint in `src/api/main.py` that accepts mode, strategy params, and MC config, calls `run_monte_carlo_enhanced`, and returns serialized `MonteCarloReport`. Acceptance: curl POST returns valid JSON with all report fields.
- [ ] 7.2 Add facade function `run_monte_carlo_enhanced_for_mcp(...)` in `src/mcp_server/facade.py` that wraps the enhanced MC dispatcher. Acceptance: MCP tool call returns same structure as API endpoint.

## 8. Frontend — Mode Selector & Sidebar Controls

- [ ] 8.1 Add mode dropdown to Monte Carlo sidebar with options: "Bootstrap", "Trade Resampling", "GBM Price Simulation", "Parameter Sensitivity". Acceptance: mode selection updates sidebar and is sent in API request.
- [ ] 8.2 Add mode-specific controls: "Block Size" for trade resampling, "Fat Tails" toggle + "Degrees of Freedom" for GBM, "Perturbation Offsets" checkboxes for sensitivity. Acceptance: controls appear/disappear based on selected mode.
- [ ] 8.3 Replace frontend-only bootstrap with `POST /api/mc/run` call. Acceptance: clicking Run sends request to backend, results render from API response.

## 9. Frontend — MDD Distribution Chart

- [ ] 9.1 Create `MddDistributionChart` component rendering a histogram of `mdd_values` from the MC report, with vertical dashed line at P95 and solid line at median. Dark theme styling. Acceptance: chart renders with correct lines when `mdd_values` is provided.
- [ ] 9.2 Integrate `MddDistributionChart` into Monte Carlo page below equity paths panel. Acceptance: visible for all modes.

## 10. Frontend — Ruin Probability Display

- [ ] 10.1 Create ruin probability stat cards showing each threshold's probability with color coding (green <5%, gold 5-20%, red >20%). Acceptance: cards render from `ruin_thresholds` dict.
- [ ] 10.2 Handle empty/zero ruin thresholds with "No ruin risk detected" message. Acceptance: message displays when all probabilities are 0.

## 11. Frontend — Parameter Sensitivity Heatmap

- [ ] 11.1 Create `ParamSensitivityHeatmap` component with parameters on Y-axis, offsets on X-axis, Sortino as cell color (diverging green/red scale from baseline). Acceptance: heatmap renders from `param_sensitivity` data.
- [ ] 11.2 Add hover tooltip showing param name, offset %, perturbed value, and Sortino. Acceptance: tooltip appears on cell hover.
- [ ] 11.3 Conditionally render heatmap only when `mode="sensitivity"`. Acceptance: heatmap hidden for other modes.

## 12. Frontend — Sharpe/Sortino Distribution

- [ ] 12.1 Render Sharpe and Sortino ratio distribution histograms with median lines when `sharpe_values` and `sortino_values` are present in the report. Acceptance: histograms render for modes that produce ratio distributions.

## 13. Tests

- [ ] 13.1 Unit tests for `compute_mdd`, `compute_mdd_distribution`, `compute_ruin_probability` with known inputs. Acceptance: all assertions pass.
- [ ] 13.2 Unit tests for `run_trade_resampling` covering empty input, single trade, block bootstrap. Acceptance: all edge cases pass.
- [ ] 13.3 Unit tests for `generate_gbm_paths` covering normal and Student-t innovations, short input validation. Acceptance: path shapes and validation errors correct.
- [ ] 13.4 Unit tests for `run_param_sensitivity` with a mock strategy backtest. Acceptance: result structure matches spec.
- [ ] 13.5 Integration test for `run_monte_carlo_enhanced` exercising all four modes. Acceptance: each mode returns a valid `MonteCarloReport`.
- [ ] 13.6 API test for `POST /api/mc/run` returning correct structure. Acceptance: 200 response with all required fields.
