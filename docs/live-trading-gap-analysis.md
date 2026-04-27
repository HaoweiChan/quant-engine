# Live Trading Gap Analysis — Quant Engine

I've reviewed the codebase. The backtest/optimization side is mature (BacktestRunner, EventEngine, ParamRegistry, walk-forward, Monte Carlo, policy composition). **The live side is roughly 40% built — you have the rails on both ends but no locomotive in the middle.**

Below is the structural picture, then prioritized fixes.

---

## What you have vs. what is actually wired

| Layer | Built | Wired into live loop? |
|---|---|---|
| Sinopac tick callback (`_on_tick`) | Yes | **Only to `push_tick` → WebSocket broadcaster.** Not to any engine. |
| `live_feed` / `blotter` / `risk` WS routes | Yes | Frontend-only |
| `LiveExecutor` (real order placement) | Yes | Has no caller — nothing produces orders to feed it |
| `LiveExecutionEngine` (disaster stop) | Yes | Same — orphaned |
| `PipelineRunner.run_step(snapshot, signal)` | Yes | Only called by `run_historical()` |
| `SessionManager.poll_all()` | Yes | Polls **broker account snapshot only**. Does NOT drive `engine.on_snapshot()`. |
| `RuntimeOrchestrator` | Skeleton | `_idle_worker` placeholders — not connected to anything |
| Tick→Bar aggregator | **Missing** | — |
| Multi-timeframe router (1m→3m/5m/15m/60m) | **Missing** | (aggregation is embedded inside each strategy's `_Indicators`) |
| Strategy warm-up from DB on session start | **Missing** | — |
| Wall clock vs. simulated clock abstraction | **Missing** | `datetime.now()` scattered |
| Tick-staleness watchdog | **Missing** | — |
| Sinopac reconnect loop | Half — has `_reconnect_interval_secs` but no scheduler invokes it | — |
| Order state machine (open→ack→partial→filled, persistent) | **Missing** | `_pending` dict in-memory, lost on restart |
| Backtest playback streamer (the thing you've been fighting) | **Missing as a module** | The closest is audit `replay()`, but that's hash verification, not chart playback |

The single sentence summary: **`SessionManager.poll_all()` only updates the equity field on `SessionSnapshot` — it never calls `position_engine.on_snapshot()`.** When you mark a session `active`, nothing drives the strategy. Ticks arrive, the chart updates, the strategy stays asleep.

---

## The three critical missing modules (build in this order)

### 1. `LiveBarBuilder` — tick → 1-minute OHLCV bar (CRITICAL — blocker)

Current `_on_tick` in `src/broker_gateway/sinopac.py` only does:
```python
asyncio.run_coroutine_threadsafe(push_tick(symbol, price, volume), loop)
```

That's a tee to the WebSocket. There is no aggregation, no bar emission, no engine feed.

You need a `src/data/live_bar_builder.py` along these lines:

```python
class LiveBarBuilder:
    """Aggregates trade ticks into closed N-second/N-minute bars.

    Emits BarEvent only on bar close (not on every tick) so strategies
    see the same 'closed bar' semantic that the backtester sees.
    """
    def __init__(self, symbol: str, interval_secs: int = 60,
                 on_bar_close: Callable[[OHLCBar], Awaitable[None]] | None = None):
        self._symbol = symbol
        self._interval = interval_secs
        self._cur_bucket: int | None = None
        self._open = self._high = self._low = self._close = 0.0
        self._volume = 0.0
        self._on_bar_close = on_bar_close
        self._last_tick_ts: float = 0.0   # for staleness watchdog

    async def on_tick(self, ts_epoch: float, price: float, volume: float) -> None:
        bucket = int(ts_epoch // self._interval)
        if self._cur_bucket is None:
            self._cur_bucket = bucket
            self._open = self._high = self._low = self._close = price
            self._volume = volume
        elif bucket != self._cur_bucket:
            # Bar closed — emit
            closed = OHLCBar(
                timestamp=datetime.fromtimestamp(self._cur_bucket * self._interval, tz=UTC),
                open=self._open, high=self._high, low=self._low,
                close=self._close, volume=self._volume,
            )
            if self._on_bar_close:
                await self._on_bar_close(closed)
            self._cur_bucket = bucket
            self._open = self._high = self._low = self._close = price
            self._volume = volume
        else:
            self._high = max(self._high, price)
            self._low = min(self._low, price)
            self._close = price
            self._volume += volume
        self._last_tick_ts = ts_epoch

    def is_stale(self, now_epoch: float, max_silence_secs: float = 5.0) -> bool:
        return self._last_tick_ts > 0 and (now_epoch - self._last_tick_ts) > max_silence_secs
```

Then a `MultiTimeframeRouter` that owns one `LiveBarBuilder(60)` and on every closed 1-min bar, fans out into 3-min/5-min/15-min/60-min builders. **Crucially: a strategy declaring `bar_agg=3` should subscribe to the 3-min stream, not internally count 1-min ticks.** Right now `_Indicators._agg_count` does this aggregation per-strategy, which means three strategies on the same data each maintain their own counter — fragile and a known source of "faulty signals" when one indicator updates and another doesn't.

### 2. `LiveStrategyDriver` — wire bars into `PositionEngine` (CRITICAL — blocker)

This is the missing locomotive. It binds the bar stream to your existing `PipelineRunner.run_step()`:

```python
class LiveStrategyDriver:
    def __init__(self, session: TradingSession, engine: PositionEngine,
                 executor: ExecutionEngine, bar_router: MultiTimeframeRouter,
                 adapter: BaseAdapter, gateway: BrokerGateway,
                 dispatcher: NotificationDispatcher | None = None):
        self._session = session
        self._runner = PipelineRunner(engine, executor, dispatcher=dispatcher)
        self._adapter = adapter
        self._gateway = gateway
        bar_router.subscribe(session.timeframe_secs, self._on_bar_close)

    async def _on_bar_close(self, bar: OHLCBar) -> None:
        if self._session.status != "active":
            return
        snapshot = self._adapter.to_snapshot({
            "symbol": self._session.symbol,
            "timestamp": bar.timestamp,
            "open": bar.open, "high": bar.high, "low": bar.low,
            "close": bar.close, "volume": bar.volume,
            "daily_atr": self._daily_atr_cache.get(),  # see point #5
        })
        # Optionally inject ML signal
        signal = self._signal_engine.predict_one(snapshot) if self._signal_engine else None
        results = await self._runner.run_step(snapshot, signal)
        # Emit to blotter/risk WS for the dashboard
        for r in results:
            await blotter_broadcaster.broadcast(self._fill_to_event(r))
```

Then `SessionManager.set_status(session_id, "active")` instantiates the driver, and `"stopped"` tears it down. This is the missing glue.

### 3. `StrategyWarmup` — backfill indicators from DB before first live bar (CRITICAL — quality)

This is almost certainly a primary source of your "faulty signals." `EmaTrendPullback` uses `ema_trend=144`. On a cold start mid-session, the EMA has no history — it starts emitting nonsense for the first ~3× the period.

Solution at session start:

```python
def warmup(self, db: Database, lookback_bars: int = 500) -> None:
    end = datetime.now(UTC)
    # 1.5x the longest indicator period, in 1-min bars
    start = end - timedelta(minutes=int(lookback_bars * 1.5))
    historical = db.get_ohlcv(self._session.symbol, start, end)
    for bar in historical:
        snapshot = self._adapter.to_snapshot(bar.__dict__)
        # Drive the engine but DISCARD orders — we're just hydrating state
        self._engine.on_snapshot(snapshot, signal=None, account=None)
    logger.info("strategy_warmup_complete",
                bars_replayed=len(historical),
                strategy=self._session.strategy_slug)
```

The trick: your `PositionEngine.on_snapshot()` returns orders even during warmup. Add a `warmup_mode: bool` flag that causes `_check_stops`/`_execute_entry` to update internal state but emit no orders. Critical, otherwise you'll fire historical phantom trades on session start.

---

## Secondary gaps (not blockers, but you'll hit them within a week of going live)

| Gap | Symptom you'll see | Fix |
|---|---|---|
| No `Clock` abstraction; `datetime.now()` scattered | Force-close window misses if no bar arrives at 13:25 exactly | Inject `Clock` (Wall vs. Simulated) into `PositionEngine`, drive `in_force_close` checks via a separate wall-clock heartbeat task that fires `engine.on_clock_tick()` |
| Tick staleness undetected | Strategy holds positions during a feed dropout believing the last quote is current | Async watchdog: if `LiveBarBuilder.is_stale(now, 5.0)`, halt all sessions on that symbol via `SessionManager.halt()` |
| Sinopac reconnect not triggered | Once disconnected, gateway stays down silently | Background `asyncio.create_task(_reconnect_loop)` in lifespan, polls `is_connected` every `_reconnect_interval_secs` |
| Daily ATR not refreshed live | Strategies use snapshot.atr['daily']; in live it's stale | Cache and refresh daily ATR at session-open + every 60-min bar close from DB |
| Order state not persisted | App restart loses in-flight order tracking | `OrderStateStore` in trading.db with FSM: `pending → ack → partial → filled / rejected / cancelled`. Reconcile against Sinopac on startup. |
| `RuntimeOrchestrator` is a skeleton | `_idle_worker` placeholders never get replaced — the multiprocess isolation you designed for shadow/micro_live is non-functional | Either commit to single-process asyncio (simpler, what you actually have working) and delete `runtime/orchestrator.py`, or implement the targets. Don't leave the skeleton — it's misleading. |

---

## On the playback function

You said it cost you a long time to tune. Looking at the code, I don't see a dedicated playback module — only `audit.trail.replay()` which is for hash-chain verification, not chart visualization. If you've been bolting playback onto the backtest WebSocket, that's why it's been painful.

The clean abstraction is one module:

```
src/playback/streamer.py
  class BacktestPlayback:
      def __init__(self, bars, strategy, speed_x: float = 1.0,
                   on_bar, on_signal, on_fill): ...
      async def run(): ...   # iterate bars, sleep(bar_dt / speed_x), call BacktestRunner step
```

Then `/ws/playback` opens it, the React chart subscribes, and the *exact same* code path can be reused for paper trading by injecting a `LiveBarBuilder` instead of a bar list. **Live and playback should differ only in the bar source.** If your playback path is different from your live path, you're testing one and running another.

---

## Recommended sequence (what to fill in this week)

1. **Day 1–2**: `LiveBarBuilder` + `MultiTimeframeRouter`, with unit tests against synthetic tick streams
2. **Day 2–3**: `LiveStrategyDriver`, wire `SessionManager` to spawn/teardown drivers on status transitions
3. **Day 3**: `StrategyWarmup` with `warmup_mode` flag in `PositionEngine`
4. **Day 4**: `Clock` abstraction; replace `datetime.now()` in `session_utils.py` and `position_engine.py`
5. **Day 4–5**: `BacktestPlayback` module on top of the same `LiveStrategyDriver` (substitute bar source)
6. **Day 5**: Tick-staleness watchdog + Sinopac reconnect task
7. **Week 2**: Order state persistence; decide on `RuntimeOrchestrator` (commit or delete)

After step 3, you should immediately stop seeing "faulty signals" — they're almost certainly cold-start indicator artifacts plus the unaggregated tick stream.

After step 5, your playback function becomes 50 lines instead of however many you've been struggling with.
