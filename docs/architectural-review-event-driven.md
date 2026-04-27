# Architectural Review: Event-Driven State Machine for Live Trading

*Lead Quantitative Developer perspective*

**Diagnosis:** You are attempting to run a live trading system on an architecture that lacks a strict Event-Driven State Machine. The symptoms—unstable bar generation, timeframe (TF) mismatches, faulty signals, and a nightmare playback function—are classic indicators of tight coupling between data ingestion, signal generation, and execution. If your playback function takes a long time to tune, it means your backtester and live engine are using two different code paths.

---

## 1. The Missing Core: Robust Tick-to-Bar Aggregator & Feed Handler

You are trying to execute trades, but there is no dedicated, resilient component for ingesting real-time data and compiling it into mathematically correct Timeframes (TFs).

**What is missing:**

- **A deterministic Bar Builder:** Your system needs a dedicated daemon that ingests Shioaji WebSocket ticks (`TickEvent`), buffers them, and emits a `BarEvent` exactly at the boundary (e.g., `09:05:00.000`).
- **Timeframe Alignment:** If a strategy requires 1m, 5m, and 15m data, the feed handler must guarantee that the 15m bar does not emit until all three 5m bars and fifteen 1m bars have strictly closed. Passing unaligned data arrays to vectorized Pandas/NumPy logic in real-time causes look-ahead bias and faulty signals.
- **Stale Data / Heartbeat Monitor:** If the WebSocket silently drops, your strategies will think volatility is zero. You need a heartbeat monitor that triggers an emergency halt if no ticks arrive within N milliseconds.

---

## 2. Lack of a Unified Event Bus (The "Playback" Problem)

Your `SessionManager` uses a `poll_all()` loop to fetch account states. This is fundamentally flawed for high-fidelity quant trading. Polling introduces latency, creates race conditions between signal execution and state updates, and makes playback impossible to simulate correctly.

**What is missing:**

- **Unified Event Queue:** Both Live and Playback environments must be 100% identical. They should both read from a single strict queue: `DataEvent` → `SignalEvent` → `OrderEvent` → `FillEvent`.
- To fix your playback function: Stop writing a separate "playback" logic. Instead, feed historical `TickEvent` or `BarEvent` objects into the exact same queue your live system uses. If the code paths differ, your backtest is structurally invalid.

---

## 3. Execution Engine Fragility & Orphaned Orders

Your `LiveExecutor` handles callbacks cleanly by routing them to an `asyncio.Future` bridge. However, it is not fault-tolerant.

**What is missing:**

- **Reconciliation State Machine:** You track pending orders in memory (`self._pending = {}`). If your Python process crashes or restarts after the order hits TAIFEX but before the Shioaji C++ callback returns, you have an "orphaned order." The system boots up with `_pending` empty, oblivious to the open order in the market. You must implement a persistent SQLite/Redis order state tracker.
- **Concurrency Locks on Fills:** Your callback bridge uses `loop.call_soon_threadsafe`. If a partial fill and a complete fill arrive in the same millisecond, you risk race conditions updating the strategy's position inventory.

---

## 4. Immature Risk Engine Guardrails

While you have a basic `_check_rollout` that prevents exceeding contract limits, it is insufficient for production capital preservation.

**What is missing:**

- **Pre-Trade Margin Checks:** The execution engine blindly assumes margin is available. You must pull the real-time available margin from `AccountSnapshot` and calculate the required initial margin *before* firing the `place_order` command.
- **Rate Limiting / Order Fat-Finger Prevention:** If a bug in your strategy generates a signal every tick (a common issue with unstable bar generation), your `LiveExecutor` will spam the broker and get your API key banned. Implement a strict token-bucket rate limiter (e.g., max 5 orders per second, max 20 per minute).

---

## Immediate Action Plan

1. **Halt Live Trading:** Do not trade real capital until the Bar Generator is deterministic.
2. **Build the `DataStreamer`:** Write a standalone WebSocket consumer that does nothing but append ticks to a buffer and chronologically slice them into precise NumPy arrays at integer minute boundaries.
3. **Refactor to Event-Driven:** Delete the `poll_all()` loop. Bind the Shioaji `FDEAL` callbacks to emit a `FillEvent` into a global `asyncio.Queue`. Have your strategy sleep until a `BarEvent` appears in the queue.
4. **Implement DB Reconciliation:** On startup, `LiveExecutor` must query Shioaji for all active working orders and populate its `_pending` dict before it allows any strategy to emit new signals.
