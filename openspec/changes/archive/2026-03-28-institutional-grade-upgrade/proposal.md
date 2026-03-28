## Why

Our backtested PnL curves are inflated by an estimated 3-5x due to the `ClosePriceFillModel` and zero market-impact modeling. An internal gap analysis (docs/critics-gemini.md) identified the fill simulation and order execution as the most critical deficiency — the single fastest way to bankrupt a fund. This is Phase A of the institutional-grade upgrade: replacing the naive fill model with a volume-aware market-impact simulator and adding an OMS slicing layer. Phase B (PIT data), Phase C (portfolio risk), and Phase D (event engine + audit) are tracked as separate changes.

## What Changes

- **Remove `ClosePriceFillModel` and `OpenPriceFillModel`** — hard-cut, no legacy mode. All backtests must use realistic fill simulation.
- **Implement `MarketImpactFillModel`** with square-root impact formula (`impact = k × σ × √(Q/V)`), spread-crossing costs, latency delay simulation (5-50ms), and partial fill support
- **Build auto-calibration pipeline** that starts with academic TAIFEX impact parameters and learns from live fill data over time
- **Add Order Management System (OMS)** with TWAP, VWAP, and POV slicing algorithms between Position Engine and Execution Engine
- **Add pre-trade risk gate** to Position Engine's `on_snapshot()` that evaluates orders against configurable limits before emission
- **Add OMS metadata** to all generated orders (urgency classification, ADV estimates)
- **BREAKING**: `ClosePriceFillModel` removed entirely; `BacktestRunner` defaults to `MarketImpactFillModel`
- **BREAKING**: All existing backtest results invalidated (expected 3-5x PnL reduction reflecting reality)

## Capabilities

### New Capabilities
- `market-impact-fill-model`: Volume-aware fill simulation with square-root impact, spread-crossing, partial fills, latency delay (5-50ms), and auto-calibration from live fills
- `order-management-system`: OMS slicing layer (TWAP/VWAP/POV) between Position Engine and Execution Engine, with passthrough for small orders

### Modified Capabilities
- `simulator`: BacktestRunner defaults to `MarketImpactFillModel`; Monte Carlo and stress tests updated; impact analysis report added
- `position-engine`: `on_snapshot()` gains pre-trade risk gate and OMS metadata on generated orders
- `execution-engine`: Receives orders from OMS; tracks parent-child relationships; reports actual impact for calibration

## Impact

- **Core modules**: `src/simulator/fill_model.py`, `src/core/position_engine.py`, `src/execution/`
- **New modules**: `src/oms/`
- **Types**: `ImpactParams`, `OMSConfig`, `PreTradeRiskConfig`, `SlicedOrder`, `ChildOrder` in `src/core/types.py`; extended `Fill` dataclass
- **Dependencies**: No new external deps (all stdlib + existing numpy/polars)
- **Tests**: New test suites for fill models, OMS algorithms, pre-trade gating
- **Existing backtests**: All historical results invalidated — must re-run with new fill models
