---
name: optimize-strategy
description: "Master orchestration for strategy optimization. Use when improving a trading strategy's parameters or logic through the backtest-engine MCP tools."
license: MIT
metadata:
  author: quant-engine
  version: "3.0"
---

Strategy optimization orchestration skill. Defines the 5-stage closed loop
and tells you which reference files to read at each stage. Read this once at
session start, then follow the stages.

## Step 0: Classify Strategy Type (MANDATORY)

Before ANY diagnosis or optimization, classify the strategy into one of
these types. This determines which metrics are "healthy" and which reference
files apply:

| Type | Timeframe | Edge Source | Healthy WR | Healthy RR | Key References |
|------|-----------|-------------|-----------|-----------|----------------|
| Trend-following | Daily | Asymmetric payoff | 35-45% | 2.5+ | references/strategy-types.md, references/position-sizing.md |
| Intraday breakout | Intraday | Momentum continuation | 45-55% | 1.0-2.0 | references/strategy-types.md (intraday sections) |
| Intraday mean-reversion | Intraday | Overshoot correction | 55-65% | 0.6-1.0 | references/strategy-types.md (intraday sections) |
| Statistical arb / liquidity | Intraday | Spread capture | 60-70% | 0.3-0.8 | (specialized) |

**How to classify:**
1. Call `get_parameter_schema` — check `recommended_timeframe` and `category`.
2. If `timeframe=intraday` and `category=mean_reversion` → Intraday mean-reversion.
3. If `timeframe=intraday` and `category=breakout` → Intraday breakout.
4. If `timeframe=daily` → Trend-following (default).

**Why this matters:**
- A 60% win rate is FAILING for trend-following but HEALTHY for mean-reversion.
- A 0.8 reward-risk ratio is FAILING for trend-following but HEALTHY for intraday.
- Applying daily trend-following diagnosis to intraday strategies produces
  WRONG conclusions. The typology router prevents this.

**Carry the classification through all 5 stages.** Every diagnosis pattern,
parameter range, and acceptance criterion must be read through the lens of
the strategy's type.

## Before You Start

1. Call `get_parameter_schema` — learn all parameters, ranges, scenarios, and
   the **recommended_timeframe** (especially for intraday strategies).
2. **Classify the strategy type** using Step 0 above.
3. Read this skill fully. Do NOT start changing parameters blindly.

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

**Read references:** `references/stop-diagnosis.md`, `references/statistical-validity.md`
**MCP tools:** `get_parameter_schema`, `run_backtest`, `get_optimization_history`

Establish a baseline using the staged approach:
1. Run `run_backtest` on 2-3 key scenarios (strong_bull, sideways, bear)
   to get a quick read on entry quality and stop behavior.
2. If results are promising, run all 7 scenarios.
3. Only proceed to `run_monte_carlo` if single-path results show > 10 trades
   and at least 1 scenario has positive PnL.

Analyze the results using the diagnosis patterns from `references/stop-diagnosis.md`:
- Which scenarios fail? (negative PnL)
- What is the win rate? (check against the **strategy type's healthy range** from Step 0)
  - Daily trend-following: 35-45% is normal
  - Intraday breakout: 45-55% is normal
  - Intraday mean-reversion: 55-65% is normal
- Is max drawdown acceptable relative to max_loss?
- Are there signs of overfitting from `get_optimization_history`?
- **Intraday only**: Is the trade count sufficient? (see `references/statistical-validity.md` DoF rules)
- **Intraday only**: Are losses concentrated in low-edge time windows? (see `references/regime.md`)

Identify the weakest component: entry filter, stop logic, or position sizing.

---

### Stage 2: HYPOTHESIZE

**Read references:** `references/strategy-types.md`, `references/regime.md`, `references/stop-diagnosis.md`
**MCP tools:** none (reasoning only)

Based on the diagnosis, form ONE concrete hypothesis:
- "The trailing stop is too tight — trail_atr_mult should be 4.0 instead of 3.0"
- "The strategy enters in choppy regimes — add a volatility filter to EntryPolicy"
- "The add-trigger is too aggressive — increase add_trigger_atr[0] from 4.0 to 5.0"

Rules:
- Change ONE thing at a time. Never change entry + stop + sizing simultaneously.
- Refer to the regime-parameter table in `references/regime.md` for target ranges.
- If the diagnosis points to entry problems, do NOT fix stops instead.

---

### Stage 3: EXPERIMENT

**Read references:** `references/position-sizing.md` (if changing position sizing)
**MCP tools:** `run_parameter_sweep`, `read_strategy_file`, `write_strategy_file`, `run_backtest`

For **parameter changes**: use `run_parameter_sweep` to search a small range
around your hypothesis (e.g., trail_atr_mult=[3.0, 3.5, 4.0, 4.5]).

For **logic changes**: use `read_strategy_file` to understand current code,
then `write_strategy_file` with modifications. Run `run_backtest` immediately
after writing as a quick smoke test before committing to full evaluation.

Constraints:
- Sweep at most 2-3 parameters at once (overfitting risk).
- Check parameter interactions from `references/position-sizing.md` (e.g., trail > stop).
- Keep Kelly fraction ≤ 0.25 and margin_limit ≤ 0.50 — these are safety rails.

---

### Stage 4: EVALUATE

**Read references:** `references/statistical-validity.md`
**MCP tools:** `run_monte_carlo`, `run_stress_test`, `get_optimization_history`

Only reach this stage if Stage 3's quick backtests were promising. Now run
the full validation suite.

Run `run_monte_carlo` (n_paths=200) on the best candidate across ALL
scenarios + stress tests. For intraday strategies, MC uses multiprocessing
automatically.

Acceptance criteria (from `references/statistical-validity.md`):
- P50 PnL > 0 across all 7 scenarios
- P25 PnL > -max_loss/2
- Win rate within the **strategy type's healthy range** (Step 0) in at least 5 of 7 scenarios
  - Daily trend-following: > 35%
  - Intraday breakout: > 45%
  - Intraday mean-reversion: > 55%
- Sharpe of P50 path > 0.5
- Stress test: no scenario causes ruin (PnL < -max_loss)
- **Intraday only**: trade_count >= 100 × N_params (from `references/statistical-validity.md`)
- **Intraday only**: Sharpe remains > 0.5 AFTER adding 1-tick round-trip slippage

Compare against baseline:
- Sharpe improvement > 0.1 (absolute) is meaningful
- If improvement < 0.05, the change is noise — reject it

Check for overfitting:
- Run the ±20% parameter sensitivity test from `references/statistical-validity.md`
- If performance collapses with small perturbation, the value is overfit

---

### Stage 5: COMMIT or REJECT

**Read references:** none
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

When optimizing, follow this sequence (from `references/statistical-validity.md`):
1. Entry parameters (entry_conf_threshold, regime filters)
2. Stop parameters (stop_atr_mult, trail_atr_mult, trail_lookback)
3. Position sizing (add_trigger_atr, lot_schedule, kelly_fraction)
4. Final validation on held-out scenarios
