# Seed Strategy Architecture Guidelines

Derived from `docs/Seed-Strategy-Architecture-For-ML-Agents.md` and validated
through live optimization on TAIFEX H1 2025 data (keltner_vwap_breakout achieving
alpha 52.68%, calmar 11.75, 184 trades).

## 1. Indicator Hierarchy

### Structural (USE THESE)

| Indicator | Role | Why It Works |
|-----------|------|-------------|
| VWAP | Institutional baseline | Deviation = real premium/discount vs market consensus |
| ATR | Volatility measure | Only non-arbitrary measure of price range; basis for all stops and sizing |
| ADX | Regime filter | Separates trending (30%) from chopping (70%) market states |
| Time-of-Day | Session logic | TAIFEX has forced flows at 08:45, 09:00, 13:30 |
| Keltner Channels | Volatility boundaries | EMA ± ATR×mult defines structural breakout/reversion zones |
| Volume | Confirmation | Breakouts without volume are noise |

### Short-Period RSI (PERMITTED WITH CAVEATS)

RSI with period 2-5 measures structural price stress (consecutive closes in
one direction), NOT lagging momentum. Validated: RSI-3 was the single largest
alpha contributor in our optimization (+11% absolute alpha improvement).

RSI-14 is banned — by the time it signals, HFT has captured the move.

### Banned (NEVER USE IN OPTIMIZER)

| Indicator | Why |
|-----------|-----|
| MACD | Derivative of derivative; lags badly on 1-min |
| Stochastics | Lags; bounded oscillator has no structural meaning |
| MA Crossovers (long period) | 200-period EMA on 1-min = 3+ hours of lag |

## 2. Composite Fitness Function

**Never optimize for net profit.** A net-profit objective finds the single
parameter set that caught one lucky 600-point TAIFEX gap.

### Formula

```
composite_fitness = (calmar_ratio × profit_factor) / duration_penalty
```

Where:
- `calmar_ratio` = annualized_return / max_drawdown_pct
- `profit_factor` = gross_profit / gross_loss
- `duration_penalty` = max(1, avg_holding_hours / 10)

### Disqualification Gates (return -9999.0)

1. `trade_count < 100` → insufficient statistical evidence
2. `expectancy < min_expectancy` → doesn't cover transaction costs

### Why Calmar > Sharpe for Intraday

Sharpe penalizes upside volatility equally with downside. For intraday
strategies with asymmetric payoffs, Calmar (return/max-drawdown) better
captures the risk that actually matters: capital destruction.

### Implementation

The function `composite_fitness()` is implemented in `src/simulator/metrics.py`
and auto-computed in every `compute_all_metrics()` call. Available as an
optimization metric in `run_parameter_sweep` via `metric="composite_fitness"`.

## 3. Parameter Bounds Enforcement

### The Principle

An optimizer is an unfettered curve-fitting machine. Without tight bounds,
it will find the one-in-a-million parameter set that happens to exploit
historical noise.

### Recommended Bounds by Parameter Type

| Parameter | Min | Max | Rationale |
|-----------|-----|-----|-----------|
| kc_mult (Keltner multiplier) | 0.05 | 3.0 | Wider = fewer trades; narrower = more noise |
| adx_threshold | 20 | 40 | Below 20 = no filtering; above 40 = no trades |
| adx_period | 7 | 21 | Shorter = reactive; longer = lagging |
| rsi_len (RSI period) | 2 | 7 | Short-period structural stress only |
| rsi_oversold / rsi_overbought | 15/70 | 40/90 | Standard band widths |
| atr_sl_multi (stop-loss) | 0.1 | 2.0 | ATR fraction for stop placement |
| atr_tp_multi (take-profit) | 0.3 | 3.0 | ATR fraction for profit target |
| max_hold_bars | 20 | 120 | 20 min to 2 hours for intraday |
| cooldown_bars | 3 | 30 | Minimum bars between trades |
| vol_mult (volume filter) | 0.5 | 2.0 | Fraction of rolling average |
| kc_len (EMA lookback) | 10 | 30 | Cap at 30 to prevent excessive lag |
| trend_filter_atr | 1.0 | 5.0 | How far from trend MA before blocking entry |

### The Lookback Cap Rule

On 1-minute charts, any indicator lookback > 30 bars represents 30+ minutes
of lag. A 200-period EMA on 1-min data is 3+ hours — useless for intraday.
Cap all lookback periods at 30 for 1-min strategies.

## 4. Intraday Structural Requirements

These are NOT optional — they must be present in any intraday strategy
submitted to the optimizer:

### EOD Force-Close
All positions MUST close before session end. Without this, the single-position
PositionEngine blocks all new entries until the stale position is manually closed.

### Max Hold Bars
Every position must have a maximum holding period. Stale positions that haven't
hit stop or target represent dead capital. Force-close after N bars.

### Time Gating
Block entries during low-edge windows:
- First 15 minutes after session open (noise, gap fills)
- Last 15 minutes before session close (forced flows, not real alpha)
- These times show negative expectancy across most strategy types.

### Volume Confirmation
Require volume >= vol_mult × rolling_average. Breakouts without volume
participation are false signals.

### Cost Modeling
Always backtest with realistic costs:
- `slippage_bps >= 1.0` (1 basis point minimum)
- `commission_bps >= 1.0` (or commission_fixed_per_contract for futures)
- A strategy that only works with zero costs is not a strategy.

## 5. Regime-Adaptive Architecture

Markets alternate between trending and mean-reverting states. A single-mode
strategy fails in the wrong regime. The validated approach:

```
if ADX >= adx_threshold:
    # TRENDING: breakout-following
    Buy above upper Keltner band
    Sell below lower Keltner band
    Confirm with VWAP alignment
else:
    # CHOPPY: mean-reversion
    Buy below lower Keltner band (RSI oversold)
    Sell above upper Keltner band (RSI overbought)
    Confirm with VWAP alignment
```

This was validated to produce alpha > 50% on TAIFEX H1 2025 data.

## 6. Optimization Sequence

1. **Entry parameters first**: ADX threshold, Keltner mult, RSI thresholds
   - Optimize for directional accuracy, NOT PnL
   - This separates prediction quality from risk management
2. **Stop/exit parameters second**: atr_sl_multi, atr_tp_multi, max_hold_bars
   - Optimal stop exits losers and keeps winners
3. **Position sizing last**: lot schedule, kelly fraction
   - Smallest individual impact, highest overfitting risk
4. **Never touch held-out data until all parameters are fixed**

## 7. Statistical Validity Gates

| Gate | Daily | Intraday |
|------|-------|----------|
| Min trades | 252 × N_params | 100 × N_params |
| OOS efficiency | >= 0.7 × IS | >= 0.7 × IS |
| Parameter sensitivity | ±20% degrades < 30% | ±20% degrades < 30% |
| Regime coverage | 5/7 scenarios positive | Multiple months/regimes |
| Cost survival | N/A | Positive after 1bps slippage + commission |
