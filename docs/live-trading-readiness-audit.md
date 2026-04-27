# Live Trading Readiness Audit (Phase 0)

This audit verifies what `docs/live-trading-gap-analysis.md` and
`docs/architectural-review-event-driven.md` flagged against the actual
codebase, with file:line citations. It is the gate for Phases 1–6 of the
plan in `.claude/plans/based-on-the-above-mellow-lemur.md`.

Verdict legend:
- **GREEN** — implementation matches the OpenSpec contract or doc claim
- **YELLOW** — implementation exists but is missing a wire-up (callable but never called)
- **RED** — missing entirely or non-functional

| Component | Verdict | Evidence |
|---|---|---|
| Tick → 1m bar aggregator | GREEN | `src/broker_gateway/live_bar_store.py:106-155` |
| Tick fan-out from `_on_tick` | GREEN | `src/broker_gateway/sinopac.py:221` (ingest) + `:231` (WS push) |
| Multi-TF folding (5m, 1h) | GREEN-PARTIAL | `live_bar_store.py:35` `_STREAMING_TFS = [(5, "ohlcv_5m"), (60, "ohlcv_1h")]` — 5m/1h only, no 3m/15m/30m |
| Bar callback fan-out into runners | GREEN | `src/execution/live_pipeline.py:207` `register_bar_callback(self._on_bar_complete)`; line 440 `await runner.on_bar_complete(symbol, bar)` |
| `LiveStrategyRunner` (the "missing locomotive") | GREEN | `src/execution/live_strategy_runner.py:381` `on_bar_complete()` evaluates engine and emits orders |
| `LiveExecutionEngine` wiring | GREEN | `live_strategy_runner.py:286-290` constructs and binds in live mode |
| Session close force-flat (04:59 / 13:44) | GREEN | `live_strategy_runner.py:738-749` `_is_session_close_bar` + `_force_flat` line 705 |
| Daily ATR live cache | GREEN | `live_strategy_runner.py:557-624` per-trading-day cache from `market.db` |
| Per-strategy bar resampling | YELLOW | `live_strategy_runner.py:416-428` `_bar_buffer` / `_resample_buffer` — fragile decentralised aggregation; replace via Phase 2 router |
| Risk monitor: `daily_loss_limit_pct` (2% AUM) | GREEN | `src/risk/monitor.py:269` cap loaded from config; `_is_daily_loss_breached` line 267 |
| Risk monitor: 3-second feed staleness check | GREEN-CODE / RED-WIRING | `risk/monitor.py:227-249` implements the check, but `update_feed_time` is only called by `src/pipeline/runner.py:89` (backtest). **Live bars never call it.** |
| Risk monitor: stale-feed protective exits | GREEN | `risk/monitor.py:246` `protective_exits_only=bool(account.positions)` |
| Reconciliation startup freeze + manual resume | GREEN | OpenSpec change `intraday-live-trading-readiness` tasks 4.1–4.4 marked `[x]` in `tasks.md`; reconciler wired in `live_pipeline.py:222` |
| Continuity cursor `get_order_events_since` | GREEN | `src/broker_gateway/sinopac.py:565`; `abc.py:36`; `types.py:69` continuity_cursor field; `mock.py:204` test impl |
| `MultiTimeframeRouter` for 3m/15m/30m | RED | No module exists; aggregation is per-strategy (see YELLOW row above) |
| Strategy warmup from DB | RED | Grep for `warmup`/`hydrate`/`prefetch_history` in `src/` returns 0 hits. `EmaTrendPullback` `ema_trend=144` cold-starts on garbage. |
| `warmup_mode` flag in `PositionEngine` | RED | `on_snapshot` always emits orders; no suppress flag |
| `Clock` abstraction | RED | No `class Clock` anywhere; `datetime.now()` in 40 files |
| Tick staleness watchdog at bar-source layer | RED | `live_bar_store.py` does not track `_last_tick_ts` per symbol; risk monitor relies on `update_feed_time` which is not wired live (see above) |
| Background Sinopac reconnect loop | RED | `sinopac.py:283` `_maybe_reconnect_disconnected` only called on-demand from `_fetch_snapshot`; no `asyncio.create_task` reconnect loop in lifespan |
| Persistent `OrderStateStore` (orders SQLite table) | RED | No `orders` or `pending_orders` table in `trading.db`; `LiveExecutor._pending` is in-memory dict (`src/execution/live.py:53`) |
| Unified playback ↔ live driver | RED | `src/api/routes/playback_engine.py` and `live_strategy_runner.py` are separate code paths |

## Notes on doc accuracy

The two source docs over-claimed missing features. Items they marked
"missing" that already exist:

- **`LiveStrategyDriver` ("the missing locomotive")** — exists as
  `LivePipelineManager` (`src/execution/live_pipeline.py`) plus
  `LiveStrategyRunner`. The doc's recommended wiring (subscribe to bar
  closes, fan into `PipelineRunner.run_step`) is implemented at
  `live_pipeline.py:207` (callback) → `:440` (per-runner dispatch).
- **`LiveExecutionEngine` "orphaned"** — wired by
  `live_strategy_runner.py:286-290`. Used in `live` mode only; `paper`
  mode swaps `PaperExecutionEngine`.
- **`SessionManager.poll_all()` "never drives strategy"** — accurate
  for `SessionManager` itself, but the actual driver is
  `LivePipelineManager`. The architecture is bar-driven, not
  poll-driven, which matches the doc's "event-bus" prescription.
- **Daily ATR "stale in live"** — refreshed once per trading day from
  `market.db` via `_compute_daily_atr` (`live_strategy_runner.py:587`).
- **Session close force-flat** — implemented at the runner.

## Wiring gap that matters for Phase 4

The 3-second feed staleness check exists in
`risk/monitor.py:227-249` and matches OpenSpec spec
`risk-monitor/spec.md` `Critical stale price feed` scenario. But the
*input* to that check, `update_feed_time(ts)`, has only one caller
(`pipeline/runner.py:89`, the backtest/research path). In live trading
the function is never invoked, which means the risk monitor's stale-feed
trip never fires regardless of broker silence.

Phase 4 must add a call site in either:
- `LivePipelineManager._on_bar_complete` (every bar close updates feed
  time), and/or
- A dedicated tick-side hook in `LiveMinuteBarStore.ingest_tick` that
  pushes per-tick feshness into the monitor.

## Conclusion

The plan in `.claude/plans/based-on-the-above-mellow-lemur.md` is
proceeding to Phase 1. No GREEN row blocks the next phase; the YELLOW
and RED rows map cleanly onto Phases 1–6.
