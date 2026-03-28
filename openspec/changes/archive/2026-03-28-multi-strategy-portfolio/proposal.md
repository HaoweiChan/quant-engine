## Why

The system currently supports backtesting and stress-testing a single strategy at a time, yet the Trading section already allows binding multiple strategies to the same broker account. Without portfolio-level testing, deploying multiple strategies on shared capital creates hidden risks: correlated drawdowns compound, margin competition starves entries, and the combined risk profile is unknown. A portfolio backtest + stress-test layer bridges this gap before live multi-strategy deployment.

## What Changes

- **New portfolio backtest endpoint** that accepts N pre-computed individual backtest results, merges their daily PnL into a combined equity curve respecting shared capital and combined position limits, and returns portfolio-level metrics (Sharpe, Sortino, max DD, VaR).
- **New portfolio stress-test endpoint** that runs Monte Carlo simulation on the merged daily returns series and produces combined terminal equity distributions, probability of ruin, and drawdown percentiles.
- **New frontend "Portfolio" sub-tab** in the Strategy section that lets users select 2-3 strategies, view individual backtest summaries side-by-side, trigger the portfolio merge, and see combined equity + stress-test results.
- **Correlation matrix display** showing inter-strategy return correlation to quantify diversification benefit.
- **Combined position limit enforcement** in the risk monitor for live trading — shared max position count across all strategies on one account.

## Capabilities

### New Capabilities
- `portfolio-backtest`: Merge up to 3 individual backtest results into a combined portfolio equity curve with shared-capital accounting, combined metrics, and correlation analysis.
- `portfolio-stress-test`: Monte Carlo simulation on merged portfolio daily returns, producing combined VaR, CVaR, probability of ruin, and terminal equity percentiles.
- `portfolio-dashboard`: Frontend sub-tab for selecting strategies, viewing side-by-side results, triggering portfolio merge, and visualizing combined equity + stress results.

### Modified Capabilities
- `risk-monitor`: Enforce combined position limits across all strategies bound to the same account during live trading.

## Impact

- **Backend**: New `src/api/routes/portfolio.py` with `/api/portfolio/backtest` and `/api/portfolio/stress-test` endpoints. New `src/core/portfolio_merger.py` for equity-curve merging logic.
- **Frontend**: New `frontend/src/pages/strategy/Portfolio.tsx` sub-tab. Minor change to strategy page layout to add the tab.
- **Risk Monitor**: Add combined position limit check in `src/core/risk_monitor.py`.
- **Dependencies**: No new Python packages required — uses existing `polars`, `numpy`, and Monte Carlo infrastructure.
- **API contracts**: Two new POST endpoints; no breaking changes to existing endpoints.
