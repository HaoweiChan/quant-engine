## Context

Our internal gap analysis (docs/critics-gemini.md) identified five structural deficiencies. This is **Phase A** — the highest-priority fix: replacing the naive fill simulation and adding an order management layer. The `ClosePriceFillModel` assumes fills at exact close price with zero market impact, inflating backtest PnL by an estimated 3-5x.

Current fill model stack:
- `ClosePriceFillModel`: fills at `bar["close"] ± fixed_slippage` — pure fantasy for any meaningful size
- `OpenPriceFillModel`: fills at `bar["open"] ± fixed_slippage` — same problem
- No spread-crossing cost, no volume participation awareness, no latency simulation
- `BacktestRunner` defaults to `ClosePriceFillModel()` when no model specified

Position Engine emits `Order` objects directly to Execution Engine with no execution optimization layer.

## Goals / Non-Goals

**Goals:**
- Replace naive fill models with volume-aware market-impact simulation (hard-cut, no legacy)
- Build auto-calibrating impact model (starts with academic TAIFEX parameters, learns from live fills)
- Add OMS slicing layer (TWAP/VWAP/POV) for large orders
- Add pre-trade risk gate to Position Engine
- Produce impact analysis reports showing naive vs. realistic PnL

**Non-Goals:**
- PIT data layer / contract stitching (Phase B — separate change)
- Portfolio-level VaR / factor exposure (Phase C — separate change)
- Event-driven simulator / audit trail (Phase D — separate change)
- L3 order book simulation (uses L1-estimated impact)
- Dashboard changes (API-first, frontend follows in later change)

## Decisions

### D1: Square-Root Impact Model with Auto-Calibration

**Decision**: Use the square-root impact model as primary (`impact = k × σ × √(Q/V)`). Start with published academic parameters for TAIFEX futures. Build an auto-calibration pipeline that updates `k` from live fill data over time.

```
Impact Estimation Pipeline:
  Academic k₀ ──► Live Fill Comparison ──► Updated k
                      │
              actual_impact = fill_price - mid_price_at_signal
              predicted_impact = k × σ × √(Q/V)
              k_new = EMA(actual / predicted, α=0.1) × k_old
```

**Rationale**: Academic estimates are a solid starting point but every market has idiosyncrasies. TAIFEX TX has specific liquidity patterns (thin around lunch break, thick at open/close). Auto-calibration converges on the real `k` after ~100 fills. The EMA smoother prevents overfitting to individual fills.

**Alternatives considered**:
- Fixed academic parameters only: ignores TAIFEX-specific microstructure
- Full Almgren-Chriss: requires permanent/temporary impact decomposition we can't estimate without L2 data
- Manual TOML tuning: doesn't scale and requires expertise to maintain

### D2: Hard-Cut Legacy Fill Models

**Decision**: Remove `ClosePriceFillModel` and `OpenPriceFillModel` entirely. No `legacy_mode`, no deprecation warnings — just delete them.

**Rationale**: Gemini's criticism is correct: "Halt all parameter optimization. You are currently overfitting to a flawed execution simulator." Keeping legacy models available means someone will use them and believe the results. A hard cut forces the team to confront reality immediately. All existing optimization results are suspect and must be re-run.

**Alternatives considered**:
- Soft deprecation with warnings: people ignore warnings
- Legacy mode flag: creates two code paths that must be maintained

### D3: OMS Target-Position Model

**Decision**: Position Engine emits `Order` objects (unchanged API). OMS wraps them with execution scheduling. Small orders (<1% ADV) pass through unmodified. Large orders are sliced.

```
Position Engine  ──[Order]──►  OMS  ──[SlicedOrder]──►  Execution Engine
                                │
                         ImpactModel.estimate_impact()
                         VolumeProfile (intraday)
                         Algorithm: auto-select
                           └─ urgent → TWAP
                           └─ size > 5% ADV → VWAP
                           └─ high vol → POV
```

**Rationale**: This preserves the Position Engine's existing interface entirely. The OMS is a new module that intercepts orders. For backtesting, the OMS operates in "estimate mode" — it doesn't actually slice orders across time, but it does apply the impact model based on what the slicing would have achieved. For live trading, it actually schedules child orders.

### D4: Pre-Trade Risk Gate

**Decision**: Add an optional `PreTradeRiskCheck` to Position Engine that evaluates entry and add-position orders before they're emitted. Stop-loss and circuit-breaker orders always bypass (risk-reducing orders must execute).

**Rationale**: This is a lightweight version of the full portfolio risk engine (Phase C). For Phase A, it enforces basic limits: max gross exposure, max ADV participation per order. When Phase C lands, the `PreTradeRiskCheck` gains VaR and factor exposure checks.

### D5: Latency Simulation at Bar Level

**Decision**: Add configurable latency delay (5-50ms uniform random) to the fill model. For daily bars, this is modeled as a price interpolation between open and close. Deterministic via seed for reproducible backtests.

**Rationale**: Real trading has latency. For daily bar backtests the effect is small but structurally important — it forces the architecture to handle the asynchronous signal → fill relationship correctly from day one.

## Risks / Trade-offs

**[Risk: All existing backtest results invalidated]** → This is intentional. Document the PnL delta in an impact report. Expected: 3-5x PnL reduction.

**[Risk: Impact model calibration requires live fills]** → **Mitigation**: Start with academic `k=1.0` for TAIFEX. Auto-calibration activates after first 50 live fills. Until then, academic parameters are conservative enough.

**[Risk: OMS adds complexity to pipeline]** → **Mitigation**: OMS has `enabled: bool` config. When disabled, all orders pass through unmodified. Default is enabled.

**[Risk: Partial fills create incomplete position states]** → **Mitigation**: Partial fills in backtest are tracked but don't create new positions until the full order is filled (aggregate child fills).

## Open Questions

None — all critical questions resolved by user input.
