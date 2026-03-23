---
name: quant-pyramid-math
description: "Pyramid position sizing mathematics and Kelly criterion. Read when modifying add-trigger thresholds, lot schedules, or position sizes."
license: MIT
metadata:
  author: quant-engine
  version: "1.0"
---

Mathematics behind pyramid lot schedules, add-trigger thresholds,
Kelly sizing, and margin safety.

## Why the Lot Schedule Ratio Matters

Default lot_schedule: `[[3, 4], [2, 0], [1, 4], [1, 4]]`
This is a decreasing pyramid: 3+4=7 lots → 2 lots → 1+4=5 lots → 1+4=5 lots.
The initial position is the largest, each add-on is smaller.

**If the trend continues:**
  Initial lots capture the most points → largest profit.
  Each addition captures fewer points but with lower risk
  (because trailing stop protects initial lots at breakeven+).

**If the trend reverses after the 3rd add-on:**
  The 3rd add-on suffers most — but it is the smallest.
  Initial lots have stop at breakeven or profit.
  Net result: give back some gains, keep the core.

**Inverted pyramid (1:2:4) breaks this:**
  If trend reverses, the largest lots are at the highest-risk point.
  This is why inverse pyramiding destroys expectancy. Never do it.

## Add-Trigger Threshold Mathematics

```
add_trigger_atr[N] = floating_profit_required / ATR
```

Default: `add_trigger_atr = [4.0, 8.0, 12.0]`

The trigger should ensure that when adding at level N+1:
- All existing lots are protected at breakeven or better
- New lot's potential loss ≤ expected gain from trend continuation

**Formula for minimum safe trigger at level N:**
```
trigger_N ≥ (N × stop_atr_mult)
```

At `stop_atr_mult=1.5`:
```
Level 1: trigger ≥ 1 × 1.5 = 1.5 ATR minimum  (default: 4.0 ✓)
Level 2: trigger ≥ 2 × 1.5 = 3.0 ATR minimum  (default: 8.0 ✓)
Level 3: trigger ≥ 3 × 1.5 = 4.5 ATR minimum  (default: 12.0 ✓)
```

The defaults are well above the minimum. Tightening to the minimum
increases trade frequency but reduces the safety cushion.

**When to tighten triggers** (reduce values):
- In strongly trending regime where momentum is confirmed
- When `trail_atr_mult` provides strong protection for existing lots

**When to widen triggers** (increase values):
- In volatile or uncertain regimes
- When the strategy has high whipsaw rate on add-ons

## Kelly Criterion for Position Sizing

**Full Kelly fraction:**
```
f* = (p × b - q) / b
where p = win probability, q = 1-p, b = avg_win / avg_loss
```

For trend-following with `win_rate=0.42`, `avg_win/avg_loss=2.5`:
```
f* = (0.42 × 2.5 - 0.58) / 2.5 = 0.188 = 18.8%
```

**ALWAYS use fractional Kelly in practice:**
```
Full Kelly:     f*    = 18.8%   (causes large drawdowns)
Half Kelly:     f*/2  =  9.4%   (reasonable for single strategy)
Quarter Kelly:  f*/4  =  4.7%   (conservative, recommended for new strategies)
```

Default: `kelly_fraction = 0.25` (quarter Kelly).

Kelly scales position size dynamically with edge strength. When the
model's estimated win rate approaches 0.5, Kelly approaches zero.
This is correct: don't trade when you have no edge.

**When optimizing kelly_fraction:**
- Safe range: 0.10 – 0.35
- Below 0.10: too conservative, leaves money on the table
- Above 0.35: too aggressive, large drawdowns during losing streaks
- NEVER exceed 0.50 (full Kelly) — this is the mathematical maximum

## Margin Safety Mathematics

At any point in the pyramid:
```
margin_used  = Σ(lots × margin_per_contract)
equity       = initial_capital + unrealized_pnl + realized_pnl
margin_ratio = margin_used / equity
```

**Hard limits (from TAIFEX rules):**
```
margin_ratio > 0.50 → STOP adding, consider reducing positions
margin_ratio > 0.75 → FORCE reduce to 0.50
risk_indicator < 0.25 → broker force-liquidates WITHOUT WARNING
```

Default: `margin_limit = 0.50`

**Safe pyramid expansion rule:**
Only add lots if projected margin_ratio after addition < 0.40
(keeping 0.10 buffer below the 0.50 limit for adverse moves).

## Interaction with Stop Parameters

The pyramid's risk profile depends on `stop_atr_mult`:
- Wider stops (stop_atr_mult=2.0) → more risk per lot → fewer safe levels
- Tighter stops (stop_atr_mult=1.0) → less risk per lot → more whipsaws

When changing stops, re-verify that `add_trigger_atr` still satisfies:
```
trigger_N ≥ N × stop_atr_mult
```

If you increase `stop_atr_mult` from 1.5 to 2.0, the minimum triggers
become 2.0, 4.0, 6.0 — the defaults still satisfy this, but barely.
