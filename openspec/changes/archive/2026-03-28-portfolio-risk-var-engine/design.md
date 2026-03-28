## Context

The Risk Monitor (`src/risk/monitor.py`) currently checks: drawdown circuit breaker, feed staleness, spread spikes, signal staleness, and margin ratio. These are operational risk controls — they detect infrastructure/market anomalies. Portfolio risk (how much is at risk given position sizes, correlations, and factor exposures) is completely missing.

Phase A added a basic `PreTradeRiskCheck` to the Position Engine that enforces max gross exposure and ADV participation. Phase C upgrades this to a full portfolio risk engine with VaR, factor exposure, and stress testing.

## Goals / Non-Goals

**Goals:**
- Parametric VaR (variance-covariance) for real-time pre-trade checks
- Both 1-day (real-time) and 10-day (reporting) horizons
- Historical VaR as daily crosscheck with divergence alerting
- Incremental VaR for per-order impact assessment
- Factor exposure tracking (beta vs benchmark)
- Margin stress testing (doubling, vol spike, correlation breakdown)
- Extend Risk Monitor with portfolio risk checks

**Non-Goals:**
- Monte Carlo VaR (too slow for real-time pre-trade)
- Multi-factor risk model (Barra-style, deferred to Phase 5+)
- Options Greeks (no options in scope)
- Real-time P&L attribution

## Decisions

### D1: Parametric VaR (Primary) + Historical VaR (Crosscheck)

**Decision**: Use variance-covariance VaR for real-time checks (O(1) matrix multiplication). Run Historical VaR as a daily batch to catch fat-tail divergence. Alert when the two differ by >30%.

**Rationale**: Parametric VaR assumes normality — fine for quick pre-trade gates but underestimates tail risk. Historical VaR uses actual return distribution but is too slow per-order. Running both gives speed + accuracy.

### D2: Dual Horizon — 1-Day Real-Time + 10-Day Reporting

**Decision**: Pre-trade gates use 1-day VaR (matches daily rebalancing cadence). Reporting dashboard shows 10-day VaR (aligns with Basel III standard for capital adequacy).

**Rationale**: User specified "both" — 1-day for operational use, 10-day for institutional reporting. 10-day VaR ≈ √10 × 1-day VaR under parametric assumptions.

### D3: Single-Instrument Degenerate Case

**Decision**: For TAIFEX Phase 1 (single instrument), VaR simplifies to `position_value × σ/√252 × z_score`. The general multi-instrument infrastructure is built but the single-instrument case naturally falls out without special-casing.

**Rationale**: Build correctly for multi-asset from the start. When Phase 4 (US equities) lands, the VaR engine works without modification.

### D4: Risk Monitor Priority Ordering

**Decision**: Portfolio risk checks slot between existing operational checks:
1. Drawdown circuit breaker (CLOSE_ALL)
2. Feed staleness (HALT)
3. Spread spike (HALT)
4. **VaR limit breach (HALT)** — new
5. Signal staleness (degrade to rule_only)
6. **Beta/factor breach (HALT)** — new
7. **Concentration breach (HALT)** — new
8. Margin ratio (REDUCE_HALF)

**Rationale**: VaR is a "position is too risky" signal — more urgent than signal staleness but less urgent than market infrastructure failures.

## Risks / Trade-offs

**[Risk: VaR underestimates tail risk]** → Historical VaR crosscheck catches this. Alert when parametric/historical diverge >30%.

**[Risk: Single-instrument VaR is trivially σ × z × size]** → Over-engineered for now. But the infrastructure is correct for multi-asset expansion.

**[Risk: Beta estimation for TAIFEX TX vs TAIEX]** → For a single futures contract on the index, beta ≈ 1.0 by construction. Factor tracking becomes meaningful when US equities are added.
