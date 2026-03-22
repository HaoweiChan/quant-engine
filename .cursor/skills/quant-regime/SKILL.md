---
name: quant-regime
description: "Market regime detection and strategy adaptation. Read when forming hypotheses about scenario-specific failures or adjusting parameters for different market conditions."
license: MIT
metadata:
  author: quant-engine
  version: "1.0"
---

How to identify market regimes and which parameters to adapt per regime.

## The Four Regimes

### TRENDING
**Characteristics:** Directional move > 2× ATR over 20 bars, low
day-to-day reversals, expanding volume.
**ATR pattern:** Stable or gradually expanding.
**Maps to scenarios:** `strong_bull`, `gradual_bull`, `bear`

### VOLATILE (high vol, no direction)
**Characteristics:** Large daily swings, no net movement over 10 bars,
ATR expanding rapidly.
**ATR pattern:** Spikes sharply, then oscillates.
**Maps to scenarios:** `volatile_bull`, `flash_crash`

### CHOPPY (low vol, no direction)
**Characteristics:** ATR contracting, small daily ranges, price
oscillates around moving average.
**ATR pattern:** Compressing steadily.
**Maps to scenarios:** `sideways`

### BREAKOUT (transition from choppy to trending)
**Characteristics:** Sudden ATR expansion after compression, price
moves through recent range boundaries.
**ATR pattern:** Sharp jump from low baseline.
**Maps to scenarios:** `bull_with_correction` (partial)

## Simple Regime Classifier (No ML Required)

Using only ATR ratio and trend score:

```
atr_ratio   = ATR(14) / ATR(63)    # short-term vs long-term vol
trend_score = abs(close - SMA(20)) / ATR(14)  # distance from mean in ATR units

if atr_ratio > 1.5 and trend_score > 1.5:  → TRENDING
if atr_ratio > 1.5 and trend_score < 0.5:  → VOLATILE
if atr_ratio < 0.7:                         → CHOPPY
else:                                        → UNCERTAIN
```

This classifier uses data already available in the strategy's
`MarketSnapshot`. No external indicators needed.

## Regime-Parameter Target Table

Use these as soft targets during optimization — not hard-coded values.
If `run_parameter_sweep` finds optimal values far from this table,
investigate why before accepting.

```
Parameter          TRENDING  VOLATILE  CHOPPY   UNCERTAIN
─────────────────  ────────  ────────  ───────  ─────────
stop_atr_mult      1.5       2.0       N/A      1.8
trail_atr_mult     3.0       4.5       N/A      3.5
add_trigger[0]     3.0       6.0       N/A      5.0
max_levels         4         2         0        1
kelly_fraction     0.25      0.10      0.00     0.15
entry_conf         0.60      0.75      1.00*    0.70
```

*`entry_conf=1.00` for CHOPPY effectively blocks all entries (no entry
will have confidence = 1.0). This is the intended behavior: do not
trade in a choppy regime.

## What the Agent MUST NOT Do with Regime

**NEVER change stop-loss execution based on regime.**
Stops execute on price. Period. Regime is irrelevant once a stop is set.

**NEVER hold a position past its stop because of regime assessment.**
"This looks like a short-term volatile spike, I'll wait" → fatal error.
The stop fires, the position closes, end of discussion.

**NEVER disable stops in any regime.**
There is no market condition where running without stops is acceptable.

## What the Agent SHOULD Do with Regime

**USE regime to block entry in choppy/volatile regimes.**
This is an entry filter decision, not a stop decision.

**USE regime to adjust add-trigger thresholds.**
Wider triggers in volatile regimes (less aggressive scaling).
Tighter triggers in trending regimes (more aggressive scaling).

**USE regime to scale position size via kelly_fraction.**
Smaller positions in volatile/uncertain regimes.
Larger positions in trending regimes (where edge is strongest).

## Mapping Scenarios to Regimes for Diagnosis

When analyzing Monte Carlo results across the 7 scenarios, group them:

```
TRENDING:  strong_bull + gradual_bull + bear
VOLATILE:  volatile_bull + flash_crash
CHOPPY:    sideways
MIXED:     bull_with_correction
```

If the strategy fails in the VOLATILE group but succeeds in TRENDING:
→ The entry signal fires on volatility spikes (false signals)
→ Fix: raise `entry_conf_threshold` or add ATR ratio filter

If the strategy fails in CHOPPY (sideways):
→ Expected behavior for trend-following — small losses are normal
→ Only worry if losses in sideways exceed 1× ATR per trade on average

If the strategy fails in TRENDING scenarios:
→ Serious problem — this is where edge should be strongest
→ Likely cause: trailing stop too tight (cuts winners) or entry too late
