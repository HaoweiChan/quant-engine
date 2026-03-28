## Context

The system currently runs backtests and Monte Carlo stress tests on a single strategy at a time. The Trading section already supports binding multiple strategies to one broker account, but there is no way to evaluate the combined risk profile before going live. Users can individually backtest strategies, but the portfolio-level effects (correlated drawdowns, margin competition, combined VaR) remain invisible until live trading.

**Current flow:**
```
Strategy Page → Backtest (single) → Stress Test (single) → Trading (deploy N strategies)
                                                            ↑ GAP: no combined test
```

**Target flow:**
```
Strategy Page → Backtest (single) × N → Portfolio Tab → Merge + Portfolio Stress Test → Trading
```

### Constraints
- Each strategy runs independently as a "virtual sub-account" — no netting of signals at the backtest level.
- Up to 3 strategies max on one account (user requirement).
- Portfolio merge uses pre-computed individual backtest results (no re-running).
- Backend already has `BlockBootstrapMC` and daily returns infrastructure ready for reuse.

## Goals / Non-Goals

**Goals:**
- Provide a `/api/portfolio/backtest` endpoint that merges N individual backtest daily-return series into a combined equity curve.
- Provide a `/api/portfolio/stress-test` endpoint that runs Monte Carlo on the merged returns.
- Build a frontend "Portfolio" sub-tab for selecting strategies, viewing side-by-side results, and combined visualizations.
- Show inter-strategy return correlation matrix.
- Enforce combined position limits in the risk monitor for live accounts.

**Non-Goals:**
- Joint parameter sweep across multiple strategies simultaneously.
- Intra-bar interaction between strategies (they remain independent virtual sub-accounts).
- Dynamic capital rebalancing between strategies during the backtest.
- Cross-instrument portfolio optimization (Phase 1 is single-instrument only).

## Decisions

### D1: Virtual sub-account model for backtest merging
**Choice:** Each strategy's backtest runs independently. The portfolio merge operates on daily returns only (not bar-by-bar trades).

**Rationale:** The user confirmed strategies act as independent virtual sub-accounts (option A). Bar-level merging would require a fundamentally different simulator architecture. Daily-return merging is simple, correct for capital-level analysis, and uses existing infrastructure.

**Alternative considered:** Full bar-level simulation with shared order book. Rejected — too complex for the initial implementation, and the user prioritized simplicity.

### D2: Additive daily PnL merging with capital weighting
**Choice:** Merge by summing weighted daily PnL: `portfolio_return[t] = Σ(w_i × strategy_return_i[t])` where weights default to equal (1/N) but are user-configurable.

**Rationale:** This correctly models the combined equity trajectory under shared capital. Equal weighting is the simplest and most intuitive default for ≤3 strategies.

**Alternative considered:** Multiplicative compounding of individual strategy returns. Rejected — it doesn't properly account for shared capital (double-counts compounding).

### D3: Reuse existing BlockBootstrapMC for portfolio stress test
**Choice:** Feed the merged daily returns into the existing `BlockBootstrapMC` class.

**Rationale:** The Monte Carlo infrastructure already supports any daily-returns array. No need to build a separate portfolio MC engine. The merged returns naturally capture inter-strategy correlation.

### D4: Frontend as a new sub-tab in Strategy section
**Choice:** Add "Portfolio" as a sub-tab alongside Backtest, Stress Test, Tear Sheet, Param Sweep in the Strategy page.

**Rationale:** Portfolio analysis is strategy-related research, not trading operations. Keeping it in the Strategy section maintains the workflow: research → validate → deploy.

### D5: Combined position limit in risk monitor
**Choice:** Add a `max_combined_positions` field to `RiskConfig`. The risk monitor sums open positions across all strategies bound to an account and enforces the limit.

**Rationale:** This is the simplest form of cross-strategy risk control. It prevents margin exhaustion without complex per-strategy allocation logic. The user confirmed sequential execution and combined limit enforcement.

## Architecture

```
┌──────────────────── Frontend ──────────────────────┐
│                                                     │
│  Portfolio Tab                                      │
│  ┌────────────────────────────────────────────┐     │
│  │ Select Strategy A  [dropdown]              │     │
│  │ Select Strategy B  [dropdown]              │     │
│  │ Select Strategy C  [dropdown] (optional)   │     │
│  │ Weights: [33%] [33%] [34%]                 │     │
│  │ [Merge & Analyze]                          │     │
│  ├────────────────────────────────────────────┤     │
│  │ Combined Equity Curve (overlaid)           │     │
│  │ Side-by-side Metrics Table                 │     │
│  │ Correlation Matrix Heatmap                 │     │
│  │ [Run Portfolio Stress Test]                │     │
│  │ Combined Fan Chart + Risk Metrics          │     │
│  └────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────┘
                          │
            POST /api/portfolio/backtest
            POST /api/portfolio/stress-test
                          │
┌──────────────────── Backend ───────────────────────┐
│                                                     │
│  src/api/routes/portfolio.py                        │
│    ├── PortfolioBacktestRequest                     │
│    │     strategies: [{slug, params, weight}]       │
│    │     symbol, start, end, initial_capital        │
│    ├── run_portfolio_backtest()                     │
│    │     → runs N individual backtests              │
│    │     → calls PortfolioMerger.merge()            │
│    │     → returns combined metrics + correlation   │
│    │                                                │
│    ├── PortfolioStressRequest                       │
│    │     merged_daily_returns: float[]              │
│    │     (or re-derive from strategies)             │
│    └── run_portfolio_stress_test()                  │
│          → feeds merged returns into BlockBootstrapMC│
│          → returns fan chart bands + risk metrics   │
│                                                     │
│  src/core/portfolio_merger.py                       │
│    ├── merge_daily_returns(results, weights)        │
│    │     → weighted sum of daily returns            │
│    ├── compute_correlation(results)                 │
│    │     → NxN correlation matrix                   │
│    └── compute_portfolio_metrics(merged_curve)      │
│          → sharpe, sortino, max_dd, calmar          │
│                                                     │
│  src/core/risk_monitor.py                           │
│    └── check() — extended with combined pos limit   │
└─────────────────────────────────────────────────────┘
```

## API Contract

### POST /api/portfolio/backtest
```python
class StrategyEntry(BaseModel):
    slug: str               # e.g. "daily/trend_following/pyramid"
    params: dict | None = None
    weight: float = 1.0     # normalized to sum=1.0

class PortfolioBacktestRequest(BaseModel):
    strategies: list[StrategyEntry]   # 2-3 items
    symbol: str = "TX"
    start: str = "2025-08-01"
    end: str = "2026-03-14"
    initial_capital: float = 2_000_000.0
    slippage_bps: float = 0.0
    commission_bps: float = 0.0
```

Response: individual backtest summaries + merged equity curve + combined metrics + correlation matrix.

### POST /api/portfolio/stress-test
```python
class PortfolioStressRequest(BaseModel):
    strategies: list[StrategyEntry]   # same as above
    symbol: str = "TX"
    start: str = "2025-08-01"
    end: str = "2026-03-14"
    initial_capital: float = 2_000_000.0
    n_paths: int = 500
    n_days: int = 252
    method: str = "stationary"
    ruin_threshold: float = 0.5
```

Response: same shape as existing Monte Carlo response but derived from merged returns.

## Risks / Trade-offs

**[Risk]** Daily-return merging loses intra-day margin interaction detail.
→ **Mitigation**: Acceptable for Phase 1 per user's simplicity preference. Document that this is a conservative approximation. Margin interaction modeling can be added later.

**[Risk]** Correlation computed from backtest period may not hold out-of-sample.
→ **Mitigation**: Display correlation as informational, not as a guarantee. Stress test Monte Carlo will bootstrap from actual merged returns, naturally capturing the in-sample correlation structure.

**[Risk]** Equal weighting may not be optimal.
→ **Mitigation**: Weights are user-configurable from the start. Default to equal.

**[Risk]** Mixed-timeframe strategies (intraday + daily) may have different daily return frequencies.
→ **Mitigation**: Both produce daily returns after aggregation. The backtest runner already aggregates intraday bars to daily PnL. No special handling needed.
