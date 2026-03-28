## 1. Core — Portfolio Merger

- [x] 1.1 Create `src/core/portfolio_merger.py` with `PortfolioMergerInput`, `PortfolioMergeResult` dataclasses and `PortfolioMerger` class. Implement `merge()` with weighted daily-return summation, equity-curve compounding, and weight normalization. Accept: `merge([A(w=0.5), B(w=0.5)])` returns correct weighted returns and equity curve.
- [x] 1.2 Implement correlation matrix computation using `numpy.corrcoef` on aligned daily return arrays. Accept: 2-strategy input returns 2×2 matrix with 1.0 diagonal; 3-strategy returns 3×3.
- [x] 1.3 Implement portfolio metrics computation (total_return, sharpe, sortino, max_drawdown_pct, calmar, annual_return, annual_vol, n_days). Handle edge cases: zero-variance returns → Sharpe=0, single strategy passthrough. Accept: metrics dict contains all keys with valid floats.
- [x] 1.4 Handle unequal return-series lengths by aligning to the longer series with 0.0 padding for missing days. Accept: strategy with 100 days + strategy with 80 days → merged series of 100 days.

## 2. Core — Risk Monitor Extension

- [x] 2.1 Add `max_combined_positions: int | None = None` field to `RiskConfig` in `src/core/types.py`. Accept: default is `None`, existing tests unchanged.
- [x] 2.2 Add combined position limit check in `RiskMonitor.check()`: sum open positions across all strategies bound to the account, return `HALT_NEW_ENTRIES` if exceeding limit. Skip if `None`. Accept: 7 open positions with `max_combined_positions=6` → HALT.

## 3. Backend — API Endpoints

- [x] 3.1 Create `src/api/routes/portfolio.py` with `PortfolioBacktestRequest`, `StrategyEntry` Pydantic models. Accept: models validate correctly with 2-3 strategies.
- [x] 3.2 Implement `POST /api/portfolio/backtest` endpoint: validate 2-3 strategies, run individual backtests via `run_strategy_backtest`, feed daily returns into `PortfolioMerger`, return combined results. Accept: 2-strategy request returns merged metrics, individual summaries, and correlation matrix.
- [x] 3.3 Implement `POST /api/portfolio/stress-test` endpoint: run backtests, merge returns, feed into `BlockBootstrapMC`, return fan-chart bands + risk metrics in same shape as `/api/monte-carlo`. Accept: response has `var_95`, `bands`, `prob_ruin` keys.
- [x] 3.4 Register portfolio router in `src/api/main.py`. Accept: endpoints appear in `/docs` Swagger UI.

## 4. Tests — Backend

- [x] 4.1 Unit tests for `PortfolioMerger`: equal weights, custom weights, auto-normalization, unequal lengths, single strategy, empty returns error. File: `tests/unit/core/test_portfolio_merger.py`.
- [x] 4.2 Unit tests for combined position limit in risk monitor. File: `tests/unit/risk/test_combined_limit.py`.
- [x] 4.3 Integration test for `/api/portfolio/backtest` endpoint with mock strategy data. File: `tests/e2e/test_portfolio_endpoints.py`.
- [x] 4.4 Integration test for `/api/portfolio/stress-test` endpoint. Same file as 4.3.

## 5. Frontend — Portfolio Tab

- [x] 5.1 Create `frontend/src/pages/strategy/Portfolio.tsx` component with strategy selection dropdowns (2 default, expandable to 3), weight inputs, and "Merge & Analyze" button. Accept: renders in Strategy page sub-tab bar.
- [x] 5.2 Wire strategy dropdown options from `/api/strategies` registry endpoint. Add duplicate-strategy prevention (disable Merge button + warning). Accept: dropdowns show registered strategies.
- [x] 5.3 Implement "Merge & Analyze" click handler: call `/api/portfolio/backtest`, display loading state, show results on success, show error on failure. Accept: successful merge displays results section.
- [x] 5.4 Build combined equity curve chart: overlay individual strategy curves (dimmed) with bold portfolio curve. Use existing chart styling conventions. Accept: chart shows N+1 lines with legend.
- [x] 5.5 Build side-by-side metrics table: columns for each strategy + portfolio. Highlight portfolio cells that beat all individual strategies. Accept: table renders with correct metrics.
- [x] 5.6 Build correlation matrix display: small heatmap with color coding (red=high, green=low, blue=negative). Accept: 2×2 or 3×3 matrix renders with values.
- [x] 5.7 Add "Run Portfolio Stress Test" button: call `/api/portfolio/stress-test`, display fan chart and risk metrics using same components as StressTest page. Disabled until merge is run. Accept: fan chart + VaR/CVaR/P(Ruin) display after stress test.
- [x] 5.8 Add "Portfolio" tab to Strategy page sub-tab bar in the router/layout. Accept: clicking "Portfolio" tab navigates to the new component.

## 6. Integration & Verification

- [x] 6.1 End-to-end browser test: select 2 strategies → Merge → verify combined equity chart + metrics table + correlation matrix display correctly.
- [x] 6.2 End-to-end browser test: after merge → run portfolio stress test → verify fan chart + risk metrics render.
- [x] 6.3 Verify backward compatibility: existing single-strategy backtest, stress test, and param sweep pages unaffected.
