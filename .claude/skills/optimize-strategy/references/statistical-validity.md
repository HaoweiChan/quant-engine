# Statistical Validity and Overfitting Detection

How to detect overfitting during optimization and what constitutes
statistically valid evidence that a strategy change is real.

## Why Overfitting Is the #1 Killer

A backtest is a search process. Every parameter combination tested
is an implicit hypothesis test. With enough tests, any random
strategy looks good in-sample.

The number of independent parameter combinations tested is MORE
important than the resulting Sharpe ratio.

## Signal 1: In-Sample vs Out-of-Sample Gap

Run Monte Carlo on baseline scenarios (in-sample), then run on
held-out scenarios or with parameter perturbation (out-of-sample proxy).

```
Acceptable:  OOS Sharpe >= 0.7 × IS Sharpe
Warning:     OOS Sharpe  = 0.3 – 0.7 × IS Sharpe  (mild overfit)
Critical:    OOS Sharpe  < 0.3 × IS Sharpe          (severe overfit)
```

In this system, you can approximate OOS testing by:
- Optimizing on 4 scenarios, validating on the other 3
- Using `run_stress_test` as an extreme OOS check

## Signal 2: Parameter Sensitivity (±20% Test)

Run backtest with the optimized parameter ± 20%.

```
Robust:   performance degrades < 30%
Overfit:  performance collapses with small perturbation
```

Example test for `stop_atr_mult`:
```
Optimal: stop_atr_mult=1.5, Sharpe=1.2
Test:    stop_atr_mult=1.2, Sharpe=?
         stop_atr_mult=1.8, Sharpe=?
If either drops below 0.84 (0.7 × 1.2), the value is suspicious.
```

Use `run_parameter_sweep` with a tight grid around the optimal value.

## Signal 3: Too Many Parameters for the Data

### Daily Strategies

Rule of thumb: need 252 × N independent observations per parameter.

```
N=2 parameters → need  504 trading days minimum
N=3 parameters → need  756 trading days minimum
N=5 parameters → need 1,260 trading days minimum
```

The pyramid strategy has ~6 tunable parameters:
  stop_atr_mult, trail_atr_mult, add_trigger_atr (3 values),
  max_levels, entry_conf_threshold
Minimum data: 1,512 trading days (~6 years)

In this system's synthetic paths, `n_bars=252` is 1 year. For 6
parameters, you need `run_monte_carlo` with n_paths >= 500 to get
enough statistical mass, or optimize on fewer parameters at once.

### Intraday Strategies — Degrees of Freedom (DoF)

**Intraday bars are NOT independent observations.** A 1,500-bar sample
on a 1-minute chart is less than 2 trading days — near-zero degrees
of freedom for independent event testing due to high autocorrelation.

Data sufficiency for intraday MUST be measured by the **number of
independent round-trip trades**, not bars:

```
Minimum trades = 100 × N   (N = number of tunable parameters)

N=2 → need ≥ 200 independent round-trip trades
N=3 → need ≥ 300 independent round-trip trades
N=5 → need ≥ 500 independent round-trip trades
```

Additionally, trades must span **multiple macroeconomic regimes**
(e.g., trending months, range-bound months, high-VIX periods).
A strategy validated on 500 trades from a single 2-month bull run
is NOT robust.

**Clustered standard errors:** When intraday trades overlap in time
(e.g., multiple entries within the same session), use clustered
standard errors grouped by session date. This prevents inflated
t-statistics from correlated intraday fills.

When using `run_monte_carlo` for intraday strategies:
- Set `n_bars` to at least 63,000 (~3 months of 1-min bars)
- Require `trade_count >= 100 × N` in Monte Carlo output
- If trade count is too low, increase `n_bars` or `n_paths`, do NOT
  reduce the minimum trade requirement

## Signal 4: Performance Concentrated in Specific Scenarios

Run strategy on each of the 7 scenarios separately.

```
If Sharpe > 2.0 in 2 scenarios but negative in 3 others:
  → The average Sharpe is an illusion
  → The strategy is regime-specific, not robust
```

A robust strategy has positive Sharpe in at least 5 of 7 scenarios.

## The Correct Optimization Sequence

1. Fix **entry** parameters FIRST using directional accuracy, NOT PnL.
   This separates prediction quality from position sizing.
2. Fix **stop** parameters using loss analysis on Step 1's signals.
   Optimal stop: exits losers, keeps winners.
3. Fix **pyramid trigger** parameters LAST.
   These have the smallest individual impact and highest overfitting risk.
4. NEVER touch final OOS data until all parameters are fixed.
   Use it ONCE for validation. If you adjust after seeing it, it's no
   longer out-of-sample.

## Minimum Monte Carlo Acceptance Criteria

Before claiming a strategy change is valid, require ALL of:

```
P50 PnL > 0        across all 7 scenarios
P25 PnL > -max_loss/2   (worst typical case is acceptable)
Win rate > 40%      in at least 5 of 7 scenarios
Sharpe (P50) > 0.5  on the composite run
```

For stress tests (gap_down, slow_bleed, flash_crash, vol_regime_shift,
liquidity_crisis):

```
No scenario causes ruin (total PnL < -max_loss)
At least 3 of 5 stress scenarios have positive P50 PnL
```

## Comparing Baseline vs New: Is the Improvement Real?

```
Sharpe improvement > 0.1 (absolute) → meaningful
Sharpe improvement 0.05 – 0.1       → marginal, needs more evidence
Sharpe improvement < 0.05           → noise, reject the change
```

Also check that the improvement is not concentrated in one scenario.
If baseline Sharpe was 0.6 and new Sharpe is 0.8, but the gain comes
entirely from strong_bull going from 1.0 to 2.5 while others are flat,
the change is regime-specific — not a real improvement.
