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

## Multi-Stage Optimization Levels

Strategies progress through three optimization levels with progressively stricter gates.
The engine auto-resolves thresholds from `HoldingPeriod` + `OptimizationLevel`.

| Level | Name | Purpose | Required Checks |
|-------|------|---------|----------------|
| L1 | Exploratory | "Worth investigating?" | MC on 2+ scenarios |
| L2 | Validated | "Survives out-of-sample?" | WF + sensitivity + MC 5+ scenarios |
| L3 | Production | "Ready for live capital?" | All L2 + slippage stress + paper trade |

### Quality Gate Thresholds by Holding Period and Level

| Gate | SHORT_TERM L1/L2/L3 | MEDIUM_TERM L1/L2/L3 | SWING L1/L2/L3 |
|------|---------------------|----------------------|----------------|
| Sharpe floor | 0.6 / 1.0 / 1.0 | 0.5 / 0.8 / 0.8 | 0.4 / 0.7 / 0.7 |
| Min trades/fold | 30 / 100 / 100 | 15 / 30 / 30 | 10 / 20 / 20 |
| MDD max | — / 10% / 10% | — / 15% / 15% | — / 20% / 20% |
| WR range | 40-75 / 45-70 / 45-70 | 35-70 / 40-65 / 40-65 | 25-60 / 35-55 / 35-55 |
| PF floor | 1.0 / 1.3 / 1.3 | 1.0 / 1.2 / 1.2 | 1.0 / 1.2 / 1.2 |
| Sensitivity CV | — / <0.15 / <0.15 | — / <0.20 / <0.20 | — / <0.25 / <0.25 |
| Slippage Sharpe | — / — / ≥0.5 | — / — / ≥0.5 | — / — / ≥0.4 |

These thresholds are the **single source of truth** in `src/strategies/__init__.py`.
The MCP tools `run_walk_forward`, `run_parameter_sweep`, and `run_risk_report`
auto-resolve them from the strategy's `STRATEGY_META["holding_period"]`.

Use `promote_optimization_level` MCP tool to advance a strategy after it passes all gates.

## Default Optimization Goal (for `optimize [strategy]` requests)

Unless the user specifies otherwise, optimize to **advance to the next level**:

**Find a parameter set with a maximum of 3 variables that:**
- Maintains positive expectancy across both In-Sample and Out-of-Sample datasets
- Achieves the holding-period-appropriate Sharpe floor for the target level
- Demonstrates stable parameter landscape (sensitivity CV below threshold)
- **Survives 50% penalty to execution slippage** (at L3)
- Meets the holding-period-appropriate trade count minimum

Check current level with strategy TOML: `config/strategies/<slug>.toml`.

## Step 0: Classify Strategy Type (MANDATORY)

Before ANY diagnosis or optimization, classify the strategy into one of
these types. This determines which metrics are "healthy" and which reference
files apply:

| Type | Holding Period | Edge Source | Healthy WR | Healthy RR | Key References |
|------|---------------|-------------|-----------|-----------|----------------|
| Swing trend-following | SWING | Asymmetric payoff (multi-week) | 35-45% | 2.5+ | references/strategy-types.md, references/position-sizing.md |
| Daily trend-following | MEDIUM_TERM | Asymmetric payoff (daily) | 40-55% | 1.5-2.5 | references/strategy-types.md |
| Intraday breakout | SHORT_TERM | Momentum continuation | 45-55% | 1.0-2.0 | references/strategy-types.md (intraday sections) |
| Intraday mean-reversion | SHORT_TERM | Overshoot correction | 55-65% | 0.6-1.0 | references/strategy-types.md (intraday sections) |
| Statistical arb / liquidity | SHORT_TERM | Spread capture | 60-70% | 0.3-0.8 | (specialized) |

**How to classify:**
1. Call `get_parameter_schema` — check `holding_period`, `category`, and `signal_timeframe`.
2. The `holding_period` metadata (`SHORT_TERM`/`MEDIUM_TERM`/`SWING`) determines which
   threshold row applies. If missing, fall back to `SHORT_TERM` (conservative).
3. The engine resolves thresholds automatically — you don't need to hardcode them.

**Why this matters:**
- A 60% win rate is FAILING for trend-following but HEALTHY for mean-reversion.
- A 0.8 reward-risk ratio is FAILING for trend-following but HEALTHY for intraday.
- Applying daily trend-following diagnosis to intraday strategies produces
  WRONG conclusions. The typology router prevents this.

**Carry the classification through all 5 stages.** Every diagnosis pattern,
parameter range, and acceptance criterion must be read through the lens of
the strategy's type.

## Seed Architecture Principles (MANDATORY)

These principles are derived from docs/archive/seed-strategy-architecture-for-ml-agents.md
and validated through live optimization runs. They apply to ALL optimization loops.

### Indicator Selection
- **REQUIRED structural indicators**: VWAP, ATR, ADX, Time-of-Day session logic.
- **BANNED lagging indicators**: MACD, standard MA crossovers, Stochastics.
- **RSI exception**: RSI with period <= 5 is acceptable as a structural stress
  indicator. RSI-14 is lagging momentum — do not use it.
- **ATR for all dynamic stops/sizing**: never use fixed-point stops on futures.
- **ADX as regime filter**: markets chop 70% of the time. ADX separates
  trend-following entries (ADX >= threshold) from mean-reversion entries (ADX < threshold).

### Fitness Function
- **Default metric**: `composite_fitness` (= calmar × profit_factor / duration_penalty).
- **NEVER optimize for net profit or raw PnL** — it finds lucky outliers.
- **Calmar > Sharpe** for intraday (captures tail risk better).
- Duration penalty = max(1, avg_holding_hours / 10) — penalizes stale positions.
- Composite fitness auto-disqualifies candidates with < 100 trades or
  expectancy below the minimum (covers slippage + commission).

### Parameter Bounds
- Restrict all parameter ranges to prevent overfitting.
- Keltner/ATR multipliers: [0.05, 3.0] (not unbounded).
- ADX threshold: [20, 40] (too low = no filter, too high = no trades).
- RSI period: [2, 7] for structural stress use.
- Lookback periods: cap at 30 bars on 1-min charts (a 200-period EMA on
  1-min data is 3+ hours of lag — useless for intraday).

### Intraday Mandatory Rules
- **EOD force-close**: all positions must close before session end.
- **Max hold bars**: enforce a maximum holding period to free the engine.
- **Time gating**: block entries in low-edge windows (first/last 15 min).
- **Volume confirmation**: require volume >= vol_mult × rolling average.
- **Slippage + commission**: always model at least 1 bps slippage + 1 bps commission.

## Before You Start

1. Call `get_parameter_schema` — learn all parameters, ranges, scenarios, and
   the **recommended_timeframe** (especially for intraday strategies).
2. **Classify the strategy type** using Step 0 above.
3. Read this skill fully. Do NOT start changing parameters blindly.
4. **Read `references/seed-strategy-guidelines.md`** for the full rationale.

### Timeframe Selection

Check the schema's `recommended_timeframe` field:
- **Daily strategies** (e.g., pyramid): use default `timeframe="daily"`, `n_bars=252`.
- **Intraday strategies** (e.g., atr_mean_reversion): use `timeframe="intraday"`.
  TAIFEX has ~1050 1-min bars/day (day 09:00-13:15 + night 15:15-04:30).
  Presets: `21000` (~1 month), `63000` (~3 months), `264600` (~1 year).

Always pass `timeframe` and `n_bars` to `run_backtest`, `run_monte_carlo`,
and `run_parameter_sweep` when working with intraday strategies.

### Intraday Mode (`intraday=true`)

When running `run_backtest_realdata` for intraday strategies, **always set
`intraday=true`**. This enables two critical behaviors:

1. **Engine-level force-close**: All open positions are forcibly liquidated at
   each TAIFEX session end (day 13:45, night 05:00), regardless of strategy
   policy. This guarantees no inter-session carry.
2. **Intraday B&H benchmark**: The buy-and-hold comparison becomes session-scoped
   (buy first bar open, sell last bar close per session) instead of full-period.
   This is the only fair benchmark for intraday strategies.

The `intraday` flag is persisted in run history and shown in the dashboard.

**Hard rule:** synthetic outputs (`run_backtest`, `run_monte_carlo`, or
`run_parameter_sweep` in `research` mode) are exploratory only. They can guide
hypotheses but can NEVER satisfy optimization termination criteria.

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

For **parameter changes**: use `run_parameter_sweep` (Optuna TPE) to search the
parameter space defined by `min`/`max`/`step` in `PARAM_SCHEMA`.
Use `mode="research"` with `require_real_data=false` for fast synthetic iteration.

For **logic changes**: use `read_strategy_file` to understand current code,
then `write_strategy_file` with modifications. Run `run_backtest` immediately
after writing as a quick smoke test before committing to full evaluation.

Constraints:
- Sweep at most 2-3 parameters at once (overfitting risk).
- Check parameter interactions from `references/position-sizing.md` (e.g., trail > stop).
- Keep Kelly fraction ≤ 0.25 and margin_limit ≤ 0.50 — these are safety rails.

**Before writing a new `AddPolicy` subclass**: check `src/core/policies.py` for
existing reusable classes. The canonical ATR-profit pyramid pattern
("+K ATR floating profit triggers another add, sized gamma^level") lives in
`AtrPyramidAdd` and supports an optional `session_filter` callable for
session-scoped strategies. Most trend-following adds should use it directly —
do not copy-paste `PyramidAddPolicy` or prior per-strategy subclasses.
Write a new subclass only if the sizing or trigger logic is genuinely
strategy-specific (e.g., `vol_managed_bnh` inverse-vol overlay,
`PyramidAddPolicy` per-level trigger schedule); document the reason in the
class docstring.

---

### Stage 4: EVALUATE

**Read references:** `references/statistical-validity.md`
**MCP tools:** `run_monte_carlo`, `run_stress_test`, `run_backtest_realdata`, `run_parameter_sweep`, `run_walk_forward`, `run_sensitivity_check`, `run_risk_report`, `get_optimization_history`

Only reach this stage if Stage 3's quick backtests were promising. Now run
the full validation suite.

Use three-layer evaluation:

1. **Synthetic robustness (exploratory, non-terminating)**  
   Run `run_monte_carlo` (n_paths=200) across scenarios + `run_stress_test`.
   For intraday strategies, MC uses multiprocessing automatically.

2. **Parameter sensitivity & stability check (mandatory gate)**  
   Run `run_sensitivity_check` with the candidate parameters to test ±20% perturbation.
   This checks for overfitting and parameter cliff-edges.
   - MUST PASS: max Sharpe drop < 30%
   - MUST PASS: all parameters have stability CV < 0.20
   - MUST PASS: no parameter has a cliff (>30% drop between adjacent sample points)
   If sensitivity check fails, the candidate is overfit — reject and return to HYPOTHESIZE.

3. **Real-data termination gate (mandatory for accept/stop decisions)**  
   Validate the candidate on TAIFEX history using:
   - `run_backtest_realdata` on baseline params and candidate params
   - `run_parameter_sweep` with `mode="production_intent"`, `require_real_data=true`,
     and explicit `symbol/start/end`
   - `run_walk_forward` with the candidate params for expanding-window out-of-sample
     validation. This is a mandatory check to confirm the candidate doesn't overfit
     to a particular training window.
   The final commit/reject decision must be based on this real-data layer.

Walk-forward acceptance criteria are now **auto-resolved from holding period + optimization level**.
The engine reads thresholds from `src/strategies/__init__.py` `get_stage_thresholds()`.

For L2 (typical walk-forward validation):

| Gate | SHORT_TERM | MEDIUM_TERM | SWING |
|------|-----------|-------------|-------|
| Aggregate OOS Sharpe | ≥ 1.0 | ≥ 0.8 | ≥ 0.7 |
| Per-fold MDD | ≤ 10% | ≤ 15% | ≤ 20% |
| Per-fold trade count | ≥ 100 | ≥ 30 | ≥ 20 |
| Per-fold PF | ≥ 1.3 | ≥ 1.2 | ≥ 1.2 |
| Per-fold WR | 45-70% | 40-65% | 35-55% |
| Sensitivity CV | < 0.15 | < 0.20 | < 0.25 |
| Mean overfit ratio | ≥ 0.7 | ≥ 0.7 | ≥ 0.7 |
| WF structure | 3mo/1mo/1mo | 6mo/2mo/1mo | 12mo/3mo/2mo |

**You do NOT need to hardcode these values.** Call `run_walk_forward` and the engine
applies the correct gates automatically based on strategy metadata.

Real-data acceptance criteria:
- P50 PnL > 0 across all 7 scenarios
- P25 PnL > -max_loss/2
- Win rate within the **strategy type's healthy range** (Step 0) in at least 5 of 7 scenarios
- Sharpe of P50 path > holding-period Sharpe floor
- Stress test: no scenario causes ruin (PnL < -max_loss)
- Trade count meets holding-period DoF requirement (auto-resolved)

Compare against baseline:
- Sharpe improvement > 0.1 (absolute) is meaningful
- If improvement < 0.05, the change is noise — reject it

Optional: Use `run_risk_report` to automatically orchestrate all 5 evaluation layers
(cost, sensitivity, regime MC, adversarial injection, walk-forward) in a single call.
This requires providing symbol/start/end for walk-forward validation.

Do not terminate the loop from synthetic metrics alone, even if they look superior.

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
- **Target reached on real data**: composite_fitness > 5.0 OR (calmar > 1.2 AND alpha > 50%) from `run_backtest_realdata` / `run_parameter_sweep(mode=production_intent)`
- **Diminishing returns**: 3 consecutive rejected hypotheses
- **Budget exhausted**: 50+ MCP tool calls in this session
- **User satisfied**: User says to stop

## Immutable Safety Parameters

NEVER optimize these — they are risk management constraints:
- `max_loss`: Set by the user's risk tolerance, not by optimization
- `margin_limit`: Broker safety rail, not a tunable parameter
- `slippage_bps` / `commission_bps`: safety overhead, not tunable
- `min_trade_count`: statistical validity gate, not tunable

## Parameter Priority Order

When optimizing, follow this sequence (from `references/statistical-validity.md`):
1. Entry parameters (ADX threshold, Keltner mult, RSI thresholds, VWAP filter)
2. Stop parameters (atr_sl_multi, atr_tp_multi, max_hold_bars)
3. Position sizing (kelly_fraction); pyramid params are account-level, not tunable
4. Time/volume filters (time_gate, vol_mult, cooldown_bars)
5. Final validation on held-out data (different date range)

## Default Sweep Configuration

All sweeps use Optuna TPE (Bayesian optimization with pruning). Parameter ranges
are defined by `min`/`max`/`step` in each strategy's `PARAM_SCHEMA`.

When running `run_parameter_sweep`, use one of these profiles:

**Exploration (loop iterations, synthetic allowed):**
- `metric`: `composite_fitness`
- `mode`: `research`
- `require_real_data`: `false`
- `is_fraction`: 0.8
- Always sweep ≤ 3 parameters at once

**Sign-off (final accept/stop decision, real data required):**
- `metric`: `composite_fitness`
- `mode`: `production_intent`
- `require_real_data`: `true`
- `symbol/start/end`: required (real TAIFEX interval)
- `min_trade_count`: 100
- `min_expectancy`: 0.0 (set > 0 for TAIFEX to cover tick costs)
