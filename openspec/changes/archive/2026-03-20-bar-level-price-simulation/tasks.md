## 1. Module Setup

- [x] 1.1 Create `src/bar_simulator/` package with `__init__.py` exposing public API (`BarSimulator`, all dataclasses, helper functions)
- [x] 1.2 Create `src/bar_simulator/models.py` with `OHLCBar`, `StopLevel`, `StopTriggerResult`, `EntryFillResult`, `BarSimResult` dataclasses. Acceptance: all models importable, mypy passes, `OHLCBar` has timestamp/open/high/low/close/volume fields

## 2. Price Sequence Generation

- [x] 2.1 Implement `intra_bar_price_sequence(bar, high_low_order)` in `src/bar_simulator/price_sequence.py`. Rules: open first, close last, open-proximity ordering for high/low, consecutive dedup. Support `"open_proximity"` / `"always_up"` / `"always_down"` modes. Acceptance: TC-PS-01 through TC-PS-04 pass
- [x] 2.2 Create `src/bar_simulator/tests/test_price_sequence.py` with tests: open near high (up first), open near low (down first), equidistant (default up), doji bar (single element), always_up/always_down overrides. Acceptance: all tests green

## 3. Stop Condition Checker

- [x] 3.1 Implement `check_stops_intra_bar(bar, stops, slippage, high_low_order)` in `src/bar_simulator/stop_checker.py`. Walk price sequence, check each price against all stops, return first triggered stop with fill price (stop.price ± slippage). Acceptance: TC-SC-01 through TC-SC-03 pass
- [x] 3.2 Create `src/bar_simulator/tests/test_stop_checker.py` with tests: long stop triggered (correct fill price with slippage), stop not triggered (low above stop), multiple stops first-one-wins, short stop ("above" direction), empty stops list. Acceptance: all tests green

## 4. Entry Fill Checker

- [x] 4.1 Implement `check_entry_intra_bar(signal_bar, entry_mode, slippage, next_bar, limit_price, direction)` in `src/bar_simulator/entry_checker.py`. Modes: `"bar_close"` fills at close±slippage, `"next_open"` fills at next_bar.open±slippage. Limit orders check price reachability. ValueError if next_open + no next_bar. Acceptance: TC-EN-01 passes
- [x] 4.2 Create `src/bar_simulator/tests/test_entry_checker.py` with tests: bar_close market entry (fill at close+slippage), next_open market entry, next_open ValueError at end-of-data, bar_close limit fill, bar_close limit miss, short entry slippage direction. Acceptance: all tests green

## 5. BarSimulator Integration

- [x] 5.1 Implement `BarSimulator` class in `src/bar_simulator/simulator.py` with `__init__(slippage_points, entry_mode, high_low_order)` and `process_bar(bar, next_bar, stops, entry_signal, limit_price)`. Compose price_sequence + stop_checker + entry_checker, resolve same-bar stop+entry conflict (stop wins). Acceptance: TC-EN-02 passes
- [x] 5.2 Create `src/bar_simulator/tests/test_simulator.py` with tests: stop-only bar, entry-only bar, same-bar stop+entry (stop_before_entry=True, entry cancelled), no stops no entry, price_sequence included in result. Acceptance: all tests green

## 6. Documentation

- [x] 6.1 Create `src/bar_simulator/USAGE.md` showing a minimal 10-bar backtest loop using `BarSimulator`, demonstrating stop checking, entry filling, and position lifecycle. Acceptance: code example is copy-pasteable and syntactically valid

## 7. Validation

- [x] 7.1 Run full test suite (`pytest src/bar_simulator/tests/`), verify all tests pass, run `ruff check` and `mypy --strict` on `src/bar_simulator/`. Acceptance: zero errors from pytest, ruff, and mypy
