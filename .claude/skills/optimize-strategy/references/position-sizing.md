# Position Sizing and Pyramid Mathematics

Mathematics behind pyramid lot schedules, add-trigger thresholds,
Kelly sizing, and margin safety. Covers both daily and intraday.

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

## Margin Safety Mathematics (Daily Strategies)

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

## Intraday Margin and Day-Trading Discounts

Brokers typically offer **reduced margin for intraday positions** that are
guaranteed to be flat by session end. TAIFEX day-trading margin is often
50% of overnight maintenance margin (varies by broker and product).

```
margin_per_contract_intraday = margin_per_contract_overnight × discount_factor
discount_factor: typically 0.50 (check with broker)
```

**This changes the denominator in all capital allocation formulas:**
```
# Daily strategy margin check:
margin_ratio = Σ(lots × margin_overnight) / equity

# Intraday strategy margin check:
margin_ratio = Σ(lots × margin_overnight × discount_factor) / equity
```

**CRITICAL**: The margin discount enables larger positions, but the risk
per point is UNCHANGED. A 2-lot intraday position loses the same per-tick
as a 2-lot overnight position. Do NOT confuse cheaper margin with lower
risk. Always size intraday positions based on risk (ATR × lots), not
available margin.

**Intraday margin safety rule:**
Only add lots if projected margin_ratio after addition < 0.30
(tighter than daily's 0.40 buffer because intraday moves can be fast
and margin calls execute faster during session hours).

## Capacity Constraints (Intraday Pyramiding)

Intraday pyramiding faces a hard constraint that daily strategies rarely
encounter: **top-of-book liquidity**.

```
max_safe_lots_per_add = top_of_book_depth / 2
```

Where `top_of_book_depth` is the typical number of contracts at best
bid/ask. For TAIFEX TX:
```
Normal hours:    50-200 contracts at best bid/ask
Opening/close:   100-500 contracts (higher liquidity)
Overnight lull:  10-50 contracts (thin book)
```

**Why this matters for pyramiding:**
- Adding 10 lots when top-of-book is 20 contracts → 50% of visible
  liquidity consumed → significant market impact and slippage
- Adding 10 lots when top-of-book is 200 contracts → 5% of visible
  liquidity → negligible impact

**Intraday max_levels must be capped by liquidity, not just margin:**
```
effective_max_levels = min(
    max_levels_from_margin,
    max_levels_from_liquidity
)
```

Where:
```
max_levels_from_liquidity = floor(
    top_of_book_depth × 0.25 / lots_per_level
)
```

The 0.25 factor ensures each add consumes no more than 25% of visible
depth. Exceeding this threshold degrades fill quality and reveals
the strategy's intentions to other participants.

**Safe intraday pyramid parameters:**
```
max_levels:  1-2  (rarely 3, never 4 for retail accounts)
lot_per_add: ≤ 25% of typical top-of-book depth
time_gate:   no adds in last 30 min of session (liquidity thins)
```

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
