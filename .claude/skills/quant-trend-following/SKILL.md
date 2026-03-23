---
name: quant-trend-following
description: "Domain knowledge for trend-following strategy design. Read when diagnosing strategy weaknesses or forming optimization hypotheses."
license: MIT
metadata:
  author: quant-engine
  version: "1.0"
---

Core principles for designing and diagnosing trend-following strategies
on futures markets, specifically pyramid position-sizing strategies.

## Why Trend-Following Has Edge

Behavioral biases (herding, under/over-reaction) create non-normal
return distributions. Trend-following cuts the left tail. The edge is
NOT predictive accuracy — it is asymmetric payoff: many small losses,
few large wins.

**Critical implication**: A win rate of 35-45% is NORMAL and HEALTHY
for a trend-following pyramid strategy. Do NOT optimize to increase
win rate above 50%. Doing so almost always means cutting winners
early, which destroys the strategy's edge.

## Three Components Every Trend-Following System Needs

1. **Entry filter** — identifies when a trend is forming
   (not: predicts where price will go)
2. **Position sizing** — determines how much to risk per trade
3. **Exit logic** — two types:
   - Stop-loss: limits loss when wrong
   - Trend exit: captures profit when trend ends

These three components have **different failure modes** and must be
diagnosed separately. See `quant-stop-diagnosis` for exit logic.

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

## Entry Signal Categories

1. **Moving average crossover** — lagging but noise-filtered
2. **Price breakout (new N-day high)** — earlier, more false signals
3. **Volatility breakout** — enters when ATR expands (conviction signal)
4. **Combined (MA trend filter + breakout trigger)** — standard best practice

The entry signal should answer ONE question:
  "Is a trend currently in motion?"
Not: "Will the trend continue?" (prediction, not confirmation)

## This System's Entry Implementation

The pyramid strategy uses `entry_conf_threshold` (default 0.65) as a
confidence gate. The `EntryPolicy.should_enter()` receives a
`MarketSnapshot` and `MarketSignal` and returns an `EntryDecision`.

When diagnosing entry quality:
- If win rate < 30%: entry fires in choppy/volatile regimes (false signals)
- If win rate > 55%: entry is too selective or exits are too tight
- If MAE is high on winning trades: entry timing is late in the trend

## Relationship to Other Skills

- Stop/exit diagnosis → `quant-stop-diagnosis`
- Regime filtering for entries → `quant-regime`
- Position sizing after entry → `quant-pyramid-math`
