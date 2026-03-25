## 1. Core Types

- [ ] 1.1 Add `VaRResult` dataclass with `var_99_1d`, `var_95_1d`, `var_99_10d`, `var_95_10d`, `expected_shortfall_99`, `position_var`, `correlation_matrix`, `timestamp`. Acceptance: importable, mypy clean.
- [ ] 1.2 Extend `PreTradeRiskConfig` (from Phase A) with `max_beta_absolute`, `max_concentration_pct`, `max_var_pct` fields. Acceptance: backward compatible defaults.
- [ ] 1.3 Extend `RiskConfig` with `max_var_pct`, `max_beta_absolute`, `max_concentration_pct`, `portfolio_risk_enabled` fields. Acceptance: `portfolio_risk_enabled=False` by default.

## 2. VaR Engine

- [ ] 2.1 Create `src/risk/var_engine.py` with `VaREngine` class implementing `compute()` — parametric VaR at 99%/95% for 1-day and 10-day horizons. Acceptance: single-instrument VaR matches `pos × σ/√252 × z`.
- [ ] 2.2 Implement 10-day VaR scaling: `var_10d = var_1d × √10`. Acceptance: correct for known inputs.
- [ ] 2.3 Implement `compute_incremental()` — marginal VaR from adding an order. Acceptance: incremental VaR computed without full matrix recalculation.
- [ ] 2.4 Implement conservative fallback when <30 returns: use `2 × ATR-based volatility`. Acceptance: fallback triggers, warning flag set.
- [ ] 2.5 Implement Historical VaR daily batch computation. Acceptance: HVaR from actual return percentile.
- [ ] 2.6 Implement divergence alerting — alert when HVaR differs from parametric by >30%. Acceptance: alert emitted via alerting pipeline.
- [ ] 2.7 Write tests: parametric accuracy, 10-day scaling, incremental, fallback, HVaR crosscheck, divergence alert. Acceptance: all tests green.

## 3. Portfolio Risk Engine

- [ ] 3.1 Create `src/risk/portfolio.py` with `PortfolioRiskEngine` wrapping `VaREngine` + factor tracking. Acceptance: `get_risk_summary()` returns VaR + beta + concentration.
- [ ] 3.2 Enhance `PreTradeRiskCheck.evaluate()` to include VaR limit, beta limit, and concentration limit checks. Acceptance: all violation codes returned correctly.
- [ ] 3.3 Implement beta tracking — portfolio beta vs benchmark (TAIEX for TAIFEX). Acceptance: single TX futures position → beta ≈ 1.0.
- [ ] 3.4 Implement margin stress testing: margin doubling, volatility spike (3×), correlation breakdown. Acceptance: each scenario reports margin-call risk.
- [ ] 3.5 Write tests: pre-trade limits (all violation types), beta computation, stress scenarios. Acceptance: all tests green.

## 4. Risk Monitor Extension

- [ ] 4.1 Add `portfolio_risk: PortfolioRiskEngine | None` to `RiskMonitor.__init__()`. Acceptance: backward compatible when None.
- [ ] 4.2 Add VaR check at priority 4.5 in `check()`. Acceptance: VaR breach → HALT_NEW_ENTRIES.
- [ ] 4.3 Add beta check and concentration check to `check()`. Acceptance: breaches → HALT_NEW_ENTRIES.
- [ ] 4.4 Enrich risk event logging with VaR, beta, concentration when portfolio risk available. Acceptance: enriched details in log output.
- [ ] 4.5 Write tests: VaR check triggers, beta check, concentration check, portfolio risk disabled by default. Acceptance: all tests green.

## 5. Integration

- [ ] 5.1 Wire `PortfolioRiskEngine` into `RiskMonitor` in pipeline runner. Acceptance: risk checks include portfolio risk when enabled.
- [ ] 5.2 Integration test: position exceeding VaR limit → entry halted by Risk Monitor. Acceptance: test green.
