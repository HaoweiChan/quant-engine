# Execution Bug: Multi-Entry Guard Persistence Analysis

## Problem Summary
When `LiveStrategyRunner` is recreated mid-session (via `_sync_runners()` deletion/recreation), the strategy policy's `_entered_this_session` guard is reset, allowing duplicate entries in the same session.

**Current Flow:**
- Broker reconnect → session status flickers (active → inactive → active)
- `_sync_runners()` called → deletes old runner (line 268: `del self._runners[sid]`)
- New runner created with fresh `NightSessionLongEntry` policy
- `_entered_this_session = False` on the new policy
- Strategy enters again on the same session

**Reproduction test proves**: 2026-04-20 session received 2 entries instead of 1 after mid-session runner recreation.

---

## Three Fix Options: Feasibility Analysis

### Option A: DB-Persisted Guard Table
**Approach:** Create `session_entry_recorded` table to persist which (session_id, strategy_slug) pairs have already entered.

**Pros:**
- ✅ Survives daemon restarts
- ✅ Atomic (SQL transaction-backed)
- ✅ Follows existing pattern (live_fills, session_snapshots already use trading.db)
- ✅ Can hook into existing snapshot store or create new minimal store

**Cons:**
- ❌ Adds DB round-trip on every bar (performance)
- ❌ Requires careful cleanup (old sessions)
- ⚠️  Must handle race between runner recreation and DB write

**Implementation Cost:** Medium
- Add table schema (~10 lines)
- Query guard on entry check (~5 lines in policy)
- Write guard on entry fill (~5 lines in runner)
- Cleanup job for old entries

**Feasibility:** **HIGH** — This is the most defensive option. Trading.db already tracks fills, so adding an entry guard is consistent.

---

### Option B: Runner-Level Guard (In-Memory + Eager Init)
**Approach:** Keep `_entered_session_ids: set[str]` at the runner level (not in policy), and populate it from `live_fills` on runner creation.

**How it works:**
1. On runner creation, query `live_fills` for fills in this session for this strategy
2. If any entry fills exist, add session_id to `_entered_session_ids`
3. Policy checks `runner._entered_session_ids` instead of `self._entered_this_session`
4. Runner survives recreation; policy can be stateless or lazy-loaded

**Pros:**
- ✅ No DB round-trips per-bar (query once at init)
- ✅ No new schema needed
- ✅ Survives runner recreation (guard lives in runner, not policy)
- ✅ No cleanup job needed (auto-scoped by session lifetime)
- ✅ Fast (set membership check is O(1))

**Cons:**
- ⚠️  Doesn't survive daemon restart (guard reloads from DB at init, which is OK)
- ⚠️  Requires passing runner ref to policy (slightly awkward API)

**Implementation Cost:** Low-to-Medium
- Query live_fills on runner init (~10 lines)
- Pass runner ref to policy __init__ (~5 lines)
- Policy checks `runner._entered_session_ids` instead of self (~3 lines)
- No cleanup

**Feasibility:** **VERY HIGH** — This is pragmatic. Survives the specific bug (runner recreation during session), and queries DB once per runner creation (not per bar).

---

### Option C: Soft-Removal Grace Period
**Approach:** Delay runner deletion by N seconds, with session status "soft_inactive" → "inactive". If session reactivates within the grace period, keep the runner alive.

**How it works:**
1. When session.status becomes "inactive" during a grace window (e.g. 30s), don't delete runner yet
2. If session.status becomes "active" again within grace window, keep runner and do nothing
3. After grace window expires, then delete runner

**Pros:**
- ✅ Simplest to understand (broker flicker → reconnect within grace window → no deletion)
- ✅ Survives restarts (runner state preserved)
- ✅ No DB queries, no new tables

**Cons:**
- ❌ Doesn't fix the case where reconnect takes >30s
- ❌ Doesn't fix intentional session stop/restart
- ❌ Requires adding grace-period logic to session manager
- ❌ Adds temporal coupling (must tune grace window carefully)
- ❌ Doesn't address the root cause (policy state should be persistent or query-backed)

**Implementation Cost:** Medium-to-High
- Add grace period state to session manager (~20-30 lines)
- Modify `_sync_runners()` to check grace period (~10 lines)
- Add async timer task (~15 lines)
- Requires testing of edge cases (reconnect timing)

**Feasibility:** **MEDIUM** — Addresses the common case (broker flicker) but not the general problem. Requires careful tuning and testing.

---

## Comparison Table

| Criterion | Option A (DB Guard) | Option B (Runner Init) | Option C (Grace Period) |
|-----------|-------------------|----------------------|------------------------|
| **Survives daemon restart** | ✅ Yes | ✅ Yes (query at init) | ✅ Yes |
| **Survives runner recreation** | ✅ Yes (DB query) | ✅ Yes (eager load) | ✅ Yes (no deletion) |
| **Fixes all cases** | ✅ Yes | ✅ Yes | ❌ Partial |
| **DB writes per bar** | ❌ Yes (overhead) | ❌ No | N/A |
| **DB queries per bar** | ❌ Yes (overhead) | ❌ No | N/A |
| **New schema** | ✅ Needed | ❌ No | ❌ No |
| **Implementation cost** | Medium | Low | Medium-High |
| **Test complexity** | Low | Low | High |
| **Production confidence** | Very High | Very High | Medium |

---

## Recommendation

**Option B (Runner-Level Guard via Eager Init)** is the best balance.

**Why:**
1. **Pragmatic** — Survives the bug (runner recreation) without per-bar overhead
2. **Minimal risk** — No schema changes, no DB writes during runtime
3. **Self-healing** — Reloads from DB on runner creation (survives daemon restart naturally)
4. **Obvious code** — Query live_fills once at init, pass runner ref to policy, check set membership
5. **Testable** — Reproduction test can verify the guard survives recreation

**Implementation sketch:**
```python
# In LiveStrategyRunner.__init__()
self._entered_session_ids = set()
# Query live_fills for entry fills in this session/strategy
rows = conn.execute(
    "SELECT DISTINCT session_id FROM live_fills "
    "WHERE session_id = ? AND strategy_slug = ? AND reason = 'entry'",
    (session_id, strategy_slug)
).fetchall()
self._entered_session_ids = {row[0] for row in rows}

# In NightSessionLongEntry.should_enter()
# Instead of: if self._entered_this_session: return None
# Use: if self._runner._entered_session_ids: return None
```

**Next step:** Implement Option B and verify the reproduction test passes.

