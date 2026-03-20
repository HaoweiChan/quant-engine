## Context

Phase 1 is complete: Position Engine, Prediction Engine, Simulator, Risk Monitor, Data Layer, and PaperExecutor are all implemented and tested. The pipeline runs synchronously — `PipelineRunner.run_step()` feeds snapshots through Prediction → Position → PaperExecutor in sequence.

The current `ExecutionEngine` ABC is synchronous (`def execute()`). The `PaperExecutor` simulates fills at close price with configurable slippage. The Risk Monitor already runs as an async task (`start_async_loop()`). Structlog is configured in `pipeline/logging.py` but most modules still use `logging.getLogger()`.

Shioaji's order API is synchronous for placement (`place_order()` returns a `Trade` with `PendingSubmit`) but fill notifications arrive via callbacks on a C++ thread (`set_order_callback()`). The `api.margin()` and `api.list_positions()` APIs provide the broker-side state needed for reconciliation.

## Goals / Non-Goals

**Goals:**
- Place and manage real TAIFEX futures orders via shioaji
- Detect engine-vs-broker state divergence before it causes damage
- Get Telegram alerts for every trade, risk event, and daily summary
- Scale gradually from 1 contract to planned allocation via config
- Make the full pipeline async-first for production robustness

**Non-Goals:**
- Multi-broker support (only shioaji/TAIFEX for now)
- Native stop orders (TAIFEX API doesn't support them; simulate via IOC)
- Automated reconciliation correction (alert-only in Phase 2; auto-correct deferred)
- Dashboard changes (existing dashboard continues as-is)
- Crypto or US equity adapters (Phase 3/4)

## Decisions

### 1. Async-first pipeline

**Decision:** Make `ExecutionEngine.execute()` async and convert `PipelineRunner` to async throughout.

**Why:** Shioaji fill confirmations arrive via C++ thread callbacks with unpredictable timing. An async pipeline lets us await fills without blocking the event loop, and naturally composes with Risk Monitor's existing async loop and reconciliation timers.

**Alternative considered:** Keep sync pipeline + thread pool for live executor. Rejected because it creates two execution models to maintain and makes composition with Risk Monitor harder.

**Migration:** PaperExecutor wraps its sync logic in `async def` — zero behavioral change. All tests that call `execute()` add `await` / use `pytest-asyncio`.

### 2. Callback → asyncio.Future bridge for shioaji

**Decision:** Each `place_order()` call creates an `asyncio.Future`. The shioaji order callback resolves it via `loop.call_soon_threadsafe(future.set_result, ...)`. The executor awaits the future with a configurable timeout.

```
  LiveExecutor                    shioaji C++ thread
  ─────────────                   ──────────────────
  future = loop.create_future()
  _pending[trade_id] = future
  api.place_order(contract, order)
       │
       │                          DealEvent callback
       │                          loop.call_soon_threadsafe(
       │                              future.set_result, deal_info
       │                          )
       │
  result = await wait_for(future, timeout=30)
```

**Why:** Standard pattern for bridging thread-based callbacks to asyncio. The `call_soon_threadsafe` is the only safe way to communicate from a non-asyncio thread to the event loop.

### 3. Stop orders via IOC limit at stop price

**Decision:** TAIFEX API does not support native stop orders. When a stop is triggered by price crossing the stop level, the executor places an IOC (Immediate-or-Cancel) limit order at the stop price.

**Why:** This is what the Position Engine already does — it checks stop conditions in `on_snapshot()` and emits close `Order`s when triggered. The executor just needs to translate those into IOC limits. Market orders (`MKT`) are also available as a fallback if IOC doesn't fill.

**Trade-off:** Slight fill risk if the market gaps through the stop level. Acceptable for TAIFEX futures which have reasonable liquidity during trading hours.

### 4. Simple Telegram integration via httpx

**Decision:** Direct `httpx.AsyncClient.post()` to Telegram Bot API. No event bus, no queue, no abstraction layer.

**Why:** One chat, one bot, five message types (entry, exit, add, risk, daily). An event bus is over-engineering at this stage. If we add Slack/Discord/LINE later, we can extract a dispatcher interface then.

**Failure policy:** Telegram failures are logged and swallowed — never crash the trading system for a notification failure.

### 5. Timer-based reconciliation at 60s intervals

**Decision:** The reconciler runs as an asyncio task alongside Risk Monitor, polling `api.list_positions()` and `api.margin()` every 60 seconds.

**Why:** Same pattern as Risk Monitor's `start_async_loop()`. Timer-based is simpler than event-driven and sufficient — position state changes on the order of minutes, not milliseconds.

**Response policy:** Alert-only by default. Halt-on-mismatch available via config for critical mismatches (ghost/orphan positions).

### 6. Structlog migration via module-level replacement

**Decision:** Replace `logging.getLogger(__name__)` with `structlog.get_logger(__name__)` in every module. The existing `pipeline/logging.py` setup already configures structlog properly.

**Why:** Straightforward find-and-replace. No architectural change. Structlog's bound loggers add structured context (order_id, symbol, etc.) which is critical for production debugging.

## Risks / Trade-offs

**[Fill race condition]** DealEvent may arrive before OrderEvent (documented shioaji behavior). → Mitigation: Key pending orders by `trade_id` from `place_order()` return, not from the OrderEvent. DealEvent carries `trade_id` for correlation.

**[Callback thread safety]** Shioaji callbacks run on a C++ thread. → Mitigation: Only touch asyncio primitives via `call_soon_threadsafe()`. No shared mutable state between threads.

**[IOC stop fill risk]** IOC limit at stop price may not fill if market gaps. → Mitigation: If IOC returns unfilled, immediately retry as MKT order. Log the gap event for analysis.

**[Telegram rate limits]** Telegram Bot API limits ~30 messages/second per chat. → Mitigation: Unlikely to hit with trading frequency. If needed, batch messages with short delay.

**[Reconciliation during market close]** Broker positions may report stale data outside trading hours. → Mitigation: Only run reconciliation during configured trading hours. Skip checks outside sessions.

**[Async migration test breakage]** Converting execute() to async touches many test files. → Mitigation: Use `pytest-asyncio` for all execution-related tests. PaperExecutor behavior is unchanged.
