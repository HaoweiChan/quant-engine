---
name: quant-stop-diagnosis
description: "Stop-loss design and backtest diagnosis patterns. Read when diagnosing why a strategy loses money or when modifying stop parameters."
license: MIT
metadata:
  author: quant-engine
  version: "1.0"
---

The 3-layer stop architecture, diagnosis patterns for common backtest
failures, and parameter interaction rules.

## The 3-Layer Stop Architecture

This system's `StopPolicy` implements three layers:

**Layer 1 — Initial stop**
```
stop_price = entry_price - stop_atr_mult × ATR(daily)
```
Purpose: Limits loss if the entry is simply wrong.
Default: `stop_atr_mult = 1.5`

**Layer 2 — Breakeven stop**
Moves stop to entry_price when floating profit exceeds 1× ATR.
Purpose: Converts open trade to "free trade" — eliminates loss risk.

**Layer 3 — Trailing stop (Chandelier Exit)**
```
trail_stop = highest_high(trail_lookback) - trail_atr_mult × ATR
```
Purpose: Locks in trend profit, exits when trend ends.
Default: `trail_atr_mult = 3.0`, `trail_lookback = 22`

Each layer has a distinct purpose. Diagnose them separately.

## Diagnosis Patterns: SYMPTOM → CAUSE → FIX

### Pattern 1: High win rate (>60%) but low total PnL
**CAUSE**: Trailing stop too tight — cutting winners short.
**FIX**: Increase `trail_atr_mult` (e.g., 3.0 → 4.0) or increase
`trail_lookback` to smooth the trailing high.

### Pattern 2: Low win rate (<30%) with many small losses
**CAUSE**: Initial stop too tight — normal volatility triggers exits.
**FIX**: Increase `stop_atr_mult` (e.g., 1.5 → 2.0). Also check if
the ATR period is too short (noisy ATR estimate).

### Pattern 3: Good win rate but unacceptable max drawdown
**CAUSE**: Stops work for individual trades but not portfolio-level risk.
**DIAGNOSIS**: Count exits by layer:
- If Layer 1 > 70% of all exits → stops are too tight
- If Layer 3 triggers after large gains → normal behavior
**FIX**: If Layer 1 dominates, widen initial stop. If drawdown comes
from correlated positions, reduce `max_levels` or tighten `add_trigger_atr`.

### Pattern 4: Works in strong_bull but fails in sideways/choppy
**CAUSE**: Entry signal fires in non-trending markets (false breakouts).
**FIX**: Add regime filter to `EntryPolicy`, NOT to stop logic.
Stop logic must remain regime-agnostic. See `quant-regime`.

### Pattern 5: Large losses on flash_crash scenario
**CAUSE**: Gap jumps past the stop level — stop executes at gap price,
not at the stop price.
**FIX**: Accept this as structural risk. Mitigate via:
- Smaller `max_levels` to reduce exposure
- Lower `kelly_fraction` to size positions conservatively
- Do NOT tighten the stop — that increases whipsaws in normal markets

## Parameter Interaction Rules

**Hard constraint**: `trail_atr_mult > stop_atr_mult`

If `trail_atr_mult ≤ stop_atr_mult`, the trailing stop will trigger
immediately after entry. This is a logic error, not a parameter choice.

**Safe parameter ranges for the pyramid strategy:**

```
stop_atr_mult:   1.0 – 2.5    (default 1.5)
trail_atr_mult:  2.0 – 5.0    (default 3.0)
trail_lookback:  10 – 44       (default 22)
```

Recommended starting point: `stop_atr_mult=1.5`, `trail_atr_mult=3.0`

## The Golden Rule of Stop Design

Stop logic must be completely independent of the prediction model.
A stop is triggered by PRICE, never by signal confidence or regime.

If you are considering "don't stop out when the model says high
confidence" — you are making a category error. Stop immediately.

Stops protect capital. Predictions allocate capital. Never mix them.

## How to Use with MCP Tools

1. `run_monte_carlo` baseline → read the win rate, P50/P25 PnL, max DD
2. Match the metrics pattern against the 5 patterns above
3. Form a hypothesis about which layer is failing
4. Use `run_parameter_sweep` to test the fix (e.g., trail_atr_mult=[2.5, 3.0, 3.5, 4.0, 4.5])
5. Validate with `run_stress_test` — stops must survive extreme scenarios
