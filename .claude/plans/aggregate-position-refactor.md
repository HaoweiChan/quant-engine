# Plan: aggregate-Position refactor — close the residual MCP-vs-simulator gap

## Context

The previous plan (`per-position-trail-stops-mighty-wozniak.md`) closed two of three structural gaps in the production engine:
- ✅ Intra-bar stop trigger (`bar_low`/`bar_high` pierce)
- ✅ Whole-book exit on stop trigger
- ✅ Stop fill at the trigger level (with realistic friction stacking on top)

`compounding_trend_long_mtf` MCP backtest improved from **2.80× / Sharpe 1.70** to **3.40× / Sharpe 2.23** on TX 2025-06-11..2026-04-24. The standalone simulator over the same window reaches **50.96× / Sharpe 4.02**. A 14× residual gap remains.

The architect's review identified the cause: **`PositionEngine._execute_add` at `src/core/position_engine.py:396` spawns a new `Position` object for every `AddDecision`**, with `pyramid_level = len(self._positions)`. The strategy is throttled by:

1. The pyramid policy gate (`PyramidAddPolicy.should_add` at `src/core/policies.py:159`) blocking adds when `engine_state.pyramid_level >= max_levels`. With max=400 in TRENDING_UP, theory says 400 lots are reachable.
2. **In practice the engine adds at most ~33 lots per cycle** because every snapshot allows only one `AddDecision` (the policy emits `lots=1.0`), and a single new Position object per snapshot — so a 5m bar that could absorb 20 lots' worth of free margin only adds 1.

The standalone simulator (`experiment/scripts/compounding_trend_long_mtf_replication.py:418-432`) sidesteps this by treating the book as a single integer lot count: `while free_cap >= 1.10 × initial_margin: lots += 1`. That while-loop scales position to 400 lots in one bar when margin allows it. Production cannot replicate this without a **single aggregate Position per direction**.

## Approach: direction-scoped aggregate slot (recommended)

The Explore agent surveyed three migration shapes and recommended Option 3 — the cleanest semantics with the largest payoff.

**Core idea**: PositionEngine holds at most one `Position` per direction. `AddDecision` increments `lots` and recomputes `weighted_avg_entry_price` in place rather than appending a new object. Every consumer that today reads per-Position `entry_price` switches to `weighted_avg_entry_price`. Every consumer that today derives pyramid depth from `len(self._positions)` switches to `Position.highest_pyramid_level`.

The backtester already does weighted-average accounting in `src/simulator/backtester.py:178` (`avg = (entry_price * entry_lots + fill.fill_price * fill.lots) / total_lots`). The engine just needs to mirror what the backtester is already computing.

## File changes

### File 1: `src/core/types.py` (Position dataclass at lines 117-132)

Add three fields with `field(default=...)` so existing constructions don't break:

```python
@dataclass
class Position:
    entry_price: float                    # last add's price (kept for UI/debug)
    lots: float                           # TOTAL lots across the aggregate book
    contract_type: str
    stop_level: float
    pyramid_level: int                    # synonym for highest_pyramid_level (kept for API parity)
    entry_timestamp: datetime
    direction: Literal["long", "short"] = "long"
    position_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    # NEW
    weighted_avg_entry_price: float | None = None  # None means "use entry_price"
    base_lots: float = 0.0                # lots at pyramid_level=0; shielded by min_hold_lots
    highest_pyramid_level: int = 0        # tracks max depth reached, never decreases
```

`__post_init__` validates `weighted_avg_entry_price > 0` if provided. `Position.replace(**changes)` helper for trail stop updates that need new objects.

### File 2: `src/core/position_engine.py`

**`_execute_add` at lines 359-420** — biggest change. Replace the append-new-Position branch with mutate-in-place:

```python
def _execute_add(self, decision: AddDecision, snapshot, account=None) -> list[Order]:
    if not self._positions:
        return []  # no aggregate position to add to
    pos = self._positions[0]  # direction-scoped: at most one per direction
    if decision.move_existing_to_breakeven:
        pos = self._move_to_breakeven(pos)

    new_lots_total = pos.lots + decision.lots
    # Weighted-average entry: matches backtester's open_entries[sym] math.
    prior_avg = pos.weighted_avg_entry_price or pos.entry_price
    new_avg = (prior_avg * pos.lots + snapshot.price * decision.lots) / new_lots_total

    self._positions[0] = pos.replace(
        entry_price=snapshot.price,
        weighted_avg_entry_price=new_avg,
        lots=new_lots_total,
        pyramid_level=pos.highest_pyramid_level + 1,
        highest_pyramid_level=pos.highest_pyramid_level + 1,
        entry_timestamp=snapshot.timestamp,
    )

    # Emit ONE Order with decision.lots (the add-side delta, not the new total).
    # Order construction is unchanged; Fill model still gets per-add lots.
    return [Order(..., lots=decision.lots, ...)]
```

**`_check_stops` at lines 184-266** — already supports whole-book exit. With direction-scoped slot, `whole_book_exit_on_stop=True` is implicit (one Position per direction, exiting it is the whole book). Keep the flag for backward compatibility but the underlying behavior simplifies. The `min_hold_lots` shield needs a tweak: instead of `pos.pyramid_level == 0`, it now means "leave `pos.base_lots` worth of contracts on a stop trigger". Implementation: when triggered AND `min_hold_lots > 0`, emit an Order for `pos.lots - pos.base_lots` (partial exit) instead of `pos.lots` (full exit).

**`get_state` at line 161** — `pyramid_level=pos.highest_pyramid_level if self._positions else 0` (was `len(self._positions)`).

**`_update_trailing_stops`** — already uses `pos.replace(stop_level=...)`; no change needed.

### File 3: `src/core/policies.py`

**`PyramidAddPolicy.should_add`** at lines 159, 169, 187, 193-207:
- Line 159: `if engine_state.pyramid_level >= self._max_levels` — already reads `pyramid_level`, which now comes from `Position.highest_pyramid_level`. **Works as-is.**
- Lines 187-193: reference price for floating-profit gate — switch from `engine_state.positions[0].entry_price` to `engine_state.positions[0].weighted_avg_entry_price or entry_price`.
- Lines 193-207: lot schedule indexing — `lot_schedule[engine_state.pyramid_level]`. **Works as-is** because `pyramid_level` is the depth reached.

**`ChandelierStopPolicy`** at lines 244-253: switch `entry_price` reads to `weighted_avg_entry_price or entry_price`. Same pattern across every stop policy.

### File 4: `src/strategies/swing/trend_following/compounding_trend_long_mtf.py`

`_RegimeAwareAdd.should_add` at line 624: `engine_state.pyramid_level >= preset["max_lots"]` is the cap gate. With aggregate-Position, `pyramid_level` becomes "highest add depth", which still maps to "how many adds have been issued" — so the cap holds. **No change needed**, but document the new semantics in a comment.

The strategy currently emits `AddDecision(lots=1.0, ...)` in a tight per-bar loop. Once the engine aggregates, this will compound naturally because the engine no longer creates per-add Position objects. Optionally, the AddPolicy can emit `lots=N` (multiple at once) when free margin allows — that's a follow-up tuning.

### File 5: `src/strategies/swing/trend_following/vol_managed_bnh.py`

`_OverlayHub` overlay logic at lines 252, 314: relies on `engine_state.pyramid_level >= 2` to prevent overlay compounding. Aggregate-Position keeps this semantics — `highest_pyramid_level` still tracks adds. **No change needed.**

The `min_hold_lots=1.0` config (line 417) requires the engine's stop logic to honor `base_lots` (see File 2). Specifically: a stop trigger on the overlay must NOT close the base 1.0 lot. The new `base_lots` field on Position handles this.

### File 6: `src/simulator/backtester.py`

**`AccountState` margin computation** at lines 270-282: `margin_used = sum(p.lots * snapshot.margin_per_unit for p in state.positions)`. Already iterates `state.positions` and sums lots — works transparently with one Position per direction since `pos.lots` is the aggregate now.

**Unrealized PnL** at line 212: same — iterates positions, sums per-position PnL using `(price - entry_price) * lots`. Switch to `weighted_avg_entry_price or entry_price` so PnL is computed against the true cost basis.

**`open_entries` dict** at lines 79, 166-181: this is the *trade log* matching machinery, separate from `Position` state. **No change needed** — it already does weighted-average aggregation.

### File 7: `src/execution/live_strategy_runner.py`

Line 530: `state.positions[-1]` reads the most recent add's `entry_price`. Switch to `state.positions[0].weighted_avg_entry_price or entry_price` (with direction-scoped slot, there's only one Position per direction; `[-1]` happens to work but the intent is "the aggregate").

### File 8: New tests

- `tests/unit/test_position_aggregate.py` — pin the new Position fields:
  1. New entry: `weighted_avg_entry_price == entry_price`, `base_lots == lots`, `highest_pyramid_level == 0`.
  2. After one add at higher price: `weighted_avg_entry_price` is the lot-weighted average; `lots` is total; `highest_pyramid_level == 1`; `base_lots` unchanged.
  3. After 5 adds: `lots` is sum, `weighted_avg_entry_price` is the running weighted average, `highest_pyramid_level == 5`.
  4. With `min_hold_lots=1.0` and a stop trigger: emit Order for `lots - base_lots`, leave `base_lots` open.
  5. Mixed direction (long position open, short AddDecision in different direction) — should reject (one direction per book) OR open a separate short slot.

- `tests/unit/test_position_engine_aggregate.py` — pin the engine integration:
  1. After 10 AddDecisions on the same direction, `len(engine._positions) == 1` (was 10).
  2. `EngineState.pyramid_level` == 10 (not list length, but accumulated depth).
  3. `_check_stops` with `whole_book_exit_on_stop=True` emits ONE Order with `lots=total_aggregate_lots`.
  4. ChandelierStopPolicy.update_stop reads `weighted_avg_entry_price` correctly.

### File 9: Migration of existing tests

~30 tests assert on `len(state.positions)` or `len(self._positions)`. Audit:
- `tests/unit/position_engine/test_position_engine.py` lines 36, 269, 545
- `tests/unit/position_engine/test_position_engine_disaster.py` lines 99, 120, 129
- `tests/unit/position_engine/test_position_engine_add_sizer.py` line 128
- `tests/trading_policies/test_policies.py` (multiple)
- `tests/unit/test_position_engine_intrabar_stop.py` line 142 (multi-position whole-book test)

Each assertion swaps `len(positions) == N` for `positions[0].highest_pyramid_level == N - 1` (since base entry is depth 0, each add is +1).

### File 10: Backward compat shim (for transition period)

Keep `Position.pyramid_level` as a property aliasing `highest_pyramid_level` so existing readers don't break during the migration. Once all consumers are updated, the field can be unified.

## Verification

1. **Pre-refactor baseline**: capture current MCP metrics for every strategy in `experiment/out/baseline_pre_aggregate.json`. Goal-post for non-regression.
2. **Phase 1 — Position dataclass**: write the new fields + helper, run `pytest tests/unit/ -q` to confirm no existing tests break (defaults preserve old API).
3. **Phase 2 — Engine internals**: refactor `_execute_add`, `_check_stops`, `get_state`. Run `tests/unit/test_position_aggregate.py` + `test_position_engine_aggregate.py` (new, should pass) AND `tests/unit/position_engine/` (existing, expect ~30 failures — fix them in this phase).
4. **Phase 3 — Policy adapters**: switch `entry_price` → `weighted_avg_entry_price or entry_price` in `policies.py` and stop policies. Run `pytest tests/trading_policies/` (expect adjustments).
5. **Phase 4 — Strategy verification**: re-run MCP backtests for ALL 4 strategies in baseline_pre_aggregate.json. Acceptable outcomes:
   - `night_session_long`, `vol_managed_bnh`: equity curve within ±2% of baseline (small drift OK from aggregate semantics)
   - `compounding_trend_long`: minor drift (≤5%) acceptable — daily strategy with few adds
   - `compounding_trend_long_mtf`: **TARGET 20×–40× / Sharpe 3.0–3.6** (up from 3.40×/2.23). If still <15×, the bottleneck is elsewhere — escalate.
6. **Phase 5 — Walk-forward**: 6-fold WF on `compounding_trend_long_mtf`. Aggregate OOS Sharpe should match the simulator's regime-dependent signature (positive in trend, negative in chop, aggregate ~1.8-2.5).
7. **Phase 6 — Live runner sanity**: `pytest tests/integration/execution/` to ensure live strategy runner still serializes/restores state correctly (one Position per direction).

## Critical files

- `/home/willy/invest/quant-engine/src/core/types.py` (Position dataclass — add 3 fields)
- `/home/willy/invest/quant-engine/src/core/position_engine.py` (`_execute_add`, `_check_stops`, `get_state`)
- `/home/willy/invest/quant-engine/src/core/policies.py` (PyramidAddPolicy, ChandelierStopPolicy entry_price reads)
- `/home/willy/invest/quant-engine/src/simulator/backtester.py` (unrealized PnL formula)
- `/home/willy/invest/quant-engine/src/strategies/swing/trend_following/compounding_trend_long_mtf.py` (no behavioral change; comment update)
- `/home/willy/invest/quant-engine/src/strategies/swing/trend_following/vol_managed_bnh.py` (verify min_hold_lots semantics with new base_lots)
- `/home/willy/invest/quant-engine/src/execution/live_strategy_runner.py` (line 530 `[-1]` access)
- `/home/willy/invest/quant-engine/tests/unit/test_position_aggregate.py` (NEW)
- `/home/willy/invest/quant-engine/tests/unit/test_position_engine_aggregate.py` (NEW)
- ~30 existing tests under `tests/unit/position_engine/` and `tests/trading_policies/` (assertion rewrites)

## Existing utilities to reuse (do NOT duplicate)

- Backtester's `open_entries[sym] = (avg_price, total_lots, side)` aggregation at `backtester.py:166-181` — the canonical weighted-average implementation, mirror it in `_execute_add`.
- `Position.replace(...)` pattern — already used in `_update_trailing_stops` to rebuild Position with a new `stop_level`. Extend to all mutations (lots, weighted_avg_entry_price, etc).
- `EngineState.pyramid_level` field — keep the API; just change its source from `len(_positions)` to `_positions[0].highest_pyramid_level`.
- `metadata['fill_price_override']` mechanism on Order — already plumbed end-to-end. Aggregate adds use the same path; no new metadata needed.

## Why NOT keep the per-Position model and patch around it

Three alternatives rejected after exploration:
1. **"Have AddPolicy emit `lots=N` (batched) so each per-Position add covers more ground"** — addresses the symptom not the cause; the engine still creates many Position objects, each with its own entry_price, requiring whole-book stop alignment work that's already maxed out. Doesn't fix the `len()`-based pyramid_level overflow when `lots` keeps growing.
2. **"AggregatePosition wrapper"** (Option 2 from explore) — exposes a façade over `_positions: list[Position]`. Dual API, hard to debug, doesn't fix the per-Position fill semantics.
3. **"In-place mutation without direction-scoping"** (Option 1) — keeps `_positions` as a list but tries to fold each add into the first element. Works in theory but breaks the `parent_position_id` linkage on Orders and complicates serialization.

Option 3 (direction-scoped slot) is the only one that aligns the engine with what the backtester is already doing.

## Risk assessment

**Highest-risk change**: `_execute_add` rewrite. Any bug here misprices the weighted-average entry, which corrupts PnL across every strategy that pyramids. Mitigation: phase 1 unit tests pin the math against the backtester's `open_entries` reference.

**Highest-blast-radius change**: `entry_price` → `weighted_avg_entry_price` in stop policies. Touches every long-only trend-following and breakout strategy. Mitigation: backward-compat shim — `weighted_avg_entry_price=None` falls back to `entry_price`. Existing strategies that don't pyramid see no change.

**Lowest-risk wins**:
- Direction-scoped slot is invisible to consumers that iterate `state.positions` and sum lots (they get the aggregate naturally).
- Backtester PnL is unchanged — `open_entries` already does the math we're moving into the engine.

## Expected outcome

Based on the simulator's behavior + the architect's analysis:

- `compounding_trend_long_mtf`: **20×–40× / Sharpe 3.0-3.6** (up from 3.40×/2.23). If lower than 15×, there's a fourth gap (likely in the regime classifier or the 1h gate's add-throttling).
- `compounding_trend_long` (v1 daily): minor drift (≤5%) — daily strategy with few adds, mostly unaffected.
- `night_session_long`, `vol_managed_bnh`: equity curve within ±2% — these don't pyramid materially or use `min_hold_lots` shield correctly.

If the post-refactor `compounding_trend_long_mtf` lands in the 20-40× band, the engine matches the simulator's structural intent and the residual delta from 50.96× is the realistic cost of execution friction (slippage / impact / spread / latency) that the simulator omits. That's an acceptable production result.

## Out of scope (deliberate)

- Tightening `MarketImpactFillModel` parameters — accepted as realistic friction.
- Changing live execution code paths beyond the `[-1]` fix — `LiveStrategyRunner.on_bar_complete` already iterates positions; aggregate-Position is transparent.
- Multi-symbol aggregation — keep one Position per (symbol × direction); cross-symbol portfolio aggregation is a separate concern.
- Walk-forward parameter tuning — once the engine matches simulator shape, parameter optimization is a follow-up Ralph.
- Removing the three opt-in flags from `EngineConfig` — they're still useful for non-pyramiding strategies. Default ON for new strategies, default OFF for legacy.
