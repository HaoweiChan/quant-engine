# Market Regime Detection and Adaptation

How to identify market regimes and which parameters to adapt per regime.

## The Four Regimes

### TRENDING
**Characteristics:** Directional move > 2x ATR over 20 bars, low
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

## Simple Regime Classifier — Daily Timeframe

Using only ATR ratio and trend score:

```
atr_ratio   = ATR(14) / ATR(63)    # short-term vs long-term vol
trend_score = abs(close - SMA(20)) / ATR(14)  # distance from mean in ATR units

if atr_ratio > 1.5 and trend_score > 1.5:  -> TRENDING
if atr_ratio > 1.5 and trend_score < 0.5:  -> VOLATILE
if atr_ratio < 0.7:                         -> CHOPPY
else:                                        -> UNCERTAIN
```

This classifier uses data already available in the strategy's
`MarketSnapshot`. No external indicators needed.

## Intraday Regime Classifier — Diurnal U-Shape Awareness

**WARNING:** The daily classifier above will produce FALSE regime labels
when applied directly to intraday bars. Intraday volatility follows a
strict diurnal "U-shape" — high volatility at the open and close, low
volatility at midday. Using raw ATR on 1-min bars will falsely label
every morning as VOLATILE/TRENDING and every lunch hour as CHOPPY.

### Seasonality-Adjusted Volatility

The intraday classifier MUST normalize current volatility relative to
the **historical average for that specific time-of-day slot**:

```
tod_slot        = current_bar_time rounded to 15-min bucket
atr_current     = ATR(14) on 1-min bars
atr_tod_avg     = historical average ATR(14) at this tod_slot
                  (rolling 20-session lookback)
atr_ratio_adj   = atr_current / atr_tod_avg

if atr_ratio_adj > 1.5 and trend_score_adj > 1.5:  -> TRENDING
if atr_ratio_adj > 1.5 and trend_score_adj < 0.5:  -> VOLATILE
if atr_ratio_adj < 0.7:                              -> CHOPPY
else:                                                 -> UNCERTAIN
```

### Microstructure Metrics for Intraday

Replace simple SMA distance with session-anchored metrics:

```
vwap_distance   = (close - session_VWAP) / ATR(14)   # replaces SMA distance
order_imbalance = (bid_volume - ask_volume) / total_volume  # if available
ib_range        = initial_balance_high - initial_balance_low  # first 30 min
ib_ratio        = current_range / ib_range
```

**Initial Balance (IB):** The first 30 minutes of the session establish
the IB range. Breakouts beyond IB high/low are stronger intraday trend
signals than raw ATR expansion.

### TAIFEX Session Structure (for time-of-day classification)

```
Day session:    09:00 - 13:15  (255 min, ~255 bars)
Night session:  15:15 - 04:30  (795 min, ~795 bars)

High vol windows:  09:00-09:30 (open), 13:00-13:15 (close),
                   15:15-15:45 (night open), 04:00-04:30 (night close)
Low vol windows:   10:30-12:00 (midday), 20:00-01:00 (overnight lull)
```

## Regime-Parameter Target Table — Daily Strategies

Use these as soft targets during optimization — not hard-coded values.
If `run_parameter_sweep` finds optimal values far from this table,
investigate why before accepting.

```
Parameter          TRENDING  VOLATILE  CHOPPY   UNCERTAIN
-----------------  --------  --------  -------  ---------
stop_atr_mult      1.5       2.0       N/A      1.8
trail_atr_mult     3.0       4.5       N/A      3.5
add_trigger[0]     3.0       6.0       N/A      5.0
max_levels         4         2         0        1
kelly_fraction     0.25      0.10      0.00     0.15
entry_conf         0.60      0.75      1.00*    0.70
```

## Regime-Parameter Target Table — Intraday Strategies

Intraday strategies use session-relative anchors instead of daily ATR.
Stop and trail values reference IB range or session-VWAP bands.

```
Parameter             TRENDING  VOLATILE  CHOPPY   UNCERTAIN
--------------------  --------  --------  -------  ---------
stop (IB multiples)   0.5xIB    1.0xIB    N/A      0.7xIB
trail (VWAP bands)    1.5s      2.5s      N/A      2.0s
time_stop (minutes)   session   session   N/A      session
max_levels            2         1         0        1
kelly_fraction        0.20      0.08      0.00     0.12
entry_conf            0.55      0.70      1.00*    0.65
win_rate_target       55-65%    50-55%    N/A      50-60%
reward_risk_target    0.8-1.5   0.5-1.0   N/A      0.6-1.2
```

Note: Intraday strategies accept **higher win rate, lower RR** profiles
compared to daily trend-following. A 60% win rate with 0.8 RR is
structurally valid for intraday — do NOT force a daily trend-following
payoff profile onto intraday strategies.

*`entry_conf=1.00` for CHOPPY effectively blocks all entries (no entry
will have confidence = 1.0). This is the intended behavior: do not
trade in a choppy regime.

## What the Agent MUST NOT Do with Regime

**NEVER change stop-loss execution based on regime.**
Stops execute on price. Period. Regime is irrelevant once a stop is set.

**NEVER hold a position past its stop because of regime assessment.**
"This looks like a short-term volatile spike, I'll wait" -> fatal error.
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
-> The entry signal fires on volatility spikes (false signals)
-> Fix: raise `entry_conf_threshold` or add ATR ratio filter

If the strategy fails in CHOPPY (sideways):
-> Expected behavior for trend-following — small losses are normal
-> Only worry if losses in sideways exceed 1x ATR per trade on average

If the strategy fails in TRENDING scenarios:
-> Serious problem — this is where edge should be strongest
-> Likely cause: trailing stop too tight (cuts winners) or entry too late
