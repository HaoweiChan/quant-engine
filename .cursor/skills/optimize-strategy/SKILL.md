---
name: optimize-strategy
description: "Master orchestration for strategy optimization. Use when improving a trading strategy's parameters or logic through the backtest-engine MCP tools."
license: MIT
metadata:
  author: quant-engine
  version: "1.1"
---

Strategy optimization orchestration skill. Defines the 5-stage closed loop
and tells you which domain skills to read at each stage. Read this once at
session start, then follow the stages.

## Before You Start

1. Call `get_parameter_schema` — learn all parameters, ranges, scenarios, and
   the **recommended_timeframe** (especially for intraday strategies).
2. Read this skill fully. Do NOT start changing parameters blindly.

### Timeframe Selection

Check the schema's `recommended_timeframe` field:
- **Daily strategies** (e.g., pyramid): use default `timeframe="daily"`, `n_bars=252`.
- **Intraday strategies** (e.g., atr_mean_reversion): use `timeframe="intraday"`.
  TAIFEX has ~1050 1-min bars/day (day 09:00-13:15 + night 15:15-04:30).
  Presets: `21000` (~1 month), `63000` (~3 months), `264600` (~1 year).

Always pass `timeframe` and `n_bars` to `run_backtest`, `run_monte_carlo`,
and `run_parameter_sweep` when working with intraday strategies.

## The 5-Stage Optimization Loop

```
DIAGNOSE → HYPOTHESIZE → EXPERIMENT → EVALUATE → COMMIT/REJECT
    ↑                                                    |
    └────────────────────────────────────────────────────┘
```

Run this loop until one of the stopping conditions is met.

### Staged Evaluation (Cost-Efficient)

Do NOT jump straight to Monte Carlo. Follow this progression:

1. **Single backtest** (~3s) — quick smoke test on 1 scenario.
   If Sharpe < 0 or trade_count < 10, stop and re-hypothesize.
2. **Multi-scenario backtest** (~20s) — run all 7 scenarios.
   If > 4 scenarios negative, stop and re-hypothesize.
3. **Monte Carlo** (~20-60s) — only run after single backtest looks promising.
   Use `n_paths=20` for iteration, `n_paths=200` for final validation.

This avoids wasting minutes on dead-end parameter sets.

---

### Stage 1: DIAGNOSE

**Read skills:** `quant-stop-diagnosis`, `quant-overfitting`
**MCP tools:** `get_parameter_schema`, `run_backtest`, `get_optimization_history`

Establish a baseline using the staged approach:
1. Run `run_backtest` on 2-3 key scenarios (strong_bull, sideways, bear)
   to get a quick read on entry quality and stop behavior.
2. If results are promising, run all 7 scenarios.
3. Only proceed to `run_monte_carlo` if single-path results show > 10 trades
   and at least 1 scenario has positive PnL.

Analyze the results using the diagnosis patterns from `quant-stop-diagnosis`:
- Which scenarios fail? (negative PnL)
- What is the win rate? (35-45% is normal for trend-following)
- Is max drawdown acceptable relative to max_loss?
- Are there signs of overfitting from `get_optimization_history`?

Identify the weakest component: entry filter, stop logic, or position sizing.

---

### Stage 2: HYPOTHESIZE

**Read skills:** `quant-trend-following`, `quant-regime`, `quant-stop-diagnosis`
**MCP tools:** none (reasoning only)

Based on the diagnosis, form ONE concrete hypothesis:
- "The trailing stop is too tight — trail_atr_mult should be 4.0 instead of 3.0"
- "The strategy enters in choppy regimes — add a volatility filter to EntryPolicy"
- "The add-trigger is too aggressive — increase add_trigger_atr[0] from 4.0 to 5.0"

Rules:
- Change ONE thing at a time. Never change entry + stop + sizing simultaneously.
- Refer to the regime-parameter table in `quant-regime` for target ranges.
- If the diagnosis points to entry problems, do NOT fix stops instead.

---

### Stage 3: EXPERIMENT

**Read skills:** `quant-pyramid-math` (if changing position sizing)
**MCP tools:** `run_parameter_sweep`, `read_strategy_file`, `write_strategy_file`, `run_backtest`

For **parameter changes**: use `run_parameter_sweep` to search a small range
around your hypothesis (e.g., trail_atr_mult=[3.0, 3.5, 4.0, 4.5]).

For **logic changes**: use `read_strategy_file` to understand current code,
then `write_strategy_file` with modifications. Run `run_backtest` immediately
after writing as a quick smoke test before committing to full evaluation.

Constraints:
- Sweep at most 2-3 parameters at once (overfitting risk).
- Check parameter interactions from `quant-pyramid-math` (e.g., trail > stop).
- Keep Kelly fraction ≤ 0.25 and margin_limit ≤ 0.50 — these are safety rails.

---

### Stage 4: EVALUATE

**Read skills:** `quant-overfitting`
**MCP tools:** `run_monte_carlo`, `run_stress_test`, `get_optimization_history`

Only reach this stage if Stage 3's quick backtests were promising. Now run
the full validation suite.

Run `run_monte_carlo` (n_paths=200) on the best candidate across ALL
scenarios + stress tests. For intraday strategies, MC uses multiprocessing
automatically.

Acceptance criteria (from `quant-overfitting`):
- P50 PnL > 0 across all 7 scenarios
- P25 PnL > -max_loss/2
- Win rate > 40% in at least 5 of 7 scenarios
- Sharpe of P50 path > 0.5
- Stress test: no scenario causes ruin (PnL < -max_loss)

Compare against baseline:
- Sharpe improvement > 0.1 (absolute) is meaningful
- If improvement < 0.05, the change is noise — reject it

Check for overfitting:
- Run the ±20% parameter sensitivity test from `quant-overfitting`
- If performance collapses with small perturbation, the value is overfit

---

### Stage 5: COMMIT or REJECT

**Read skills:** none
**MCP tools:** `get_optimization_history`

Decision rules:
- **COMMIT** if: all acceptance criteria pass AND improvement is meaningful
  → Record the new parameters as the new baseline
  → Move to next diagnosis cycle if further improvement needed
- **REJECT** if: any acceptance criteria fail OR improvement is noise
  → Revert to baseline parameters
  → Return to DIAGNOSE with a different hypothesis

---

## Stopping Conditions

Stop the optimization loop when ANY of these are true:
- **Target reached**: Sharpe > 1.0 across all scenarios (good enough)
- **Diminishing returns**: 3 consecutive rejected hypotheses
- **Budget exhausted**: 50+ MCP tool calls in this session
- **User satisfied**: User says to stop

## Immutable Safety Parameters

NEVER optimize these — they are risk management constraints:
- `max_loss`: Set by the user's risk tolerance, not by optimization
- `margin_limit`: Broker safety rail, not a tunable parameter

## Parameter Priority Order

When optimizing, follow this sequence (from `quant-overfitting`):
1. Entry parameters (entry_conf_threshold, regime filters)
2. Stop parameters (stop_atr_mult, trail_atr_mult, trail_lookback)
3. Position sizing (add_trigger_atr, lot_schedule, kelly_fraction)
4. Final validation on held-out scenarios
