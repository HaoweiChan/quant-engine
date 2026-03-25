## 1. Core Types & Schema

- [x] 1.1 Add `PITRecord`, `StitchedSeries` dataclasses to `src/core/types.py`. Acceptance: types importable, mypy clean.
- [x] 1.2 Add `knowledge_time`, `valid_from`, `valid_to` columns to margin snapshot table via migration in `src/data/db.py`. Acceptance: migration runs, existing queries unchanged.
- [x] 1.3 Create `contract_rolls` table with columns: `symbol`, `roll_date`, `old_contract`, `new_contract`, `adjustment_factor`. Acceptance: table created, CRUD works.

## 2. PIT Query Layer

- [x] 2.1 Create `src/data/pit.py` with `PITQuery` class implementing `as_of()`, `at_event()`, `range()` query builders. Acceptance: `AS_OF(T)` returns only data with `knowledge_time <= T`.
- [x] 2.2 Add `as_of` parameter to `Database.get_latest_margin()`. Acceptance: backtest margin queries at past date return past values; no arg = latest.
- [x] 2.3 Ensure retroactive corrections append new records (same `event_time`, later `knowledge_time`), never modify originals. Acceptance: original record untouched after correction.
- [x] 2.4 Write tests: AS_OF returns correct data, no look-ahead, retroactive correction, missing data returns None. Acceptance: all tests green.

## 3. Continuous Contract Stitching

- [x] 3.1 Create `src/data/stitcher.py` with `ContractStitcher` class implementing `stitch(symbol, method, start, end)`. Acceptance: returns `StitchedSeries`.
- [x] 3.2 Implement ratio-adjusted stitching — multiply historical prices by new/old ratio at roll points. Acceptance: percentage returns preserved across rolls.
- [x] 3.3 Implement Panama (additive) stitching. Acceptance: absolute differences preserved.
- [x] 3.4 Implement backward-adjusted stitching. Acceptance: recent prices unchanged.
- [x] 3.5 Implement roll date detection: volume crossover (2 consecutive days) + 3rd Wednesday calendar fallback. Acceptance: correct roll dates for historical TAIFEX data.
- [x] 3.6 Store per-contract OHLCV with both specific contract ID and generic symbol. Acceptance: `TX202604` and `TX` both queryable.
- [x] 3.7 Add `get_stitched_ohlcv()` and `get_adv()` methods to Database. Acceptance: stitched series and PIT-safe ADV queryable.
- [x] 3.8 Write tests: all three stitching methods, roll detection, ADV computation, unadjusted prices preserved. Acceptance: all tests green.

## 4. Adapter Integration

- [x] 4.1 Update `TaifexAdapter.get_contract_specs()` to accept optional `as_of` parameter, using PIT margin lookup. Acceptance: backtest uses past margins, live uses current.
- [x] 4.2 Update `TaifexAdapter.to_snapshot()` to pass `as_of` context when in backtest mode. Acceptance: snapshots during backtest use PIT-safe data.
- [x] 4.3 Write integration test: backtest with PIT-aware adapter at past date uses historical margins. Acceptance: test green.
