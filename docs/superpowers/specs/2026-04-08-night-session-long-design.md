# Night Session Long Strategy

## Motivation

Return decomposition analysis (scripts/intraday_vs_gap.py) over 2020-03 to 2026-04 showed:

| Component | Cumulative Return | Sharpe |
|---|---|---|
| Night session intraday | +156.7% | 1.28 |
| Day session intraday | -4.8% | 0.00 |
| Gaps (all) | +58.4% | 0.90 |

Night session returns are positive every year (2020-2026), including 2022 bear market (+2.8%). This is a structural edge worth exploiting with leverage.

## Strategy Design

**Core logic**: Enter long at night session open, hold through session, exit at session close. Maximize lot size subject to drawdown constraints.

**File**: `src/strategies/short_term/trend_following/night_session_long.py`
**Timeframe**: 5-min bars
**Session**: Night only (15:00-05:00)

### Entry Policy — `NightSessionLongEntry`

- Enter long on the first 5-min bar after `entry_offset_min` minutes into the night session
- One entry per session maximum
- Block entry if already in position or if engine is halted

**Optional filters** (toggled by boolean params):
- `use_atr_filter=1`: Skip if current daily ATR > `atr_filter_mult` x rolling 20-day average ATR. Purpose: avoid extremely volatile nights.
- `use_trend_filter=1`: Skip if current price < EMA(`trend_ema_len`). Purpose: avoid entering long in bear trends.

**Position sizing**: Fixed `lots` parameter (1-10 contracts). This is the primary leverage lever.

**Initial stop**: `entry_price - atr_sl_mult * daily_ATR`

### Stop Policy — `NightSessionLongStop`

- Fixed ATR-based initial stop (set at entry)
- Optional trailing stop (`trail_enabled=1`): Once unrealized profit > `trail_trigger_atr * ATR`, trail stop at `highest_high - trail_atr_mult * ATR`
- Force close when bar time reaches `exit_before_close_min` minutes before session end (05:00)

### Add Policy

`NoAddPolicy` — no pyramiding. Leverage is achieved through lot size, not position adds.

### Parameters

| Param | Type | Default | Min | Max | Sweep Grid |
|---|---|---|---|---|---|
| lots | int | 1 | 1 | 10 | [1, 2, 3, 4, 5, 6, 8, 10] |
| entry_offset_min | int | 5 | 0 | 30 | [5, 10, 15] |
| exit_before_close_min | int | 5 | 5 | 15 | [5, 10] |
| atr_sl_mult | float | 2.0 | 0.5 | 4.0 | [1.0, 1.5, 2.0, 2.5, 3.0] |
| use_atr_filter | int | 0 | 0 | 1 | [0, 1] |
| atr_filter_mult | float | 2.0 | 1.2 | 3.0 | [1.5, 2.0, 2.5] |
| use_trend_filter | int | 0 | 0 | 1 | [0, 1] |
| trend_ema_len | int | 20 | 5 | 60 | [10, 20, 40] |
| trail_enabled | int | 0 | 0 | 1 | [0, 1] |
| trail_trigger_atr | float | 1.0 | 0.5 | 3.0 | [0.5, 1.0, 1.5] |
| trail_atr_mult | float | 1.5 | 0.5 | 3.0 | [1.0, 1.5, 2.0] |

### Indicator State

Minimal indicators needed:
- Rolling daily ATR (from `snapshot.atr["daily"]` — provided by engine)
- 20-bar rolling average ATR (for ATR filter)
- EMA of close prices (for trend filter)

ATR and EMA computed internally in an `_Indicators` class, updated once per bar.

## Optimization Plan

### Phase 1: Baseline
Run with defaults (1 lot, no filters, sl_mult=2.0) on real TX data 2020-2026.
Establish base Sharpe, MDD, trade count.

### Phase 2: Stop Optimization
Sweep `atr_sl_mult` x `trail_enabled` x `trail_trigger_atr` x `trail_atr_mult`.
Fix best stop config.

### Phase 3: Filter Evaluation
With best stop, sweep `use_atr_filter` x `atr_filter_mult` and `use_trend_filter` x `trend_ema_len`.
Keep filters only if they improve risk-adjusted return.

### Phase 4: Leverage Maximization
With best stop + filter config, sweep `lots` from 1 to 10.
Target: max lots where MDD <= 20% and Sharpe remains > 1.0.

### Phase 5: Validation
- Sensitivity check: +/- 20% param perturbation, Sharpe degradation < 30%
- Walk-forward: 3-fold expanding window, OOS Sharpe > 1.0

## Key Files

- `src/strategies/short_term/trend_following/night_session_long.py` — new strategy file
- `src/core/policies.py` — EntryPolicy, StopPolicy, NoAddPolicy ABCs
- `src/core/types.py` — MarketSnapshot, EntryDecision, Position, EngineConfig
- `src/strategies/_session_utils.py` — in_night_session(), in_force_close()
- `src/strategies/registry.py` — auto-discovers strategy by convention
- `src/strategies/short_term/mean_reversion/atr_mean_reversion.py` — reference template
