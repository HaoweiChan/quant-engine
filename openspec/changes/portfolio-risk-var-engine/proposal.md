## Why

Gap analysis (docs/critics-gemini.md) identified that while the Risk Monitor handles operational risk (feed staleness, spread spikes, drawdown circuit breakers), portfolio-level risk is completely absent. There is no VaR calculation, no correlation matrix, no factor exposure limits. The engine could inadvertently concentrate 100% of margin on a single systemic macro factor. This is Phase C of the institutional-grade upgrade, building on Phase A (realistic fills) and Phase B (PIT data).

## What Changes

- **Add portfolio-level risk engine** with parametric VaR (99%, variance-covariance) for real-time pre-trade checks and Historical VaR as daily crosscheck
- **Implement both 1-day and 10-day VaR horizons**: 1-day for real-time pre-trade gating, 10-day for reporting
- **Add pre-trade risk matrix**: max gross exposure, max ADV participation, beta limit, concentration limit, VaR limit — all configurable
- **Extend Risk Monitor** with VaR-based, factor exposure, and concentration checks at new priority levels
- **Add margin stress testing**: margin doubling, volatility spike (3×), correlation breakdown scenarios
- **Track portfolio beta** relative to benchmark (TAIEX for Phase 1)
- **Enrich risk events** with portfolio metrics when available

## Capabilities

### New Capabilities
- `portfolio-risk-engine`: Pre-trade risk matrix, parametric VaR (99%/95%, 1-day and 10-day), incremental VaR, Historical VaR crosscheck, margin stress testing, factor exposure tracking

### Modified Capabilities
- `risk-monitor`: Extended with VaR, beta, and concentration checks; enriched risk event logging; new config fields for portfolio thresholds
- `position-engine`: Pre-trade risk gate (from Phase A) enhanced with VaR and factor limits

## Impact

- **Core modules**: `src/risk/monitor.py`, `src/core/position_engine.py`
- **New modules**: `src/risk/portfolio.py`, `src/risk/var_engine.py`
- **Types**: `VaRResult`, extended `RiskConfig`, extended `PreTradeRiskConfig`
- **Dependencies**: `numpy` (already available) for variance-covariance computation
- **API**: New REST endpoints for VaR dashboard, stress test results
- **Tests**: VaR accuracy tests, stress scenario tests, integration with Risk Monitor
