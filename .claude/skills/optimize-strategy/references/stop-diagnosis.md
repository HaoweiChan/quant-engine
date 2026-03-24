# Stop-Loss Design and Diagnosis

The stop architecture, diagnosis patterns for common backtest
failures, and parameter interaction rules. Covers both daily and
intraday timeframes.

## The 3-Layer Stop Architecture (Daily Strategies)

This system's `StopPolicy` implements three layers:

**Layer 1 — Initial stop**
```
stop_price = entry_price - stop_atr_mult x ATR(daily)
```
Purpose: Limits loss if the entry is simply wrong.
Default: `stop_atr_mult = 1.5`

**Layer 2 — Breakeven stop**
Moves stop to entry_price when floating profit exceeds 1x ATR.
Purpose: Converts open trade to "free trade" — eliminates loss risk.

**Layer 3 — Trailing stop (Chandelier Exit)**
```
trail_stop = highest_high(trail_lookback) - trail_atr_mult x ATR
```
Purpose: Locks in trend profit, exits when trend ends.
Default: `trail_atr_mult = 3.0`, `trail_lookback = 22`

Each layer has a distinct purpose. Diagnose them separately.

## The 4-Layer Stop Architecture (Intraday Strategies)

Intraday strategies add a **Layer 0 — Time Stop** and replace
minute-bar rolling lookbacks with session-anchored references.

**Layer 0 — Time stop (MANDATORY for intraday)**
```
if current_time >= session_end - buffer_minutes:
    flatten ALL positions
```
Purpose: Eliminates overnight gap risk. There is NO intraday strategy
where holding past session end is acceptable unless explicitly designed
as a multi-session strategy.

TAIFEX time stops:
```
Day session close:   13:10 (5 min before 13:15 close)
Night session close: 04:25 (5 min before 04:30 close)
```

**Layer 1 — Initial stop (session-anchored)**
```
stop_price = entry_price - stop_mult x IB_range
# OR
stop_price = entry_price - stop_mult x session_ATR_adjusted
```
Do NOT use raw ATR(14) on 1-min bars — a 14-period lookback is only
14 minutes, which is pure microstructure noise.

Instead, anchor to:
- **Initial Balance (IB) range**: high-low of first 30 min
- **Session VWAP bands**: entry_price - N x session_VWAP_stdev
- **Higher-timeframe ATR**: ATR computed on 15-min or 60-min bars

**Layer 2 — Breakeven stop** (same logic as daily)

**Layer 3 — Trailing stop (session-anchored)**
```
trail_stop = session_high - trail_mult x IB_range
# OR
trail_stop = VWAP - trail_sigma x VWAP_stdev
```
`trail_lookback = 22` on 1-min bars means 22 minutes — this is
trailing on microstructure noise, NOT price trends. For intraday
trailing, use session high/low or VWAP bands instead of rolling
minute-bar highs.

## Diagnosis Patterns: SYMPTOM -> CAUSE -> FIX

### Pattern 1: High win rate (>60%) but low total PnL
**CAUSE**: Trailing stop too tight — cutting winners short.
**FIX**: Increase `trail_atr_mult` (e.g., 3.0 -> 4.0) or increase
`trail_lookback` to smooth the trailing high.

### Pattern 2: Low win rate (<30%) with many small losses
**CAUSE**: Initial stop too tight — normal volatility triggers exits.
**FIX**: Increase `stop_atr_mult` (e.g., 1.5 -> 2.0). Also check if
the ATR period is too short (noisy ATR estimate).

### Pattern 3: Good win rate but unacceptable max drawdown
**CAUSE**: Stops work for individual trades but not portfolio-level risk.
**DIAGNOSIS**: Count exits by layer:
- If Layer 1 > 70% of all exits -> stops are too tight
- If Layer 3 triggers after large gains -> normal behavior
**FIX**: If Layer 1 dominates, widen initial stop. If drawdown comes
from correlated positions, reduce `max_levels` or tighten `add_trigger_atr`.

### Pattern 4: Works in strong_bull but fails in sideways/choppy
**CAUSE**: Entry signal fires in non-trending markets (false breakouts).
**FIX**: Add regime filter to `EntryPolicy`, NOT to stop logic.
Stop logic must remain regime-agnostic. See `references/regime.md`.

### Pattern 5: Large losses on flash_crash scenario
**CAUSE**: Gap jumps past the stop level — stop executes at gap price,
not at the stop price.
**FIX**: Accept this as structural risk. Mitigate via:
- Smaller `max_levels` to reduce exposure
- Lower `kelly_fraction` to size positions conservatively
- Do NOT tighten the stop — that increases whipsaws in normal markets

### Pattern 6: Strategy profitable in backtest but fails live (intraday)
**CAUSE**: Backtest does not simulate bid-ask bounce or latency.
Intraday strategies that trade frequently accumulate slippage that
does not appear in mid-price backtests.
**FIX**: Add execution simulation — model latency (50-200ms for retail),
bid-ask spread (1 tick minimum for TAIFEX TX), and partial fills.
Require that backtest Sharpe remains > 0.5 AFTER adding 1-tick
round-trip slippage per trade.

### Pattern 7: Consistent losses during midday / overnight lull
**CAUSE**: Strategy trades in low-volatility time windows where
spreads widen and noise dominates signal.
**FIX**: Add time-of-day filter to entry logic — block entries during
known low-vol windows (10:30-12:00, 20:00-01:00 for TAIFEX).
Do NOT adjust stops — this is an entry problem, not a stop problem.

## Parameter Interaction Rules

**Hard constraint**: `trail_atr_mult > stop_atr_mult`

If `trail_atr_mult <= stop_atr_mult`, the trailing stop will trigger
immediately after entry. This is a logic error, not a parameter choice.

**Safe parameter ranges for daily pyramid strategy:**

```
stop_atr_mult:   1.0 - 2.5    (default 1.5)
trail_atr_mult:  2.0 - 5.0    (default 3.0)
trail_lookback:  10 - 44       (default 22)
```

Recommended starting point: `stop_atr_mult=1.5`, `trail_atr_mult=3.0`

**Safe parameter ranges for intraday strategies:**

```
stop_ib_mult:     0.3 - 1.5   (default 0.5, in IB range multiples)
trail_vwap_sigma: 1.0 - 3.0   (default 1.5, in VWAP stdev units)
time_stop_buffer: 3 - 10 min  (default 5, minutes before session end)
```

## The Golden Rule of Stop Design

Stop logic must be completely independent of the prediction model.
A stop is triggered by PRICE, never by signal confidence or regime.

If you are considering "don't stop out when the model says high
confidence" — you are making a category error. Stop immediately.

Stops protect capital. Predictions allocate capital. Never mix them.

## How to Use with MCP Tools

1. `run_monte_carlo` baseline -> read the win rate, P50/P25 PnL, max DD
2. Match the metrics pattern against the 7 patterns above
3. Form a hypothesis about which layer is failing
4. Use `run_parameter_sweep` to test the fix (e.g., trail_atr_mult=[2.5, 3.0, 3.5, 4.0, 4.5])
5. Validate with `run_stress_test` — stops must survive extreme scenarios
