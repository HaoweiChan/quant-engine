---
name: taifex-chart-rendering
description: "Correct time handling for TAIFEX futures charting: session topology, bar indexing, and TradingView Lightweight Charts configuration to eliminate phantom gaps."
license: MIT
metadata:
  author: quant-engine
  version: "1.0"
---

## The Core Problem
TAIFEX futures do NOT trade continuously. Standard charting libraries assume
continuous time axes. Applying them naively to TAIFEX data produces:
- Phantom gaps stretched across the chart (13:45→15:00 inter-session gap)
- Compressed bars during low-volume periods
- Wrong date labels (a bar at 04:55 on Jan 16 belongs to the Jan 15 session)
- Incorrect OHLC candle sizing during opening auction

This skill defines the canonical patterns for correct TAIFEX chart rendering.

---

## Session Topology (Memorize This)

```
Calendar Day N:
  15:00 ──────────────────────────────────────────── Night Session Opens
  ...
Calendar Day N+1:
  05:00 ──── Night Session Closes  [GAP: 3h45m]
  08:45 ──── Day Session Opens
  13:45 ──── Day Session Closes    [GAP: 1h15m]
  15:00 ──── Night Session Opens (Day N+1)
```

**Key rules:**
1. A bar timestamped `2024-01-16 04:55` belongs to the session that opened `2024-01-15 15:00`.
   Its session label is `N20240115`, NOT `N20240116`.
2. Bars between `05:00–08:45` and `13:45–15:00` DO NOT EXIST. They are gaps, not zeros.
3. Never interpolate across session gaps. Never fill missing bars with zero-volume bars.

---

## Canonical Session ID Function
```python
from datetime import datetime, time, timedelta

def session_id(ts: datetime) -> str:
    """
    Returns the canonical session identifier for a bar timestamp.
    Night session is keyed to the calendar date it OPENED, not the bar date.

    Examples:
      2024-01-15 16:00 → "N20240115"
      2024-01-16 04:55 → "N20240115"  ← same session, crosses midnight
      2024-01-16 09:30 → "D20240116"
    """
    t = ts.time()
    if t >= time(15, 0):
        return f"N{ts.strftime('%Y%m%d')}"
    elif t < time(5, 0):
        prev = (ts - timedelta(days=1)).strftime('%Y%m%d')
        return f"N{prev}"
    elif time(8, 45) <= t <= time(13, 45):
        return f"D{ts.strftime('%Y%m%d')}"
    return "CLOSED"  # inter-session — this bar should not exist

def session_label(sid: str) -> str:
    """Human-readable label. 'N20240115' → '01/15 Night', 'D20240116' → '01/16 Day'"""
    kind = "Night" if sid[0] == "N" else "Day"
    date_str = sid[1:]
    return f"{date_str[4:6]}/{date_str[6:8]} {kind}"
```

---

## TradingView Lightweight Charts — Correct Configuration

TradingView Lightweight Charts supports `timeScale.tickMarkFormatter` and custom
time visible range. Use these to eliminate phantom gaps.

### 1. Filter out inter-session bars before sending to chart
```typescript
// frontend/src/utils/taifex-time.ts

export function isValidTaifexBar(ts: number): boolean {
  // ts is Unix timestamp in seconds
  const d = new Date(ts * 1000);
  // Convert to Taiwan time (UTC+8)
  const twHour = (d.getUTCHours() + 8) % 24;
  const twMin = d.getUTCMinutes();
  const minuteOfDay = twHour * 60 + twMin;

  const NIGHT_OPEN = 15 * 60;      // 15:00
  const NIGHT_CLOSE = 5 * 60;      // 05:00
  const DAY_OPEN = 8 * 60 + 45;    // 08:45
  const DAY_CLOSE = 13 * 60 + 45;  // 13:45

  return minuteOfDay >= NIGHT_OPEN ||
         minuteOfDay < NIGHT_CLOSE ||
         (minuteOfDay >= DAY_OPEN && minuteOfDay <= DAY_CLOSE);
}

export function sessionLabel(ts: number): string {
  const d = new Date(ts * 1000);
  const twHour = (d.getUTCHours() + 8) % 24;
  const twMin = d.getUTCMinutes();
  const minuteOfDay = twHour * 60 + twMin;

  if (minuteOfDay >= 15 * 60 || minuteOfDay < 5 * 60) {
    // Night session — label with opening date
    const openDate = minuteOfDay < 5 * 60
      ? new Date((ts - 86400) * 1000)  // previous calendar day
      : d;
    return `${openDate.toLocaleDateString('zh-TW')} 夜盤`;
  }
  return `${d.toLocaleDateString('zh-TW')} 日盤`;
}
```

### 2. Chart initialization with custom tick formatter
```typescript
import { createChart, CrosshairMode } from 'lightweight-charts';

const chart = createChart(container, {
  timeScale: {
    timeVisible: true,
    secondsVisible: false,
    tickMarkFormatter: (time: number, tickMarkType: any, locale: string) => {
      // time is UTC seconds
      const d = new Date(time * 1000);
      const twHour = (d.getUTCHours() + 8) % 24;
      const twMin = d.getUTCMinutes();
      const hhmm = `${String(twHour).padStart(2, '0')}:${String(twMin).padStart(2, '0')}`;

      // Show date only at session boundaries
      if (twHour === 15 && twMin === 0) {
        return `夜 ${d.getUTCMonth()+1}/${d.getUTCDate()} ${hhmm}`;
      }
      if (twHour === 8 && twMin === 45) {
        return `日 ${hhmm}`;
      }
      return hhmm;
    },
  },
  crosshair: { mode: CrosshairMode.Normal },
  localization: {
    timeFormatter: (ts: number) => sessionLabel(ts),
  },
});
```

### 3. Gap handling — use business day / bar-index time scale
The cleanest approach for TAIFEX is to use **bar index as the x-axis** in the chart,
with a lookup table mapping index → real timestamp for tooltip display.
This eliminates ALL gap artifacts at the cost of one lookup on hover.

```typescript
// Map bar index → real timestamp for tooltip
const indexToTimestamp: Map<number, number> = new Map();

function barsToChartData(bars: OHLCVBar[]) {
  return bars
    .filter(b => isValidTaifexBar(b.timestamp))
    .map((b, i) => {
      indexToTimestamp.set(i, b.timestamp);
      return {
        time: i as any,  // use index as time
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      };
    });
}
```

---

## Plotly Dash — Correct Configuration (Legacy)

If still on Dash, use these settings to minimize gap artifacts:

```python
import plotly.graph_objects as go

def make_taifex_candlestick(df):
    # Step 1: Remove inter-session bars
    df = df[df["session_id"] != "CLOSED"].copy()

    # Step 2: Use rangebreaks to hide gaps
    fig = go.Figure(go.Candlestick(
        x=df["timestamp"],
        open=df["open"], high=df["high"],
        low=df["low"], close=df["close"],
    ))
    fig.update_xaxes(
        rangebreaks=[
            # Hide the inter-session gap: 05:00–08:45
            {"bounds": ["05:00", "08:45"], "pattern": "hour"},
            # Hide the post-day-session gap: 13:45–15:00
            {"bounds": ["13:45", "15:00"], "pattern": "hour"},
            # Hide weekends
            {"bounds": ["sat", "mon"]},
        ],
        tickformat="%m/%d %H:%M",
        hoverformat="%Y-%m-%d %H:%M (TW)",
    )
    return fig
```

---

## Tooltip / Crosshair Display Standard
Every bar tooltip MUST show:
```
[Session Label]  e.g. "01/15 夜盤" or "01/16 日盤"
Time: HH:MM (Taiwan)
O: 18,450  H: 18,520  L: 18,430  C: 18,490
Volume: 1,203
Δ vs prev close: +40 (+0.22%)
```

Never show raw UTC timestamps to the user.
Never show "2024-01-16 04:55" without the session label.
