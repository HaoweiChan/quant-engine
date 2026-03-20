"""E2E backtest: verifies BarSimulator catches intra-bar stops that naive close-price misses.

Scenario: Long TX futures position with 100-pt initial stop and trailing stop.
The market rallies, trails up, then a volatile bar dips through the trailing
stop but closes above it. A naive close-only check misses the stop.
BarSimulator catches it.
"""
from datetime import datetime, timedelta

from src.bar_simulator.models import OHLCBar, StopLevel
from src.bar_simulator.simulator import BarSimulator

BASE_TS = datetime(2024, 3, 1, 9, 0)


def _ts(minutes: int) -> datetime:
    return BASE_TS + timedelta(minutes=minutes)


# 20-bar scenario: entry on bar 1, rally to bar 10, volatile dip on bar 14
BARS = [
    # Bar 0: pre-signal, flat
    OHLCBar(_ts(0), 17000, 17020, 16980, 17010, 1200),
    # Bar 1: entry signal fires here
    OHLCBar(_ts(5), 17010, 17040, 16990, 17030, 1100),
    # Bar 2-6: steady rally
    OHLCBar(_ts(10), 17030, 17080, 17020, 17070, 1300),
    OHLCBar(_ts(15), 17070, 17120, 17060, 17110, 1250),
    OHLCBar(_ts(20), 17110, 17160, 17100, 17150, 1400),
    OHLCBar(_ts(25), 17150, 17200, 17130, 17180, 1350),
    OHLCBar(_ts(30), 17180, 17230, 17170, 17220, 1500),
    # Bar 7-9: momentum slows
    OHLCBar(_ts(35), 17220, 17240, 17200, 17210, 900),
    OHLCBar(_ts(40), 17210, 17230, 17190, 17200, 850),
    OHLCBar(_ts(45), 17200, 17220, 17180, 17210, 800),
    # Bar 10: volatile bar — low dips through trailing stop but closes above
    # This is the critical bar: stop at ~17130, low hits 17100
    OHLCBar(_ts(50), 17210, 17220, 17100, 17190, 2500),
    # Bar 11-14: recovery (should never reach if stop caught on bar 10)
    OHLCBar(_ts(55), 17190, 17250, 17180, 17240, 1600),
    OHLCBar(_ts(60), 17240, 17300, 17230, 17280, 1700),
    OHLCBar(_ts(65), 17280, 17320, 17260, 17310, 1500),
    OHLCBar(_ts(70), 17310, 17350, 17290, 17340, 1400),
    # Bar 15-19: another dip
    OHLCBar(_ts(75), 17340, 17350, 17300, 17320, 1100),
    OHLCBar(_ts(80), 17320, 17330, 17280, 17290, 1000),
    OHLCBar(_ts(85), 17290, 17310, 17270, 17300, 950),
    OHLCBar(_ts(90), 17300, 17320, 17290, 17310, 900),
    OHLCBar(_ts(95), 17310, 17340, 17300, 17330, 1050),
]

INITIAL_STOP_DISTANCE = 100.0
TRAILING_DISTANCE = 100.0  # trail at highest_high - 100 pts
SLIPPAGE = 2.0


def _run_backtest_with_bar_simulator() -> dict:
    """Run full backtest using BarSimulator with intra-bar stop checking."""
    sim = BarSimulator(slippage_points=SLIPPAGE, entry_mode="bar_close")
    entry_price: float | None = None
    initial_stop: float | None = None
    trailing_stop: float | None = None
    highest_since_entry: float | None = None
    trade_log: list[dict] = []
    equity = 2_000_000.0
    equity_curve = [equity]
    point_value = 200.0  # TX: 1 point = NT$200
    lots = 1.0

    for i, bar in enumerate(BARS):
        next_bar = BARS[i + 1] if i + 1 < len(BARS) else None

        # Build stop levels
        stops: list[StopLevel] = []
        if initial_stop is not None:
            stops.append(StopLevel(price=initial_stop, direction="below", label="initial_stop"))
        if trailing_stop is not None and trailing_stop > (initial_stop or 0):
            stops.append(StopLevel(price=trailing_stop, direction="below", label="trailing_stop"))

        entry_signal = (i == 1) and entry_price is None

        result = sim.process_bar(bar, next_bar, stops, entry_signal)

        # Handle stop
        if result.stop_result.triggered and entry_price is not None:
            fill = result.stop_result.trigger_price
            pnl_pts = fill - entry_price
            pnl_cash = pnl_pts * lots * point_value
            equity += pnl_cash
            trade_log.append({
                "bar": i, "action": "STOP",
                "price": fill, "label": result.stop_result.trigger_label,
                "pnl_pts": pnl_pts, "pnl_cash": pnl_cash,
                "seq_idx": result.stop_result.sequence_idx,
                "bar_close": bar.close, "bar_low": bar.low,
            })
            entry_price = None
            initial_stop = None
            trailing_stop = None
            highest_since_entry = None
            equity_curve.append(equity)
            continue

        # Handle entry
        if result.entry_result and result.entry_result.filled and entry_price is None:
            entry_price = result.entry_result.fill_price
            initial_stop = entry_price - INITIAL_STOP_DISTANCE
            trailing_stop = initial_stop
            highest_since_entry = entry_price
            trade_log.append({
                "bar": i, "action": "ENTRY",
                "price": entry_price,
                "stop": initial_stop,
            })

        # Update trailing stop: highest_high - fixed distance
        can_trail = entry_price is not None and highest_since_entry is not None
        if can_trail and bar.high > highest_since_entry:
            highest_since_entry = bar.high
            new_trail = highest_since_entry - TRAILING_DISTANCE
            if new_trail > trailing_stop:
                trailing_stop = new_trail

        # Mark-to-market
        if entry_price is not None:
            unrealized = (bar.close - entry_price) * lots * point_value
            equity_curve.append(2_000_000.0 + unrealized)
        else:
            equity_curve.append(equity)

    return {
        "trade_log": trade_log,
        "equity_curve": equity_curve,
        "final_equity": equity_curve[-1],
    }


def _run_naive_close_only() -> dict:
    """Run same backtest but only check stops against bar close (naive)."""
    entry_price: float | None = None
    initial_stop: float | None = None
    trailing_stop: float | None = None
    highest_since_entry: float | None = None
    trade_log: list[dict] = []
    equity = 2_000_000.0
    equity_curve = [equity]
    point_value = 200.0
    lots = 1.0

    for i, bar in enumerate(BARS):
        # Entry on bar 1
        if i == 1 and entry_price is None:
            entry_price = bar.close + SLIPPAGE
            initial_stop = entry_price - INITIAL_STOP_DISTANCE
            trailing_stop = initial_stop
            highest_since_entry = entry_price
            trade_log.append({"bar": i, "action": "ENTRY", "price": entry_price})

        # Naive: only check close against stops
        if entry_price is not None:
            effective_stop = max(initial_stop or 0, trailing_stop or 0)
            if bar.close <= effective_stop:
                fill = effective_stop - SLIPPAGE
                pnl_pts = fill - entry_price
                pnl_cash = pnl_pts * lots * point_value
                equity += pnl_cash
                trade_log.append({
                    "bar": i, "action": "STOP",
                    "price": fill, "pnl_pts": pnl_pts,
                    "bar_close": bar.close, "bar_low": bar.low,
                })
                entry_price = None
                initial_stop = None
                trailing_stop = None
                highest_since_entry = None
                equity_curve.append(equity)
                continue

        # Update trailing stop: highest_high - fixed distance
        can_trail = entry_price is not None and highest_since_entry is not None
        if can_trail and bar.high > highest_since_entry:
            highest_since_entry = bar.high
            new_trail = highest_since_entry - TRAILING_DISTANCE
            if new_trail > (trailing_stop or 0):
                trailing_stop = new_trail

        if entry_price is not None:
            unrealized = (bar.close - entry_price) * lots * point_value
            equity_curve.append(2_000_000.0 + unrealized)
        else:
            equity_curve.append(equity)

    return {
        "trade_log": trade_log,
        "equity_curve": equity_curve,
        "final_equity": equity_curve[-1],
    }


def test_e2e_intrabar_stop_catches_what_naive_misses() -> None:
    """The core E2E test: BarSimulator catches the bar-10 stop, naive doesn't."""
    sim_result = _run_backtest_with_bar_simulator()
    naive_result = _run_naive_close_only()

    # BarSimulator should have triggered a stop
    sim_stops = [t for t in sim_result["trade_log"] if t["action"] == "STOP"]
    assert len(sim_stops) == 1, f"Expected 1 stop, got {len(sim_stops)}"

    # The stop should fire on bar 10 (the volatile dip bar)
    stop_event = sim_stops[0]
    assert stop_event["bar"] == 10, f"Stop on wrong bar: {stop_event['bar']}"
    assert stop_event["label"] == "trailing_stop"

    # Bar 10 close (17190) is ABOVE the trailing stop, but low (17100) is BELOW
    assert stop_event["bar_close"] == 17190
    assert stop_event["bar_low"] == 17100

    # Naive close-only should NOT have triggered on bar 10
    naive_stops = [t for t in naive_result["trade_log"] if t["action"] == "STOP"]
    naive_stop_bars = [t["bar"] for t in naive_stops]
    assert 10 not in naive_stop_bars, (
        f"Naive should NOT stop on bar 10 (close > stop), but did: {naive_stops}"
    )


def test_e2e_stop_fill_includes_slippage() -> None:
    """Stop fill price should be stop_level - slippage (adverse for long)."""
    sim_result = _run_backtest_with_bar_simulator()
    stop_event = [t for t in sim_result["trade_log"] if t["action"] == "STOP"][0]

    # Trailing stop = highest_high - TRAILING_DISTANCE
    # Highest high through bar 9 = 17240 (bar 7)
    highest = max(b.high for b in BARS[1:11])
    expected_trail = highest - TRAILING_DISTANCE
    expected_fill = expected_trail - SLIPPAGE

    assert abs(stop_event["price"] - expected_fill) < 0.01, (
        f"Fill {stop_event['price']} != expected {expected_fill}"
    )


def test_e2e_pnl_consistency() -> None:
    """PnL from stop should match (fill - entry) * lots * point_value."""
    sim_result = _run_backtest_with_bar_simulator()
    entry_ev = sim_result["trade_log"][0]
    stop_ev = sim_result["trade_log"][1]

    expected_pnl = (stop_ev["price"] - entry_ev["price"]) * 200.0
    assert abs(stop_ev["pnl_cash"] - expected_pnl) < 0.01


def test_e2e_no_position_after_stop() -> None:
    """After stop triggers on bar 10, no further trades should occur."""
    sim_result = _run_backtest_with_bar_simulator()
    events_after_10 = [t for t in sim_result["trade_log"] if t["bar"] > 10]
    assert len(events_after_10) == 0, f"Unexpected trades after stop: {events_after_10}"


def test_e2e_equity_curve_length() -> None:
    """Equity curve should have len(bars) + 1 entries (initial + per-bar)."""
    sim_result = _run_backtest_with_bar_simulator()
    assert len(sim_result["equity_curve"]) == len(BARS) + 1


def test_e2e_same_bar_stop_and_entry_conflict() -> None:
    """If we force an entry signal on the same bar that stops us out, stop wins."""
    sim = BarSimulator(slippage_points=SLIPPAGE, entry_mode="bar_close")
    # Bar that dips through a stop
    bar = OHLCBar(_ts(0), 17200, 17220, 17050, 17180, 2000)
    next_bar = OHLCBar(_ts(5), 17180, 17250, 17170, 17230, 1500)
    stop = StopLevel(price=17100, direction="below", label="trailing_stop")

    result = sim.process_bar(bar, next_bar, [stop], entry_signal=True)
    assert result.stop_before_entry is True
    assert result.stop_result.triggered is True
    assert result.entry_result is None


def test_e2e_naive_overstates_pnl() -> None:
    """Naive backtest should show higher final equity (missed the stop loss)."""
    sim_result = _run_backtest_with_bar_simulator()
    naive_result = _run_naive_close_only()

    # Naive holds through bar 10 and beyond — should show higher equity
    # because it never realized the loss that BarSimulator caught
    sim_final = sim_result["final_equity"]
    naive_final = naive_result["final_equity"]

    # Naive should have unrealized gains (still in position at bar 19)
    # while BarSimulator stopped out at a loss on bar 10
    assert naive_final > sim_final, (
        f"Naive ({naive_final}) should overstate vs BarSimulator ({sim_final})"
    )
