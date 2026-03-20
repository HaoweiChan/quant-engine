# BarSimulator — Usage Guide

Minimal 10-bar backtest loop demonstrating stop checking, entry filling, and position lifecycle.

```python
from datetime import datetime, timedelta

from src.bar_simulator import BarSimulator, OHLCBar, StopLevel

# Configure simulator: 2-point slippage, fill entries at bar close
sim = BarSimulator(slippage_points=2.0, entry_mode="bar_close")

# Sample 10-bar data (TX futures)
bars = [
    OHLCBar(datetime(2024, 1, 1, 9, 0), 17000, 17050, 16950, 17020, 500),
    OHLCBar(datetime(2024, 1, 1, 9, 5), 17020, 17080, 17000, 17060, 450),
    OHLCBar(datetime(2024, 1, 1, 9, 10), 17060, 17120, 17040, 17100, 600),
    OHLCBar(datetime(2024, 1, 1, 9, 15), 17100, 17150, 17050, 17080, 550),
    OHLCBar(datetime(2024, 1, 1, 9, 20), 17080, 17090, 16950, 16970, 700),
    OHLCBar(datetime(2024, 1, 1, 9, 25), 16970, 17010, 16940, 16980, 400),
    OHLCBar(datetime(2024, 1, 1, 9, 30), 16980, 17050, 16960, 17030, 480),
    OHLCBar(datetime(2024, 1, 1, 9, 35), 17030, 17100, 17010, 17080, 520),
    OHLCBar(datetime(2024, 1, 1, 9, 40), 17080, 17130, 17060, 17110, 460),
    OHLCBar(datetime(2024, 1, 1, 9, 45), 17110, 17140, 17090, 17120, 430),
]


# Simple signal: buy on bar 1, hold until stopped out
def my_signal(bar_idx: int) -> bool:
    return bar_idx == 1


position_entry: float | None = None
stop_price: float | None = None

for i, bar in enumerate(bars):
    next_bar = bars[i + 1] if i + 1 < len(bars) else None

    # Build active stops from current position
    stops: list[StopLevel] = []
    if stop_price is not None:
        stops.append(StopLevel(price=stop_price, direction="below", label="initial_stop"))

    entry_signal = my_signal(i) and position_entry is None

    result = sim.process_bar(bar, next_bar, stops, entry_signal)

    # Handle stop trigger
    if result.stop_result.triggered and position_entry is not None:
        pnl = result.stop_result.trigger_price - position_entry
        print(f"Bar {i}: STOPPED at {result.stop_result.trigger_price:.0f} "
              f"(PnL: {pnl:+.0f} pts, label: {result.stop_result.trigger_label})")
        position_entry = None
        stop_price = None
        continue

    # Handle entry fill
    if result.entry_result and result.entry_result.filled and position_entry is None:
        position_entry = result.entry_result.fill_price
        stop_price = position_entry - 100  # 100-point initial stop
        print(f"Bar {i}: ENTRY at {position_entry:.0f}, stop at {stop_price:.0f}")
        continue

    # Status
    if position_entry is not None:
        unrealized = bar.close - position_entry
        print(f"Bar {i}: holding (unrealized: {unrealized:+.0f} pts)")
    else:
        print(f"Bar {i}: flat")
```

## Output

```
Bar 0: flat
Bar 1: ENTRY at 17062, stop at 16962
Bar 2: holding (unrealized: +38 pts)
Bar 3: holding (unrealized: +18 pts)
Bar 4: STOPPED at 16960 (PnL: -102 pts, label: initial_stop)
Bar 5: flat
Bar 6: flat
Bar 7: flat
Bar 8: flat
Bar 9: flat
```

## Key Behaviors Demonstrated

1. **Entry at close** — Bar 1 entry fills at `17060 + 2 = 17062` (close + slippage)
2. **Intra-bar stop detection** — Bar 4 low (16950) pierces stop at 16962, even though close (16970) is above the stop
3. **Stop fill with slippage** — Fill at `16962 - 2 = 16960` (stop price - slippage)
4. **Same-bar conflict** — If a stop and entry occurred on the same bar, the stop would win
