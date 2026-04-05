---
name: alpha-validation-protocol
description: "Distinguish simulated robustness (Monte Carlo) from real alpha (walk-forward backtests on historical data). Two-phase validation protocol with acceptance criteria."
license: MIT
metadata:
  author: quant-engine
  version: "1.0"
---

## The Cardinal Rule
**Monte Carlo / simulated path performance is NOT alpha.**
It is a robustness test of parameter sensitivity and risk characteristics.
A strategy claiming alpha MUST demonstrate it on real TAIFEX OHLCV data.

These are two completely different claims:
| Claim | Evidence Required |
|---|---|
| "The strategy parameters are not overfit" | Monte Carlo across scenarios |
| "The strategy has edge on TAIFEX" | Walk-forward backtest on real bars |

Confusing these is the most common — and most expensive — mistake in quant research.

---

## The Two-Phase Validation Protocol

### Phase 1: Simulation (MCP Server) — Parameter Stress Testing
**Purpose**: Eliminate fragile parameters. Not to claim alpha.
**Tools**: `run_monte_carlo`, `run_parameter_sweep`, `run_stress_test`
**Data**: Synthetic GBM + GARCH paths with TAIFEX microstructure calibration
**Output**: Robust parameter set that survives distributional stress

**Acceptance criteria for Phase 1:**
- MC P50 Sharpe ≥ 0.8 on `strong_bull`
- MC P50 Sharpe ≥ 0.4 on `sideways`
- Survives `flash_crash` without ruin (drawdown < 25%)
- Parameter sensitivity: ±20% perturbation → Sharpe drop < 30%

**What Phase 1 does NOT prove:**
- That the signal has predictive power on real TAIFEX data
- That the strategy will be profitable live
- That reported Sharpe numbers reflect real market conditions

### Phase 2: Historical Validation — Alpha Claims
**Purpose**: Prove the strategy has edge on real TAIFEX price history.
**Tools**: `run_historical_backtest` (real OHLCV from SQLite/QuestDB)
**Data**: Real 1m/5m bars from the SQLite database
**Method**: Walk-forward validation (NOT in-sample optimization)

**Walk-forward structure:**
```
Total data: 2 years of real bars

Training window:  6 months  (optimize params here — but use Phase 1 params as prior)
Validation window: 2 months (evaluate without touching params)
Step size: 1 month

Run: [T1→T6 train, T7→T8 validate], [T2→T7 train, T8→T9 validate], ...
Final: report ONLY validation period metrics, never training period metrics
```

**Acceptance criteria for Phase 2 (MINIMUM for sign-off):**
- Walk-forward Sharpe ≥ 0.6 (annualized, validation periods only)
- Max Drawdown ≤ 20% on any single validation window
- Win Rate: 35%–70%
- N_trades ≥ 30 per validation window (low sample → inconclusive)
- Strategy must be tested on BOTH day session and night session separately
- Profit Factor ≥ 1.2 on combined validation periods
- **Intraday strategies**: must use `intraday=true` in `run_backtest_realdata`
  to enforce engine-level session-close and use intraday B&H benchmark.
  Strategy Sharpe must exceed intraday B&H Sharpe (not full-period B&H).

---

## How to Run Historical Backtest (Agent Instructions)

### Step 1: Verify data coverage
```python
# Check you have enough real bars before claiming anything
from src.data.sqlite_store import get_coverage_report
coverage = get_coverage_report()
# Must show: bars ≥ 126,000 (≈ 2 years × 250 days × ~252 bars/day for 1m)
# Must show: no gaps > 2 bars during session hours
```

### Step 2: Load real bars
```python
from src.data.sqlite_store import load_bars_from_sqlite
from datetime import datetime

bars = load_bars_from_sqlite(
    symbol="TXF",
    start=datetime(2022, 1, 1),
    end=datetime(2024, 1, 1),
    interval_minutes=1,
)
# Verify: len(bars) > 100_000
# Verify: bars[0]["timestamp"] is within expected range
```

### Step 3: Run walk-forward backtest
```python
from src.simulator.walk_forward import run_walk_forward

results = run_walk_forward(
    bars=bars,
    strategy="ta_orb",
    strategy_params=phase1_best_params,  # from Phase 1 — do NOT re-optimize here
    train_months=6,
    validate_months=2,
    step_months=1,
)
# results.validation_sharpe  ← this is the number you report
# results.training_sharpe    ← NEVER report this as strategy performance
```

### Step 4: Report correctly
```markdown
## Alpha Validation Report — [Strategy] — [Date]

### Phase 1 Summary (Simulated)
- Parameter set: [params]
- MC P50 Sharpe (strong_bull): X.X  ← robustness, not alpha
- Stress test: PASS/FAIL

### Phase 2 Walk-Forward (Real Data)  ← THIS is alpha evidence
- Data: TXF 1m bars, 2022-01-01 to 2024-01-01
- Walk-forward periods: N
- Validation Sharpe: X.X  ← report this
- Validation Max DD: X.X%
- Validation Win Rate: X%
- Validation N_trades: N (per window avg)
- Day session only: Sharpe X.X
- Night session only: Sharpe X.X

### Verdict
SIGN-OFF / REJECT / INCONCLUSIVE (reason: insufficient data)
```

---

## Agent Checklist Before Claiming Alpha

Before writing "the strategy has alpha" or "the strategy performs well", answer:

```
[ ] Was this result from real OHLCV bars? (not simulated)
    → If NO: you may NOT claim alpha. State "robust parameters found via simulation."

[ ] Was this result from the validation period only? (not the training period)
    → If training period: you may NOT report this Sharpe. It is in-sample.

[ ] Is N_trades ≥ 30 per validation window?
    → If NO: result is statistically inconclusive. Do not sign off.

[ ] Was the strategy tested on both day and night sessions?
    → If NO: incomplete. Night session often has different behavior.

[ ] Were the params fixed from Phase 1 before running Phase 2?
    → If you optimized params on validation data: severe look-ahead bias. Restart.
```

---

## Honest Language Standards

When reporting results, agents MUST use precise language:

| Situation | Correct phrasing |
|---|---|
| MC simulation result | "Simulated robustness: P50 Sharpe = 1.2 on synthetic paths" |
| Real data result | "Walk-forward validation Sharpe = 0.7 on real TXF bars" |
| Training period result | Do not report. Say "training period metrics withheld to prevent data snooping." |
| Insufficient trades | "Result inconclusive: N=18 trades in validation window, minimum is 30." |
| Phase 1 only completed | "Parameters validated for robustness. Alpha not yet claimed. Phase 2 required." |

**Never say**: "The strategy has a Sharpe of 1.8" without specifying simulated vs real and in-sample vs out-of-sample.

---

## Why Simulated Performance Looks Better Than Real Performance
(And why this is expected, not a bug)

Synthetic GBM+GARCH paths have:
- No microstructure noise (bid-ask bounce, partial fills)
- No regime persistence (real markets trend longer or revert more violently)
- No liquidity gaps (real TAIFEX has thin order books at session open)
- No correlation structure across sessions

A real-data Sharpe of 0.6 when simulated Sharpe is 1.2 is **normal and expected**.
A real-data Sharpe of -0.2 when simulated Sharpe is 1.2 means the signal is model-specific, not market-real.
Investigate: look-ahead bias, session boundary error, or the signal requires conditions the synthetic model cannot replicate.
