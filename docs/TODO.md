# Tracked TODOs

Tracked items deferred from active work. Each entry references the analysis
or context that produced it.

---

## Split sync-vps-data.sh to prevent silent data loss under concurrent writes

**Status:** open
**Filed:** 2026-05-06
**Source:** WSL/VPS migration — Phase B audit (`.claude/plans/vps_stability_migration_plan_wsl.md`)

### Problem

`scripts/sync-vps-data.sh` runs a bidirectional rsync over four databases
(`market.db`, `trading.db`, `param_registry.db`, `portfolio_opt.db`) using
mtime-based reconciliation (`rsync --update`). It treats every DB as
two-way writable, but in practice ownership is split:

| DB | Writer | Today's sync direction |
|---|---|---|
| `market.db` | VPS-only (live data daemon) | bidirectional ⚠ |
| `trading.db` | VPS-only (live execution engine) | bidirectional ⚠ |
| `param_registry.db` | local-only (backtest sweeps, walk-forward) | bidirectional ⚠ |
| `portfolio_opt.db` | local-only (portfolio optimizer) | bidirectional ⚠ |

`--update` keeps whichever side has the newer mtime. That works as long as
no DB is concurrently written on both ends. If a stale process or a routine
that touches a file (cron, tooling, even an ill-timed `sqlite3 ... vacuum`)
bumps mtime on the wrong side, `--update` cannot merge content — one side
wins entirely and the other side's writes are lost.

### Concrete evidence (captured 2026-05-05)

```
                Local            VPS              Delta
market.db       871 MB May 4     872 MB May 5     VPS newer
trading.db      111 MB Apr 28    111 MB May 5     VPS newer
param_registry  3.8 GB May 4     2.9 GB May 1     local newer (~900 MB)
portfolio_opt   136 KB Apr 28    120 KB May 1     local newer
```

`param_registry.db` carrying ~900 MB of local-only research output is exactly
the failure mode this issue exists to prevent.

### Proposed fix

Split into two unidirectional scripts that codify ownership:

- `scripts/sync-pull-prod.sh` — VPS → local for `market.db`, `trading.db`.
  Read-only producer mirror for backtest research that wants today's bars.
- `scripts/sync-push-research.sh` — local → VPS for `param_registry.db`,
  `portfolio_opt.db`. Research output published back to the VPS so dashboards
  and the optimizer registry see it.

Add a `safety-rails` mode to each script that refuses to run if it detects
the "wrong" DB being modified on its side recently (e.g. mtime drift on a DB
the script claims to own).

Keep `sync-vps-data.sh` as a thin wrapper that calls both, for users who
just want everything reconciled in one go.

### Why deferred

Migration scope is dev-environment + deploy pipeline. The sync split is a
data-layer correctness fix that touches workflow muscle memory; it deserves
its own change with a brainstorming pass and a paired test (e.g. simulated
mtime drift).
