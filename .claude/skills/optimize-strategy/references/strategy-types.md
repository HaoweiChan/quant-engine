# Strategy Types and Entry Design

Core principles for designing and diagnosing trading strategies
on futures markets. Covers both daily trend-following (pyramid) and
intraday strategies (breakout, mean-reversion, statistical arb).

## Strategy Typology — Read This First

Before applying any guidance below, classify the strategy:

| Type | Timeframe | Edge Source | Expected Profile |
|------|-----------|-------------|-----------------|
| Trend-following | Daily | Asymmetric payoff | 35-45% WR, 2.5+ RR |
| Intraday breakout | Intraday | Momentum continuation | 45-55% WR, 1.0-2.0 RR |
| Intraday mean-reversion | Intraday | Overshoot correction | 55-65% WR, 0.6-1.0 RR |
| Statistical arb / liquidity | Intraday | Spread capture | 60-70% WR, 0.3-0.8 RR |

**The guidance in this file defaults to daily trend-following.**
Intraday-specific sections are marked explicitly. Do NOT force a
daily trend-following payoff profile onto intraday strategies.

## Why Trend-Following Has Edge (Daily)

Behavioral biases (herding, under/over-reaction) create non-normal
return distributions. Trend-following cuts the left tail. The edge is
NOT predictive accuracy — it is asymmetric payoff: many small losses,
few large wins.

**Critical implication for daily strategies**: A win rate of 35-45%
is NORMAL and HEALTHY for a trend-following pyramid strategy. Do NOT
optimize to increase win rate above 50%. Doing so almost always means
cutting winners early, which destroys the strategy's edge.

## Why Intraday Strategies Have Different Edge

Intraday strategies are **structurally bounded by the session clock**.
You cannot mathematically "let profits run forever" to achieve a 3.0+ RR
because the session ends. This is a hard physical constraint.

**Critical implication for intraday**: Accept higher win rate, lower RR
profiles. A 60% win rate with 0.8 RR is structurally valid and
profitable for intraday mean-reversion. Do NOT reject it because
daily trend-following says "low win rate is healthy".

Intraday edge sources:
- **Mean reversion**: Outside the first and last 30 min, intraday
  markets are heavily mean-reverting. Price tends to revert to VWAP.
- **Opening Range Breakout (ORB)**: First 15-30 min establish range;
  breakouts beyond this range have momentum continuation probability.
- **Session structure**: Predictable volume/volatility patterns
  (U-shape) create exploitable timing edges.

## Three Components Every Strategy Needs

1. **Entry filter** — identifies when a trade setup is forming
   (not: predicts where price will go)
2. **Position sizing** — determines how much to risk per trade
3. **Exit logic** — two types:
   - Stop-loss: limits loss when wrong
   - Trend/target exit: captures profit when edge is exhausted

These three components have **different failure modes** and must be
diagnosed separately. See `references/stop-diagnosis.md` for exit logic.

## Entry Signal Quality Metrics (Use These, Not PnL)

- **Maximum Adverse Excursion (MAE)**: how far against you before winning.
  A good entry has low MAE — it works almost immediately.
- **Time-in-trade**: winning trades resolve faster than losing ones.
- **Entry efficiency**: `(close - low) / (high - low)` on entry bar.
  Higher = entered closer to bar's best price.

## ATR as the Universal Unit of Measurement

All thresholds, stops, and triggers should be expressed in ATR
multiples, NOT fixed points. Markets change volatility regime over
time; fixed-point thresholds become too tight or too loose.

ATR benchmarks for TAIFEX TX (index ~20,000, start_price in PRESETS):

```
Daily ATR:    300-450 points   (normal regime)
              150-200 points   (compressed, pre-breakout)
              500-800 points   (high volatility / crisis)
Hourly ATR:   60-100 points
4H ATR:       120-180 points
```

If a strategy uses fixed stops of 200 points, it implicitly assumes
ATR ≈ 133 (at 1.5× multiplier). Verify this matches actual ATR.

## Entry Signal Categories — Daily

1. **Moving average crossover** — lagging but noise-filtered
2. **Price breakout (new N-day high)** — earlier, more false signals
3. **Volatility breakout** — enters when ATR expands (conviction signal)
4. **Combined (MA trend filter + breakout trigger)** — standard best practice

The daily entry signal should answer ONE question:
  "Is a trend currently in motion?"
Not: "Will the trend continue?" (prediction, not confirmation)

## Entry Signal Categories — Intraday

1. **Opening Range Breakout (ORB)** — price breaks above/below the
   Initial Balance (first 15-30 min). Replaces "N-day high" breakout.
2. **VWAP reversion** — price deviates > N sigma from session VWAP,
   then shows reversal candle. Core mean-reversion signal.
3. **Session VWAP trend** — price consistently above/below VWAP with
   volume confirmation. Intraday equivalent of MA trend filter.
4. **Order flow imbalance** — bid/ask volume ratio signals directional
   pressure (requires Level 2 data or proxy).

The intraday entry signal should answer:
  "Is price dislocated from fair value (mean-reversion)?" OR
  "Has the session established directional momentum (breakout)?"

**Time-of-day gates for intraday entries:**
```
High-edge windows:  09:00-09:30 (ORB), 13:00-13:15 (close drive)
                    15:15-15:45 (night ORB)
Low-edge windows:   10:30-12:00 (midday noise)
                    20:00-01:00 (overnight lull)
```
Block entries in low-edge windows unless the strategy is specifically
designed for those periods with validated edge.

## This System's Entry Implementation

The pyramid strategy uses `entry_conf_threshold` (default 0.65) as a
confidence gate. The `EntryPolicy.should_enter()` receives a
`MarketSnapshot` and `MarketSignal` and returns an `EntryDecision`.

When diagnosing entry quality:
- If win rate < 30%: entry fires in choppy/volatile regimes (false signals)
- If win rate > 55%: entry is too selective or exits are too tight
- If MAE is high on winning trades: entry timing is late in the trend

## Cross-References

- Stop/exit diagnosis: `references/stop-diagnosis.md`
- Regime filtering for entries: `references/regime.md`
- Position sizing after entry: `references/position-sizing.md`
