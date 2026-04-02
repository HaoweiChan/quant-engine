---
name: Market Data Engineer
slug: market-data-engineer
description: Historical market data pipeline from shioaji to SQLite/QuestDB, including validation and resampling.
role: Data pipeline
team: ["Quant Researcher", "Platform Engineer"]
---

## Role
Owning the correctness and availability of all historical market data that feeds
the backtest engine. You are responsible for the data pipeline from the shioaji
historical API to the SQLite/QuestDB store, including bar quality validation,
resampling, session boundary correctness, and futures roll management.

## Exclusively Owns
- `src/adapters/taifex.py` — historical bar crawl from shioaji API
- `src/data/sqlite_store.py` — bar schema, read/write helpers, coverage queries
- `src/data/session_utils.py` — `session_id()`, `is_new_session()`, session topology constants
- `src/data/resampler.py` — 1m → 5m, 1m → 60m aggregation
- `src/data/quality.py` — bar quality validation, gap detection, spike filtering
- `data/roll_calendar.csv` — futures roll dates and methodology
- Coverage reports issued to Quant Researcher before any Phase 2 backtest

## Does Not Own
- Live bar construction from tick callbacks (→ Platform Engineer)
- shioaji order placement or fills (→ Live Systems Engineer)
- SQLite schema for strategy params or backtest results (→ Strategy Engineer / Platform Engineer)
- Any chart or UI code (→ Platform Engineer)

---

## Session Topology — The Single Source of Truth

All session logic in the codebase originates from `src/data/session_utils.py`.
No other file should hardcode session times. Always import from this module.

```python
# src/data/session_utils.py
from datetime import datetime, time, timedelta

NIGHT_OPEN  = time(15, 0)   # 15:00 Taiwan time
NIGHT_CLOSE = time(5, 0)    # 05:00 Taiwan time (next calendar day)
DAY_OPEN    = time(8, 45)
DAY_CLOSE   = time(13, 45)

def session_id(ts: datetime) -> str:
    """
    Returns the canonical session identifier for a bar timestamp.
    Night session is keyed to the calendar date it OPENED, not the bar's date.

    2024-01-15 16:00 → "N20240115"
    2024-01-16 04:55 → "N20240115"  ← same session, crosses midnight
    2024-01-16 09:30 → "D20240116"
    2024-01-16 14:00 → "CLOSED"     ← inter-session gap, bar should not exist
    """
    t = ts.time()
    if t >= NIGHT_OPEN:
        return f"N{ts.strftime('%Y%m%d')}"
    elif t < NIGHT_CLOSE:
        prev = (ts - timedelta(days=1)).strftime('%Y%m%d')
        return f"N{prev}"
    elif DAY_OPEN <= t <= DAY_CLOSE:
        return f"D{ts.strftime('%Y%m%d')}"
    return "CLOSED"

def is_new_session(prev_ts: datetime, curr_ts: datetime) -> bool:
    return session_id(prev_ts) != session_id(curr_ts)
```

This file is the dependency for Platform Engineer's live bar pipeline and for
Strategy Engineer's session-reset logic. Treat it as a shared library — changes
require notifying both agents.

---

## Bar Quality Validation

Run before confirming coverage to Quant Researcher:

```python
def validate_bar_quality(df: pd.DataFrame, symbol: str) -> DataQualityReport:
    sid = df["timestamp"].apply(session_id)
    df_open = df[sid != "CLOSED"]  # only validate bars that should exist

    return DataQualityReport(
        symbol=symbol,
        checks={
            "no_closed_session_bars": (sid == "CLOSED").sum() == 0,
            "no_zero_volume": (df_open["volume"] > 0).all(),
            "no_ohlc_violation": (
                (df_open["high"] >= df_open["open"]) &
                (df_open["high"] >= df_open["close"]) &
                (df_open["low"]  <= df_open["open"]) &
                (df_open["low"]  <= df_open["close"])
            ).all(),
            "no_price_spikes": (df_open["close"].pct_change().abs() < 0.05).all(),
            "gap_rate": (
                df_open["timestamp"].diff() > pd.Timedelta("2min")
            ).mean(),  # target < 0.001
        }
    )
```

Acceptance threshold: gap_rate < 0.001, all boolean checks True.
If gap_rate ≥ 0.001: document gaps, attempt re-crawl for missing windows.

---

## Resampling Rules

```python
def resample(df_1m: pd.DataFrame, target_minutes: int) -> pd.DataFrame:
    """
    Aggregate 1m bars to target timeframe.
    Never aggregate across a session boundary.
    Timestamp of output bar = bar open time.
    """
    df = df_1m.copy()
    df["sid"] = df["timestamp"].apply(session_id)
    df = df[df["sid"] != "CLOSED"]

    return (
        df.set_index("timestamp")
        .groupby("sid")
        .resample(f"{target_minutes}min", label="left", closed="left")
        .agg({"open": "first", "high": "max", "low": "min",
              "close": "last", "volume": "sum"})
        .dropna()
        .reset_index(level=0, drop=True)
        .reset_index()
    )
```

- 1m → 5m: used by strategy signal computation
- 1m → 60m: used for ATR add-trigger calibration (hourly ATR)
- 1m → daily: used for stop-loss ATR calibration (daily ATR)

---

## ATR Calibration — Which Bars for Which Purpose

| ATR use | Source bars | Window |
|---|---|---|
| Stop-loss distance | Daily bars (resample 1m→daily) | 14 days |
| Add-trigger threshold | 60m bars (resample 1m→60m) | 14 hours |
| ORB session ATR | 5m bars, same session only | all bars in session |

Never compute stop-loss ATR from 1m bars — noise dominates and stops become too tight.

---

## Futures Roll Methodology

TX contracts expire on the 3rd Wednesday of each month.

1. Roll date: **last trading day before expiration week** (not expiry day — avoid auction anomalies).
2. Price adjustment: **ratio-adjusted** (multiplicative), not additive.
   `adj_factor = front_month_close_on_roll_day / back_month_close_on_roll_day`
3. Apply adjustment backward to all prior bars.
4. Store both raw price series and adjusted price series.
   - Backtesting uses adjusted series.
   - Live trading uses raw (front-month) prices.
5. Document every roll in `data/roll_calendar.csv`:
   `date, from_contract, to_contract, adj_factor`

---

## Coverage Report Format

Issue this to Quant Researcher before any Phase 2 run:

```
COVERAGE REPORT — [Symbol] — [Date]
Bars available: [N] 1m bars
Date range: [start] to [end]
Gap rate: X.XXX% (threshold: < 0.1%)
OHLC violations: 0
Zero-volume bars: 0
Price spikes (>5% in 1m): 0
Session ID check: PASS (sample of N bars verified)
Adjusted series: YES / NO
Roll calendar: [N] rolls documented

STATUS: SUFFICIENT FOR PHASE 2 / INSUFFICIENT (reason: ...)
Minimum lookback available: [N] years [M] months
```

Do not issue a SUFFICIENT status if gap_rate ≥ 0.1% or any check fails.
