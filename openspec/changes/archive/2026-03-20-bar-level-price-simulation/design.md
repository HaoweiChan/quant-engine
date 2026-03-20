## Context

The `BacktestRunner` currently feeds OHLC bars through `PositionEngine.on_snapshot()` using the bar's close (or open) price as the single reference price. Stop-loss conditions are only checked against that single price, and entry signals can fill on the same bar that generated them. This creates two well-known backtest artifacts:

1. A bar whose low pierces a stop level but closes above it never triggers the stop — the backtest misses a real loss event.
2. An entry signal derived from bar N's OHLC data can fill at bar N's open, using information not available at that price.

The existing `FillModel` abstraction (`ClosePriceFillModel`, `OpenPriceFillModel`) handles slippage on fills but has no concept of intra-bar price traversal.

```
Current flow:
  bar → FillModel.simulate(order, bar) → Fill(price=close±slip)

Proposed flow:
  bar → BarSimulator.process_bar(bar, stops, entry_signal)
        ├─ intra_bar_price_sequence(bar)  → [O, H, L, C] path
        ├─ check_stops_intra_bar(path, stops)  → StopTriggerResult
        ├─ check_entry_intra_bar(bar, mode)    → EntryFillResult
        └─ resolve same-bar conflict           → BarSimResult
```

## Goals / Non-Goals

**Goals:**
- Reconstruct a conservative intra-bar price path from OHLC data
- Detect stop-loss triggers that occur within a bar (not just at close)
- Prevent look-ahead bias on entry signals (fill at close or next open, never same-bar open)
- Resolve same-bar stop+entry conflicts (stop wins, no re-entry)
- Provide a standalone module that `BacktestRunner` can adopt without modifying `PositionEngine`

**Non-Goals:**
- Modifying `PositionEngine` or pyramid logic (separate module, unchanged interface)
- Simulating order book depth or tick-by-tick data
- Computing ATR (injected from outside)
- Broker connectivity or live execution
- Adding dependencies beyond numpy/pandas

## Decisions

### D1: Module placement — `src/bar_simulator/` as standalone package

**Decision:** Create `src/bar_simulator/` as an independent package with its own models, not integrated into `src/simulator/`.

**Rationale:** The bar simulator is a pure computation layer with no dependency on `PositionEngine`, `FillModel`, or any broker adapter. Keeping it standalone means:
- It can be unit-tested in isolation
- `BacktestRunner` can optionally use it (not forced)
- Future fill models can compose it without circular imports

**Alternative considered:** Extending `FillModel` with intra-bar logic. Rejected because `FillModel.simulate()` takes a single order and returns a fill — it has no concept of "check all stops against a price path before deciding on entries."

### D2: Price path ordering — open proximity heuristic

**Decision:** Use the open-proximity rule to determine whether the bar visited high or low first: if open is closer to high (or tied), go `[O, H, L, C]`; otherwise `[O, L, H, C]`.

**Rationale:** Without tick data, we cannot know the true intra-bar path. The open-proximity heuristic is the most commonly used conservative assumption (used by XQ, AmiBroker, and others). It tends to be adversarial for trend-following strategies (tests the stop before rewarding the trend), which is the right bias for backtesting.

**Alternative considered:**
- `always_up` / `always_down` — useful for sensitivity analysis, supported as config option
- Random ordering — adds noise without improving accuracy

### D3: Entry fill timing — bar_close default, next_open optional

**Decision:** Default entry mode is `bar_close` (fill at signal bar's close). Optional `next_open` mode fills at the next bar's open.

**Rationale:** Filling at close avoids look-ahead on the signal bar's open (which was already known when the bar started) while still allowing same-bar execution. The `next_open` mode is more conservative and useful for strategies where execution latency is a concern.

### D4: Stop fill price — stop level minus slippage (conservative)

**Decision:** When a stop triggers, fill price = `stop_level ± slippage_points` (adverse direction). Default slippage: 2 points for TX.

**Rationale:** Real stop-market orders rarely fill exactly at the stop level. Using a fixed adverse slippage is conservative and predictable. More sophisticated models (proportional to spread, vol-adjusted) can be added later without changing the interface.

### D5: Same-bar conflict resolution — stop always wins

**Decision:** If both a stop trigger and an entry signal occur on the same bar, the stop executes and the entry is cancelled.

**Rationale:** In the intra-bar price sequence, the stop triggers at some `sequence[i]` where `i < len(sequence) - 1`, while the entry can only fill at close (`sequence[-1]`). The stop therefore happens "first" in simulated time. Allowing re-entry on the same bar that stopped out creates an unrealistic pathological trade.

## Risks / Trade-offs

**[Risk] Open-proximity heuristic may not match actual intra-bar path** → Mitigation: The heuristic is conservative for long-biased strategies. Provide `high_low_order` config (`always_up`, `always_down`) so users can run sensitivity analysis. Future enhancement: use volume profile or 1-min sub-bars when available.

**[Risk] Fixed slippage may under/overestimate real execution** → Mitigation: `slippage_points` is configurable per-instrument. For TX futures (tight spread, liquid), 2 points is conservative. Adapter-specific defaults can be set by the caller.

**[Risk] 4-point price path is a rough approximation** → Mitigation: This is a known limitation of OHLC data. The 4-point path is the standard approach used by professional backtesting tools. If higher fidelity is needed, users should switch to tick or 1-min data (different code path, out of scope).

**[Risk] Entry `next_open` mode requires lookahead to next bar** → Mitigation: `BarSimulator.process_bar()` accepts `next_bar` as an explicit parameter. Raises `ValueError` at end-of-data. The caller (`BacktestRunner`) naturally has access to the next bar in its loop.
