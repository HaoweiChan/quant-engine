# Phase A Migration Impact Report

**Date**: 2026-03-25
**Change**: `institutional-grade-upgrade` (Phase A)
**Summary**: Replaced naive `ClosePriceFillModel` and `OpenPriceFillModel` with `MarketImpactFillModel`, added OMS (TWAP/VWAP/POV), and pre-trade risk gate.

## Breaking Changes

| Component | Before | After |
|-----------|--------|-------|
| Fill Model | `ClosePriceFillModel` — fills at bar close | `MarketImpactFillModel` — square-root impact + spread + latency |
| Fill Model (alt) | `OpenPriceFillModel` — fills at bar open | **Removed** |
| Execution Cost | Zero | `impact = k × σ × √(Q/V)` + half-spread + latency shift |
| Partial Fills | Never | Orders exceeding 10% ADV get partial fills |
| OMS | None | TWAP/VWAP/POV slicing for large orders |
| Pre-Trade Risk | None | Gross exposure and ADV participation gates |

## Expected PnL Impact

The MarketImpactFillModel introduces execution costs that were previously invisible:

- **Market Impact**: Proportional to `σ × √(Q/V)` — typically 0.5-5 points per trade
- **Spread Cost**: Half-spread per trade (1 bps default = ~2 points on TX at 20000)
- **Latency Shift**: Random [5ms, 50ms] price drift simulated

**Expected PnL reduction**: 10-30% compared to naive model backtests, depending on:
- Average position size relative to ADV
- Market volatility (σ)
- Number of trades

This reduction reflects *reality* — the old model overstated PnL by ignoring execution costs.

## New Metrics in BacktestResult

All backtests now include:
- `total_market_impact` — cumulative impact cost across all trades
- `total_spread_cost` — cumulative spread crossing cost
- `avg_latency_ms` — average simulated latency
- `partial_fill_count` — number of orders that received partial fills
- `impact_report` — full naive-vs-realistic PnL comparison

## Migration Notes

1. All imports of `ClosePriceFillModel` / `OpenPriceFillModel` must be updated to `MarketImpactFillModel`
2. `BacktestRunner()` without explicit `fill_model` now uses `MarketImpactFillModel()` by default
3. Custom `ImpactParams` can be passed to tune the model: `MarketImpactFillModel(ImpactParams(k=0.8))`
4. The OMS is optional — pipeline works with or without it wired in
5. Pre-trade risk check is optional — `PositionEngine` works identically when `pre_trade_check=None`

## Test Coverage

| Module | Tests | Status |
|--------|-------|--------|
| MarketImpactFillModel | 16 | ✅ All pass |
| OMS (TWAP/VWAP/POV) | 12 | ✅ All pass |
| Pre-Trade Risk | 8 | ✅ All pass |
| Position Engine (existing) | 27 | ✅ All pass |
| Execution Engine OMS Integration | 13 | ✅ All pass |
| Impact Report | 7 | ✅ All pass |
| Paper Executor (existing) | 7 | ✅ All pass |
| Phase A E2E Integration | 3 | ✅ All pass |
| **Total** | **93** | **✅ All pass** |
