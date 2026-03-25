## Context

The current `BacktestRunner.run()` iterates `for i, bar in enumerate(bars):` — calling `engine.on_snapshot()` then `fill_model.simulate()` in a tight loop. This is fast but structurally different from live trading, where events arrive asynchronously and the fill happens after latency. Gemini's critique: "the code that runs the backtest MUST be the exact same code that runs in production."

The current audit capability is `structlog.get_logger()` emitting structured log entries. These are mutable (log files can be edited), non-sequential (no guaranteed ordering), and don't capture full engine state.

## Goals / Non-Goals

**Goals:**
- Unified `EventEngine` that processes the same handler chain in backtest and live
- `BacktestRunner` becomes a thin wrapper (preserving API) around `EventEngine`
- Intra-bar tick drill-down using synthetic ticks from `price_sequence.py`
- SHA-256 hash-chain audit trail in separate SQLite database
- Deterministic replay from any audit point

**Non-Goals:**
- Distributed event bus (ZMQ/Redis) — in-process `deque` is sufficient for current scale
- Full tick-level backtesting (we synthesize ticks only for volatile bars)
- Real-time streaming dashboard for events (API endpoints for querying audit trail are sufficient)
- Blockchain/IPFS for audit storage

## Decisions

### D1: In-Process Event Queue (deque) over Message Bus

**Decision**: Use `collections.deque` as the event queue. Handlers are registered Python callables. No ZMQ/Redis.

```
EventEngine
├── _queue: deque[Event]
├── _handlers: dict[EventType, list[Callable]]
├── push(event) → appends to queue
├── run() → drains queue, dispatches to handlers
└── run_backtest(bars, ...) → converts bars to MarketEvents, runs
```

**Rationale**: For a single-process trading engine, an in-process queue has zero serialization overhead. The handler interface (`Callable[[Event], list[Event] | None]`) is clean enough that migration to an external message bus later requires only swapping the queue backend, not rewriting handlers.

### D2: Tick Drill-Down via Synthetic Generation

**Decision**: When a bar has `(high - low) > tick_drill_atr_mult × daily_atr`, synthesize intra-bar ticks using the existing `price_sequence.py` generator. The sequence uses the bar's OHLCV to constrain the path: start at open, touch high and low, end at close.

**Rationale**: User confirmed: synthesize ticks from OHLCV (Question Q1, answer A). Real tick data is not reliably available for TAIFEX. The existing `price_sequence.py` already generates realistic paths with configurable volatility, jumps, and mean-reversion.

### D3: Separate SQLite for Audit Trail

**Decision**: Audit records stored in `audit.db`, separate from the main `quant_engine.db`.

**Rationale**: User confirmed (Q6: B). Isolation means: (1) audit data survives main DB schema migrations, (2) backup/archival is a simple file copy, (3) append-only constraint is easier to enforce on a dedicated DB, (4) no performance impact on main DB writes.

### D4: SHA-256 Hash Chain over Merkle Tree

**Decision**: Each `AuditRecord` includes `prev_hash` (hash of preceding record) and `record_hash` (hash of current record's contents + prev_hash). Chain starts with genesis hash `"0" * 64`.

**Rationale**: Hash chain provides tamper evidence with O(n) verification. Merkle tree adds O(log n) proof-of-inclusion but at significantly more implementation complexity. At our scale (~thousands of audit records per day), O(n) verification takes milliseconds.

### D5: BacktestRunner as Wrapper — Zero API Change

**Decision**: `BacktestRunner.run(bars, signals, timestamps)` internally creates an `EventEngine`, registers handlers, converts bars to `MarketEvent`s, runs, and collects results into the existing `BacktestResult` format.

```python
class BacktestRunner:
    def run(self, bars, signals, timestamps) -> BacktestResult:
        engine = EventEngine(config=self._event_config)
        engine.register_handler(EventType.MARKET, self._on_market)
        engine.register_handler(EventType.ORDER, self._on_order)
        engine.register_handler(EventType.FILL, self._on_fill)
        for i, bar in enumerate(bars):
            engine.push(MarketEvent(...))
        engine.run()
        return self._collect_results()
```

**Rationale**: All existing tests, MCP facades, and dashboard integrations continue to work. The event-driven architecture is an internal refactoring, not an API change.

## Risks / Trade-offs

**[Risk: Backtest performance regression]** → Event dispatch adds overhead vs. direct function calls. **Mitigation**: Profile and optimize. The deque + handler dispatch should add <5% overhead. If problematic, add a fast-path for non-drill-down bars.

**[Risk: Synthetic tick generation quality]** → Generated ticks may not match real market microstructure. **Mitigation**: Constrain synthetic paths to bar OHLCV bounds. This is still more accurate than assuming close-price execution.

**[Risk: Audit trail storage growth]** → ~4 records per bar (market, signal, order, fill) × 252 days × 1 symbol = ~1000 records/year. Trivial. **Mitigation**: Configurable retention + archival.

**[Risk: Deterministic replay requires exact git commit]** → Strategy code changes between record time and replay time will cause divergence. **Mitigation**: Audit records store `git_commit`. Replay explicitly checks out the recorded commit before running.
