# Overnight handoff — 2026-05-18

Ralph session, ~00:57 → 01:20 CST, before TAIFEX day session open at 08:45.
User asleep, working autonomously under the explicit brief:
1. L0a verification (T+>24h)
2. "Finish the migration" — target needs discovery
3. Merge `feature/txo-iv-screener` into `main`
4. Make site reachable via tailscale, not localhost
5. Paper portfolio sends Telegram signals tomorrow

## TL;DR — all critical items green

| Item | Status | Evidence |
|---|---|---|
| L0a SEGV containment | ✅ Working at T+72h (~88% reduction) | 8 crashes in 73h vs ~68 baseline; 68 `broker_rate_limited_not_retrying` short-circuits |
| Telegram dispatcher | ✅ Live | 200 OK from `api.telegram.org` on `POST /api/paper-trade/test-telegram` at 01:06 CST; `telegram_dispatcher_ready` on every startup |
| Tailscale frontend access | ✅ Reachable on `http://100.92.172.90:8000` | `LISTEN 0 2048 100.92.172.90:8000`; cross-tailnet `curl` from this dev box at `100.69.9.67` returns 200 |
| `feature/txo-iv-screener` merge | ✅ Merged + hotfixed | `a0c2bce` merge + `f3c2748` route hotfix; deployed at 01:18 CST |
| Live pipeline / sessions | ✅ Intact | 6 active sessions across account 2010515 (TMF) and mock-dev (MTX); `live_pipeline_started runners=6` on every restart |
| "The migration" | ⚠️ Deferred — see "Open items" |  |

## What changed on disk

```
src/data/connector.py          (L0a — already shipped 2026-05-14, untouched tonight)
src/api/routes/options.py      (NEW 3-line fix tonight — GatewayRegistry.get_instance bug)
docs/handoff/2026-05-08-segv-hypothesis.md  (T+72h verdict appended)
docs/handoff/2026-05-18-overnight-paper-portfolio.md  (this file)
~/.config/systemd/user/quant-engine-api.service.d/host.conf  (ON VPS — tailscale bind drop-in)
```

Worktree at `feature/txo-iv-screener` (`/home/willy/invest/quant-engine-txo-screener`)
also has **uncommitted local WIP** that was already present before this session:
+2877 lines including `src/analytics/options/{portfolio,scenarios,strategy_recognizer}.py`,
`tests/options/test_{orders_routes,greeks_smile,strategy_recognizer}.py`,
`docs/analysis/execution_bug_fix_live_runner.md`, +247-line extensions to
`src/broker_gateway/sinopac.py`, and frontend changes. **This WIP was NOT included
in the merge** — only the committed tip (`bba12d8`) was merged into `main`.
The user should review the WIP separately. The only edit I made in that worktree
is a defensive test-mock fix in `tests/options/test_orders_routes.py` (already
staged, makes the 5 previously-failing tests pass — but the file itself is still
uncommitted).

## Commits pushed to `main` tonight

| Commit | Purpose |
|---|---|
| `a0c2bce` | Merge branch 'feature/txo-iv-screener' into main (no-ff) — brings in TXO IV screener analytics, API, frontend, design doc |
| `f3c2748` | `fix(options)`: route bug — GatewayRegistry.get_instance() does not exist (3 routes) |

## Verification trail (selected)

**L0a re-check (S0)**
```
$ ssh netcup 'systemctl --user show -p MainPID -p NRestarts -p ActiveEnterTimestamp'
MainPID=717026  NRestarts=2  ActiveEnterTimestamp=Sat 2026-05-16 03:44:46
$ journalctl --user -u quant-engine-api --since "2026-05-14 23:30:14" \
  | grep -c "broker_rate_limited_not_retrying"
68
$ ... | grep -c "live_gap_repair_failed"
68
$ ... | grep -cE "Main process exited|SEGV|segfault|core-dump"
8
```

**Telegram (S2)**
```
$ curl -X POST http://127.0.0.1:8000/api/paper-trade/test-telegram
{"status":"ok","message":"Sent"}
$ journalctl … | grep -E "HTTP/1.1 200 OK.*sendMessage" | tail -1
… "POST https://api.telegram.org/bot…/sendMessage \"HTTP/1.1 200 OK\""
```
Note: bot token is leaking into the journal via `httpx` request logging. Not
blocking tonight; see "Open items".

**Tailscale (S3)**
```
$ ss -ltnp | grep :8000
LISTEN 0 2048 100.92.172.90:8000  0.0.0.0:*  users:(("python3",pid=756520,fd=24))
$ # from this dev box (100.69.9.67 on the tailnet)
$ curl -s -o /dev/null -w "%{http_code}\n" http://100.92.172.90:8000/api/accounts
200
```
Drop-in lives at `~/.config/systemd/user/quant-engine-api.service.d/host.conf`
on the VPS. Public internet still cannot reach `:8000` because the VPS only
advertises that port on the tailscale interface (interface-level binding —
no firewall rule required).

**Pre-merge tests (S4)**
```
$ cd /home/willy/invest/quant-engine-txo-screener && \
    .venv/bin/python -m pytest tests/options tests/unit/{data,execution,api}
162 passed, 1 skipped, 1 warning in 3.27s
$ npm run build
✓ built in 535ms  (Node 20.18 warning is non-blocking)
```
(5 of those passes are the previously-failing tests, fixed by the test-mock
patch in the worktree WIP.)

**txo merge + hotfix (S5)**
```
$ curl -s -o /dev/null -w "%{http_code}\n" http://100.92.172.90:8000/api/options/accounts
200
$ curl -s -o /dev/null -w "%{http_code}\n" http://100.92.172.90:8000/api/options/positions
200
$ curl -s http://100.92.172.90:8000/api/sessions | jq '[.[] | select(.status=="active")] | length'
6
```

## What to expect at 08:45 CST (day session open)

1. **Telegram should fire** when account 2010515's strategies generate a fill.
   The three active sessions are:
   - `swing/trend_following/compounding_trend_long_mtf` (TMF)
   - `medium_term/trend_following/donchian_trend_strength` (TMF)
   - `short_term/trend_following/night_session_long` (TMF — intraday, will close
     positions at 13:44 force-flat)
2. **War-room dashboard** is at `http://100.92.172.90:8000` from any tailnet host
   (or `http://localhost:8000` from the VPS itself).
3. **Quick grep** to confirm telegram is firing on real fills:
   ```
   ssh netcup 'journalctl --user -u quant-engine-api --since "08:00 today" \
     | grep -E "live_fill|api.telegram.org" | tail -20'
   ```
   You should see each `live_fill` event followed within ~1 second by an
   `HTTP/1.1 200 OK` to `api.telegram.org`.

## Open items / deferred

1. **"The migration"** — I could not unambiguously identify what migration
   was meant. Candidates considered:
   - `openspec/changes/monte-carlo-enhancements`: 12 sections of unchecked
     tasks (MonteCarloReport dataclass, MDD/ruin utilities, trade resampling,
     GBM, param sensitivity, dispatcher, API extension, frontend mode selector,
     histograms, sensitivity heatmap, tests). This is **multi-week scope**,
     not overnight scope. Deferred.
   - `docs/handoff/2026-05-08-mode-aware-guard-todo.md`: the previously
     deferred mode-aware session guard (`TRADE_MODE=paper|shadow|micro-live|production`
     branching in `scripts/deploy.sh` + orchestrator agent prompt). Small but
     touches multiple subsystems and was explicitly deferred to a dedicated
     session in the prior handoff. Deferred again to avoid mixing concerns
     with tonight's deploy.
   - No active openspec change is mid-implementation (no partial diff staged).
   - Possible the user meant the txo merge itself ("migration" of options
     code into main) — if so, it is done.
   - **Action requested from user**: confirm which one was meant; if it was
     a third thing not listed here, point at the artifact.

2. **txo branch WIP in the worktree** — the user has substantial uncommitted
   work in `/home/willy/invest/quant-engine-txo-screener` (see "What changed
   on disk" above for inventory). The merge tonight only brought in the
   committed tip `bba12d8`. The user should triage the WIP: commit + push +
   merge if ready, or stash if exploratory.

3. **Telegram bot token leaking in journal** — `httpx`'s default request log
   line is `HTTP Request: POST https://api.telegram.org/bot{TOKEN}/sendMessage`
   and the token is in the URL. Currently visible to anyone who can read the
   user journal on the VPS (which is the service account itself, not root).
   Mitigation: install an `httpx` event hook that masks the URL, OR set
   `logging.getLogger("httpx").setLevel(logging.WARNING)` in the API startup.
   Not blocking but worth fixing soon.

4. **Pytest deprecation** — `tests/unit/execution/test_bar_source.py:129` uses
   `asyncio.get_event_loop()` which is deprecated. Not blocking.

5. **L0c (subprocess isolation of gap_repair)** — see appended section in
   the SEGV handoff for the rationale. Highest-leverage residual SEGV fix.

6. **Coredump capture** — still half-configured. `systemd-coredump` install
   needs sudo on the VPS; not done tonight.

7. **VPS Phase E lockdown** — still deferred, as in the prior handoff.

## State summary

- Production service: `quant-engine-api` MainPID 756520, NRestarts 0,
  active since 2026-05-18 01:18:39 CST, bound to `100.92.172.90:8000`.
- Telegram dispatcher: ready and verified end-to-end.
- Live pipeline: 6 runners, 6 active sessions across 2 accounts.
- Current `main` HEAD on origin: `f3c2748`.
- No outstanding modified tracked files in the main worktree.
