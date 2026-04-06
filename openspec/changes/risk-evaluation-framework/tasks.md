## 1. Transaction Cost Model

- [x] 1.1 Add `InstrumentCostConfig` dataclass and `INSTRUMENT_COSTS` registry to `src/core/types.py` — TX: 0.1% slippage + NT$100 commission, MTX: 0.1% slippage + NT$40 commission. Acceptance: types import cleanly, mypy passes.
- [x] 1.2 Update MCP facade (`src/mcp_server/facade.py`) to inject default costs from `INSTRUMENT_COSTS` when `slippage_bps`/`commission_fixed_per_contract` are not explicitly provided. Acceptance: calling `run_backtest` without cost params applies non-zero defaults; explicit `slippage_bps=0.0` is respected.
- [x] 1.3 Add `gross_pnl`, `net_pnl`, `total_slippage_cost`, `total_commission_cost`, `cost_drag_pct` to backtest result metrics in `src/simulator/backtester.py`. Acceptance: backtest output includes cost breakdown fields.
- [x] 1.4 Add `high_cost_drag` warning flag when `cost_drag_pct > 50%`. Acceptance: a strategy with high friction triggers the warning in results.
- [x] 1.5 Write unit tests for cost injection logic — default injection, explicit override, explicit zero, unknown instrument fallback. Acceptance: `pytest tests/unit/test_cost_model.py` green.

## 2. Parameter Sensitivity Enhancement

- [x] 2.1 Extend parameter sensitivity module to compute `cliff_detected` flag — True when Sharpe drops >30% between adjacent grid points. Acceptance: synthetic test with a cliff returns `cliff_detected=True`.
- [x] 2.2 Add `stability_cv` metric (CV of Sharpe across perturbation grid) to each parameter result. Acceptance: result dict includes `stability_cv` per parameter.
- [x] 2.3 Add `optimal_at_boundary` warning when best Sharpe is at grid edge. Acceptance: a sweep where optimum is at ±20% boundary triggers the flag.
- [x] 2.4 Add aggregate `likely_overfit` assessment — True when >50% of parameters have cliff or instability. Acceptance: multi-parameter sweep with mixed stability returns correct aggregate flag.
- [x] 2.5 Ensure all perturbation backtests use default instrument costs (not zero). Acceptance: perturbation results reflect cost-adjusted metrics.
- [x] 2.6 Write unit tests for cliff detection, stability CV, boundary warning, and overfit flag. Acceptance: `pytest tests/unit/test_param_sensitivity.py` green.

## 3. Regime-Conditioned Monte Carlo

- [x] 3.1 Create `src/simulator/regime.py` with `RegimeModel` dataclass, `fit_regime_model()`, and `label_regimes()` using `hmmlearn.GaussianHMM`. Acceptance: 2-state model fits on synthetic returns, labels array matches input length.
- [x] 3.2 Add `hmmlearn` to project dependencies. Acceptance: `uv pip install` succeeds, import works.
- [x] 3.3 Extend `BlockBootstrapMC.simulate()` to accept optional `regime_model` parameter — when provided, resample blocks within-regime. Acceptance: regime-conditioned paths differ from global paths; fallback without model is unchanged.
- [x] 3.4 Add `RegimeMetrics` dataclass and per-regime metric computation to MC results. Acceptance: MC result includes `regime_metrics` list with per-regime Sharpe, MDD, win rate.
- [x] 3.5 Add `worst_regime` identification to MC results. Acceptance: result highlights regime with lowest Sharpe.
- [x] 3.6 Handle HMM convergence failure with `RegimeModelError`. Acceptance: non-converging fit raises descriptive error.
- [x] 3.7 Write unit tests for regime fitting, labeling, within-regime bootstrap, and fallback. Acceptance: `pytest tests/unit/test_regime.py` green.

## 4. Adversarial Scenario Injection

- [x] 4.1 Create `src/simulator/adversarial.py` with `InjectionConfig`, `AdversarialResult`, and injection logic that embeds stress scenarios at random positions in MC paths. Acceptance: 30% of paths have injected events, injection preserves path prefix.
- [x] 4.2 Implement multi-scenario support — when multiple configs provided, each path gets at most one injection selected uniformly. Acceptance: mixed scenario injection test passes.
- [x] 4.3 Compute `worst_case_terminal_equity` and `median_impact_pct` from injected vs clean paths. Acceptance: adversarial result includes both metrics with correct values.
- [x] 4.4 Compute side-by-side `clean_metrics` vs `injected_metrics` (VaR, CVaR, P(Ruin)). Acceptance: both metric sets present in result.
- [x] 4.5 Write unit tests for injection positioning, probability, impact calculation, and multi-scenario selection. Acceptance: `pytest tests/unit/test_adversarial.py` green.

## 5. Walk-Forward OOS Validation

- [x] 5.1 Create `src/simulator/walk_forward.py` with `WalkForwardConfig`, `FoldResult`, `WalkForwardResult`, and expanding-window walk-forward engine. Acceptance: 3-fold split on 4-year data produces correct date ranges.
- [x] 5.2 Implement IS optimization — run parameter sweep (±20% grid, capped at `max_sweep_combinations`) on each fold's IS window. Acceptance: fold result includes `is_best_params` and `is_sharpe`.
- [x] 5.3 Implement OOS evaluation — backtest with IS-optimized params on OOS window, report Sharpe, MDD, win rate, trade count, profit factor. Acceptance: fold result includes all OOS metrics.
- [x] 5.4 Implement overfit ratio logic — `oos_sharpe / is_sharpe`, handle negative OOS (set to 0.0), compute mean ratio, set `overfit_flag` ("none" ≥0.7, "mild" 0.3–0.7, "severe" <0.3). Acceptance: synthetic IS/OOS ratios produce correct flags.
- [x] 5.5 Add per-session filtering — `session="day"` filters to 08:45–13:45, `session="night"` to 15:00–05:00+1d. Acceptance: day-only walk-forward excludes night bars.
- [x] 5.6 Implement quality gate pass/fail logic: aggregate OOS Sharpe ≥0.6, no severe overfit, MDD ≤20%, win rate 35–70%, N trades ≥30, profit factor ≥1.2. Acceptance: failing any criterion sets `passed=False` with `failure_reasons`.
- [x] 5.7 Write unit tests for fold splitting, IS optimization, OOS evaluation, overfit detection, session filtering, and gate logic. Acceptance: `pytest tests/unit/test_walk_forward.py` green.

## 6. Risk Sign-Off Report

- [x] 6.1 Create `src/simulator/risk_report.py` with `RiskReport` dataclass and gate evaluation logic. Acceptance: report assembles from five layer results, applies pass/fail per gate.
- [x] 6.2 Implement gate criteria — cost (net Sharpe ≥0.5, drag <80%), param stability (no cliffs, >50% stable), regime (worst Sharpe ≥0.4), adversarial (MDD <25%, equity >50% initial), walk-forward (delegated). Acceptance: synthetic results produce correct gate outcomes.
- [x] 6.3 Implement recommendation logic — "promote" (all pass), "investigate" (non-critical fail), "reject" (critical fail). Acceptance: each recommendation triggered by correct conditions.
- [x] 6.4 Write unit tests for all gate evaluations and recommendation logic. Acceptance: `pytest tests/unit/test_risk_report.py` green.

## 7. MCP Tool Integration

- [x] 7.1 Register `run_walk_forward` MCP tool in `src/mcp_server/facade.py` and `server.py` with input schema validation. Acceptance: tool appears in `tools/list`, accepts strategy/n_folds/session params.
- [x] 7.2 Register `run_risk_report` MCP tool with cached result assembly, `force_rerun` support, and missing layer handling. Acceptance: tool returns unified report, reports `not_evaluated` for missing layers.
- [x] 7.3 Verify default cost injection works for all existing tools (`run_backtest`, `run_monte_carlo`, `run_parameter_sweep`, `run_stress_test`). Acceptance: calling each tool without cost params produces non-zero cost metrics in output.

## 8. FastAPI Endpoints

- [x] 8.1 Add `GET /api/risk-report/{strategy_name}` endpoint in `src/api/routes/`. Acceptance: returns JSON risk report, 404 for missing strategies.
- [x] 8.2 Add `POST /api/walk-forward/{strategy_name}` endpoint to trigger walk-forward validation. Acceptance: returns walk-forward results with per-fold breakdown.

## 9. Integration Testing

- [x] 9.1 End-to-end test: run full risk evaluation pipeline for a test strategy — costs → sensitivity → regime MC → adversarial → walk-forward → report. Acceptance: report returns with all five layers evaluated and correct pass/fail.
- [x] 9.2 Backward compatibility test: verify existing MCP tool calls without cost params still work (now with default costs applied). Acceptance: existing test suite passes with default cost injection.
