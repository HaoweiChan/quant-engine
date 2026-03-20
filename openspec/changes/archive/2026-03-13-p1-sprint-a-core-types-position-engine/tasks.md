## 1. Project Scaffold

- [x] 1.1 Initialize project with `pyproject.toml` (Python 3.12+, uv, ruff, mypy strict, pytest) — verify `uv sync` and `pytest` run cleanly
- [x] 1.2 Create package structure: `quant_engine/core/__init__.py`, `quant_engine/core/types.py`, `quant_engine/core/adapter.py`, `quant_engine/core/position_engine.py`
- [x] 1.3 Create test structure: `tests/conftest.py`, `tests/test_types.py`, `tests/test_position_engine.py`

## 2. Core Types (`quant_engine/core/types.py`)

- [x] 2.1 Implement `ContractSpecs` dataclass with validation: positive margins, non-empty lot_types — acceptance: `ValueError` raised on invalid margins
- [x] 2.2 Implement `MarketSnapshot` dataclass with validation: positive price, `"daily"` key required in `atr` — acceptance: `ValueError` on zero/negative price or missing daily ATR
- [x] 2.3 Implement `MarketSignal` dataclass with validation: direction in [-1,1], direction_conf in [0,1], regime in allowed set — acceptance: `ValueError` on out-of-range values
- [x] 2.4 Implement `Order` dataclass with validation: positive lots, stop_price required for stop orders, price is None for market orders — acceptance: `ValueError` on invalid combinations
- [x] 2.5 Implement `Position` dataclass with fields: entry_price, lots, contract_type, stop_level, pyramid_level, entry_timestamp — acceptance: `ValueError` on None stop_level
- [x] 2.6 Implement `EngineState` dataclass with fields: positions, pyramid_level, mode, total_unrealized_pnl — acceptance: read-only snapshot constructable from engine internals
- [x] 2.7 Implement `AccountState` dataclass with validation: drawdown_pct in [0,1] — acceptance: `ValueError` on out-of-range drawdown
- [x] 2.8 Implement `PyramidConfig` dataclass with validation: lot_schedule length == max_levels, add_trigger_atr length == max_levels-1, max_loss must be positive and explicitly provided — acceptance: `ValueError` on inconsistencies
- [x] 2.9 Implement `RiskAction` enum with members: NORMAL, REDUCE_HALF, HALT_NEW_ENTRIES, CLOSE_ALL — acceptance: exactly 4 members

## 3. Base Adapter (`quant_engine/core/adapter.py`)

- [x] 3.1 Implement `BaseAdapter` ABC with abstract methods: `to_snapshot()`, `calc_margin()`, `calc_liquidation_price()`, `get_trading_hours()`, `get_contract_specs()`, `estimate_fee()`, `translate_lots()` — acceptance: cannot instantiate directly, subclass must implement all methods

## 4. Position Engine (`quant_engine/core/position_engine.py`)

- [x] 4.1 Implement `PositionEngine.__init__(config: PyramidConfig)` with internal state: positions list, pyramid_level, mode, highest_high tracker — acceptance: engine starts flat with mode `"model_assisted"`
- [x] 4.2 Implement `on_snapshot()` orchestration with correct priority order: stop-loss → trailing stop update → margin safety → entry signal → add-position → circuit breaker — acceptance: each step is a separate private method called in order
- [x] 4.3 Implement entry logic: enter when flat + signal.direction_conf > threshold, with lot sizing from lot_schedule[0] and initial stop at entry - stop_atr_mult × daily_atr — acceptance: order generated only when confidence exceeds threshold
- [x] 4.4 Implement pre-entry risk validation: scale down lots if max-loss-if-stopped exceeds config.max_loss, skip entry if even 1 lot exceeds limit — acceptance: lot count reduced or entry skipped
- [x] 4.5 Implement pyramid add-position: trigger when floating profit ≥ add_trigger_atr[N-1] × daily_atr, use lot_schedule[N], move all existing stops to breakeven — acceptance: adds at correct ATR multiples, stops move up
- [x] 4.6 Implement margin headroom check: skip add if margin_ratio would exceed margin_limit × 0.8 — acceptance: add skipped when margin tight
- [x] 4.7 Implement Layer 1 stop: initial fixed stop at entry - stop_atr_mult × ATR — acceptance: stop set correctly at entry time
- [x] 4.8 Implement Layer 2 stop: move to breakeven when floating profit > 1 × ATR — acceptance: stop moves to entry price
- [x] 4.9 Implement Layer 3 stop: Chandelier Exit trailing stop = highest_high(trail_lookback) - trail_atr_mult × ATR, only moves up — acceptance: stop ratchets upward, never down
- [x] 4.10 Implement stop trigger: if price ≤ stop_level → generate close order with correct reason — acceptance: close order emitted with "stop_loss" or "trailing_stop" reason
- [x] 4.11 Implement margin safety: if margin_ratio > margin_limit → generate reduce orders — acceptance: reduce orders emitted when margin breached
- [x] 4.12 Implement circuit breaker: if drawdown ≥ max_loss → close all + set mode=halted — acceptance: all positions closed, mode transitions to halted
- [x] 4.13 Implement mode switching: model_assisted (use signals), rule_only (ignore signals, fixed params), halted (no new entries, stops still active) — acceptance: each mode behaves as specified
- [x] 4.14 Implement `set_mode()` and `get_state()` — acceptance: mode changes immediately, state snapshot is read-only

## 5. Tests (`tests/`)

- [x] 5.1 Test fixtures in conftest.py: helper functions to build synthetic MarketSnapshot sequences, valid MarketSignal, default PyramidConfig — acceptance: all fixtures usable across test files
- [x] 5.2 Type validation tests: verify ValueError for every invalid construction scenario (bad price, bad direction range, bad regime, invalid lots, missing stop_price, etc.) — acceptance: all validation paths covered
- [x] 5.3 Test entry logic: flat engine + strong signal → order generated; flat + weak signal → no order — acceptance: threshold boundary verified
- [x] 5.4 Test pre-entry risk scaling: max_loss constraint scales lots down or skips entry — acceptance: lot count matches expectation
- [x] 5.5 Test pyramid adds: price rises through ATR thresholds → add orders at correct levels — acceptance: each level triggers at correct profit threshold
- [x] 5.6 Test stops only move upward: supply sequence where trailing stop would decrease → verify stop unchanged — acceptance: stop never decreases
- [x] 5.7 Test breakeven stop activation: floating profit crosses 1× ATR → stop moves to entry — acceptance: exact trigger point verified
- [x] 5.8 Test circuit breaker: drawdown hits max_loss → close-all orders + mode=halted — acceptance: transition at exact threshold
- [x] 5.9 Test rule_only mode: same stop behavior, no signal-dependent entries — acceptance: signal ignored, stops still active
- [x] 5.10 Test halted mode: no new entries, existing stops still trigger — acceptance: entry blocked, stop still fires
- [x] 5.11 Test margin safety: margin_ratio > limit → reduce orders generated — acceptance: reduce order quantities are sensible
- [x] 5.12 Test lot scaling respects max_loss constraint — acceptance: position size bounded by max_loss / (stop_distance × point_value)

## 6. Quality Gates

- [x] 6.1 `ruff check` passes with zero errors — acceptance: clean lint
- [x] 6.2 `mypy --strict` passes with zero errors — acceptance: full type coverage
- [x] 6.3 All pytest tests pass — acceptance: 100% pass rate
