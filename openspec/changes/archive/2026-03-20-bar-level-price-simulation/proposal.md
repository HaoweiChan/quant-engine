## Why

The current `BacktestRunner` feeds OHLC bars through `PositionEngine.on_snapshot()` and resolves fills via `FillModel` using only close/open prices. This introduces two systematic errors that overstate strategy performance:

1. **Missed intra-bar stops** — A bar that trades through a stop level and recovers by close never triggers the stop, overstating PnL.
2. **Look-ahead entry bias** — An entry signal computed from a bar's OHLC data can fill at that bar's open, using information that wasn't available yet.

This change adds intra-bar price simulation (模擬逐筆洗價) — reconstructing the plausible price path within each bar to resolve stops and entries at their correct sequence positions. This matches the behavior of XQ's "模擬逐筆洗價" feature and is a prerequisite for trustworthy backtest results on the TAIFEX pyramid strategy.

## What Changes

- Add a new `bar_simulator` module under `src/` with intra-bar price path generation, stop condition checking, entry fill filtering, and a unified `BarSimulator` class
- Introduce dataclasses for bar simulation I/O: `OHLCBar`, `StopLevel`, `StopTriggerResult`, `EntryFillResult`, `BarSimResult`
- Provide conservative high/low visit ordering based on open proximity (matching XQ's approach)
- Handle same-bar stop+entry conflict: stop always wins (no re-entry on the same bar that stopped out)
- Full test suite covering price sequence generation, stop checking, entry filtering, and simulator integration

## Capabilities

### New Capabilities
- `bar-simulator`: Intra-bar price simulation that resolves stop and entry conditions against a reconstructed OHLC price path, with configurable slippage, entry modes, and high/low ordering

### Modified Capabilities
_(none — BarSimulator is a standalone module consumed by the existing BacktestRunner/FillModel layer; no spec-level changes to existing capabilities)_

## Impact

- **New module**: `src/bar_simulator/` (models, price_sequence, stop_checker, entry_checker, simulator)
- **Downstream consumer**: `BacktestRunner` and any future fill model can delegate stop/entry resolution to `BarSimulator`
- **No breaking changes**: Existing `FillModel`, `PositionEngine`, and `BacktestRunner` interfaces remain unchanged
- **Dependencies**: None beyond stdlib + numpy/pandas (already in stack)
- **Testing**: New `tests/` subdirectory under `bar_simulator/` with pytest cases
