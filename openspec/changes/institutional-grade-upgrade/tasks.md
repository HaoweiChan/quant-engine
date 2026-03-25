## 1. Core Types & Fill Dataclass Extension

- [x] 1.1 Extend `Fill` dataclass in `src/simulator/types.py` with `market_impact`, `spread_cost`, `latency_ms`, `fill_qty`, `remaining_qty`, `is_partial` fields (default 0/False). Acceptance: mypy clean, existing tests pass.
- [x] 1.2 Add `ImpactParams`, `OMSConfig`, `PreTradeRiskConfig`, `PreTradeResult`, `SlicedOrder`, `ChildOrder` dataclasses to `src/core/types.py`. Acceptance: all types instantiable with defaults, validation on construction.

## 2. Market Impact Fill Model

- [x] 2.1 Implement `MarketImpactFillModel` in `src/simulator/fill_model.py` with square-root impact formula `impact = k × σ × √(Q/V)`. Acceptance: `estimate_impact()` returns correct values for known inputs (e.g., Q=10, V=50000, σ=0.015).
- [x] 2.2 Add spread-crossing cost — half-spread from `bar["spread"]` or fallback `params.spread_bps × close / 10000`. Acceptance: buy fills higher than mid, sell fills lower.
- [x] 2.3 Add latency delay simulation with `[min_latency_ms, max_latency_ms]` uniform random, deterministic with seed. Acceptance: same seed → identical fill sequences.
- [x] 2.4 Add partial fill logic — reject when `bar["volume"]` is 0 (`fill_qty=0, reason="no_liquidity"`), partial fill when order exceeds `max_adv_participation × volume`. Acceptance: zero-volume bar rejected, oversized order partially filled.
- [x] 2.5 Delete `ClosePriceFillModel` and `OpenPriceFillModel` classes entirely from `src/simulator/fill_model.py`. Update all imports. Acceptance: no references to removed classes anywhere in codebase.
- [x] 2.6 Change `BacktestRunner.__init__()` default from `ClosePriceFillModel()` to `MarketImpactFillModel()`. Acceptance: `BacktestRunner()` without fill_model arg uses impact model.
- [x] 2.7 Build auto-calibration tracker in `src/simulator/fill_model.py` — `ImpactCalibrator` class that records (predicted_impact, actual_impact) pairs and updates `k` via EMA. Acceptance: `k` converges toward 1.0 when actual matches predicted.
- [x] 2.8 Write tests: impact scaling with order size, impact scaling with volatility, spread direction, latency determinism, partial fills, zero-volume rejection, calibrator convergence. Acceptance: all tests green, >95% coverage on fill_model.py.

## 3. Order Management System

- [x] 3.1 Create `src/oms/__init__.py` and `src/oms/oms.py` with `OrderManagementSystem` class, `schedule()` method, `is_passthrough()` logic. Acceptance: small orders (<1% ADV) pass through, large orders sliced.
- [x] 3.2 Implement TWAP algorithm — evenly distribute lots across `n_slices` time windows. Acceptance: 100 lots / 10 slices = 10 child orders of 10 lots.
- [x] 3.3 Implement VWAP algorithm — distribute lots proportional to `VolumeProfile`. Falls back to TWAP when no profile available. Acceptance: child sizes match volume profile ratios.
- [x] 3.4 Implement POV algorithm — cap each child order at `participation_rate × bar_volume`. Acceptance: no child exceeds configured rate.
- [x] 3.5 Implement auto-selection: urgent (stops) → passthrough, size > 5% ADV → VWAP, high vol → POV, default → TWAP. Acceptance: correct algorithm per condition.
- [x] 3.6 Add `VolumeProfile` data structure and loader from historical OHLCV data. Acceptance: returns normalized intraday volume distribution.
- [x] 3.7 Add `OMSConfig` loading from TOML with `enabled: bool` toggle. When disabled, all orders pass through. Acceptance: disabled OMS = no behavior change.
- [x] 3.8 Write tests: passthrough threshold, TWAP/VWAP/POV correctness, auto-selection logic, disabled mode. Acceptance: all tests green.

## 4. Position Engine Pre-Trade Risk Gate

- [x] 4.1 Add `pre_trade_check: PreTradeRiskCheck | None = None` to `PositionEngine.__init__()`. Acceptance: existing construction works without it (backward compatible).
- [x] 4.2 Implement `PreTradeRiskCheck.evaluate()` in `src/risk/pre_trade.py` — checks max gross exposure and max ADV participation. Acceptance: orders exceeding limits rejected with correct violation codes.
- [x] 4.3 Wire pre-trade evaluation in `on_snapshot()` between margin safety and entry/add logic. Stop-loss, trailing-stop, margin-safety, and circuit-breaker orders bypass. Acceptance: risk-reducing orders always pass.
- [x] 4.4 Add `urgency` ("immediate" for stops, "normal" for entry/add) and `estimated_adv` metadata to all generated orders. Acceptance: all orders have metadata fields.
- [x] 4.5 Update `create_pyramid_engine()` factory to accept optional `pre_trade_check` param. Acceptance: factory works with and without it.
- [x] 4.6 Write tests: pre-trade rejection suppresses entry, stop orders bypass, None check backward compatible, metadata populated. Acceptance: all tests green.

## 5. Execution Engine OMS Integration

- [x] 5.1 Add parent-child order relationship tracking to `ExecutionEngine` — aggregate fill stats at parent order level. Acceptance: parent VWAP fill price computed from child fills.
- [x] 5.2 Add actual impact reporting — compute `actual_impact = fill_price - mid_price` after each live fill and feed back to `ImpactCalibrator`. Acceptance: calibrator receives actual impact data.
- [x] 5.3 Extend `get_fill_stats()` with `predicted_impact_accuracy` (correlation) and `oms_algorithm_performance` (per-algorithm fill quality). Acceptance: stats dict includes new fields.
- [x] 5.4 Write tests: child order aggregation, impact feedback loop, extended stats. Acceptance: all tests green.

## 6. Simulator Impact Analysis Report

- [x] 6.1 Add `impact_report` dict to `BacktestResult` — `naive_pnl` (no impact estimate), `realistic_pnl`, `pnl_ratio`, `per_trade_impact_breakdown`. Acceptance: report populated after each backtest.
- [x] 6.2 Extend `BacktestResult.metrics` with `total_market_impact`, `total_spread_cost`, `avg_latency_ms`, `partial_fill_count`. Acceptance: new metrics populated, existing metrics unchanged.
- [x] 6.3 Update MCP facade functions to include impact metrics in response dicts. Acceptance: MCP backtest results include impact breakdown.
- [x] 6.4 Update Monte Carlo and stress test runners to use `MarketImpactFillModel` by default. Acceptance: MC/stress results reflect realistic execution costs.
- [x] 6.5 Write tests: impact report accuracy, naive-vs-realistic comparison, metrics completeness. Acceptance: all tests green.

## 7. Pipeline Wiring & Integration

- [x] 7.1 Wire OMS into pipeline: `PositionEngine → OMS → ExecutionEngine` in `src/pipeline/runner.py`. Acceptance: full pipeline runs end-to-end with OMS.
- [x] 7.2 Run all existing backtest presets with new fill model, document PnL delta in `docs/migration-impact-report.md`. Acceptance: report shows before/after metrics for all 7 presets.
- [x] 7.3 End-to-end integration test: bar data → PositionEngine (with pre-trade gate) → OMS → MarketImpactFillModel → verify fills have impact/spread/latency populated. Acceptance: single test exercises entire Phase A stack.
- [x] 7.4 Fix any broken imports from `ClosePriceFillModel` removal across tests and facades. Acceptance: `ruff check`, `mypy`, `pytest` all pass clean.
