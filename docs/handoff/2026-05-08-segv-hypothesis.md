# SEGV Diagnosis — 2026-05-08

## TL;DR

Production `quant-engine-api` has crashed 109 times over May 04–08 (NRestarts metric showed 45 because counter resets per unit-start). Random sampling of 13 crashes classifies **92% (12/13) as the same fault path**: `live_bar_gap_detected` → `shioaji session-login` → Sinopac 451 "Too Many Connections" → retry loop in `src.data.connector` → fatal SEGV or ABRT inside the shioaji C++ binding during retry. The single outlier (May 04 first crash) followed a 13-month OHLCV API query and may be unrelated or a hidden variant. **Root cause is broker-binding instability under rate-limit retry, not application code, not data, not deploy state.**

## Crash distribution

- Lifetime: **109 SEGVs over May 04–08** (5 days, ~22/day average)
- Onset: May 04 17:58:21 — first ever SEGV
- Pattern: rising → peak May 05 (~46) → decay May 06 (~22) → May 08 (~12 partial)
- Median process lifetime: 30–60 min (rules out startup-load cause)
- Distribution NOT Poisson: 6/13 sampled crashes are **storm members** (another SEGV within ±10 min), 7/13 independent

## Trigger event (May 04)

Reflog confirms a commit burst was deployed via git pull around May 04, including:
- `e343158` fix(api): non-blocking startup + delay market-data subscriber to avoid 451
- `33e2567` fix(execution): bound startup aggregation + use main loop for resampled dispatch
- `8647bf5` feat(research): parallelize MCP backtest tools through Ray-backed worker pool
- `ccba361` feat(deploy): on-VPS self-watchdog with auto-restart on health failure
- `dfe1b4b` feat(deploy): production hardening for quant-engine-api systemd unit
- `74c844c` chore(deploy): remove obsolete taifex-data-daemon systemd unit

The `e343158` commit name **acknowledges 451 was a known issue pre-May 04** — the fix was a startup-delay band-aid, not a root-cause fix. Crashes started immediately after this commit went live, suggesting either:
- The "fix" reduced 451 frequency but did not eliminate it; subsequent 451s now route through a more crash-prone path
- One of the other commits in the burst introduced a new 451-triggering behavior

System packages were NOT changed pre-May 04 (kernel + libcurl upgrades came AFTER, on May 05–06).
Ray cluster runs on WSL only — confirmed not active on VPS — eliminates `8647bf5` as direct trigger.

## Crash classification (n=13 random sample, ~12% of population)

| Class | Count | % | Mechanism |
|---|---|---|---|
| A: 451-retry-shioaji | 12 | 92% | gap_repair → shioaji.login → 451 → retry loop → SEGV/ABRT in C++ binding |
| B: OHLCV-mmap | 1 | 8% | 13-month OHLCV API query → SEGV 4s later (mechanism unconfirmed) |
| C: Other | 0 | 0% | — |
| D: No signal | 0 | 0% | — |

**Storm structure within Class A:**
- 6/12 are storm members (uptime 44–57s, systemd 15s restart re-hits same broker rate limit)
- 6/12 are independent (uptime 17m–4h, fresh gap event triggers path)

**Sub-signals within Class A:**
- Exit signal: 10/12 SIGSEGV (=11), 2/12 SIGABRT (=6) — both terminal, both from same path
- Retry stage at fatal exit: distributed across retry 1, 2, 3, and post-retry-3 cleanup (no deterministic failure point)
- Symbols: 5x TX_R2, 5x MTX_R2, 2x cascading or unclear — no symbol bias
- 3/12 show `live_gap_repair_failed` event before SEGV (Python error handling fires; subsequent cleanup crashes)
- 1/12 shows cascading repair (TX_R2 fail → MTX_R2 attempt → SEGV in same process)

The non-deterministic retry-stage failure pattern is consistent with a use-after-free or refcount bug in the shioaji C++ binding, NOT a deterministic null-pointer-deref. This means simply skipping one retry stage will not protect against the bug — any code path that enters shioaji's C++ login machinery under 451 conditions can hit fatal memory corruption.

## Coredump status

- `LimitCORESoft=0` → process cannot dump core
- `core_pattern` set to apport handler
- `systemd-coredump` not installed
- **0 backtraces available from any of 109 SEGVs**
- Pre-mitigation requirement: install `systemd-coredump`, drop `LimitCORE=infinity` and `LimitCORESoft=infinity` in unit drop-in. Without backtraces, L1+ mitigation choices are guesswork.

## Mitigation options (do NOT apply yet)

Ranked by leverage, with explicit coverage estimates:

### L0a — Remove retry entirely (recommended first move)

Modify `src.data.connector` to NOT retry on 451. On 451 response: mark broker degraded, raise upward immediately, let `gap_repair` decide how to handle the gap (e.g., skip until next natural tick, or queue for next session).

- **Coverage**: All 12/12 Class A crashes (= 92% of all crashes). Eliminates the path entirely.
- **Implementation cost**: Small — delete retry loop, add early-return.
- **Risk**: Higher gap-repair failure rate. Need `gap_repair` to tolerate occasional skip without compounding.

### L0b — Shorten/debounce retry (alternative)

Reduce retry max from 3 to 1, add jitter, debounce gap_repair so consecutive 451s in <60s skip the entire path.

- **Coverage**: ~75% of Class A — saves storm crashes (6/12) and retry-2/retry-3 crashes (5/12 estimated). Does NOT save retry-1 crashes (~33% of independent crashes).
- **Implementation cost**: Small but more logic than L0a.
- **Risk**: Lower than L0a — preserves some retry capability.

### L1 — Wrap shioaji.login in try/except, mark broker degraded on any exit

Even L0a doesn't help if the C++ binding can crash after raising 451 (cleanup path). L1 wraps the call in `try/except (SystemExit, BaseException)` and on any failure, sets a `broker_degraded` flag, prevents re-login for N minutes.

- **Coverage**: Adds resilience on top of L0a/L0b for cleanup-path crashes.
- **Implementation cost**: Medium — touches connector, gap_repair, possibly health-check endpoint.

### L2 — Pin/upgrade shioaji

Check shioaji release notes between currently pinned version and latest for any session-login or memory-related fix.

- **Coverage**: Unknown until release notes consulted.
- **Implementation cost**: Low if no API breaking changes; high if API changed.
- **Risk**: Untested deployment of new version under production load.

### L3 — Subprocess isolation

Run shioaji client in a separate `multiprocessing.Process`; main API process talks to it via queue. SEGV in subprocess does not kill main service.

- **Coverage**: Belt-and-suspenders; protects main API even if all above fail.
- **Implementation cost**: High — requires reworking the broker abstraction.
- **Risk**: Adds IPC latency; may surface other concurrency bugs.

## Recommended mitigation sequence (for next session)

1. **Enable coredump capture** (systemd-coredump install + LimitCORE drop-in). High leverage, no code change, no service touch beyond a `daemon-reload`.
2. **Apply L0a**. Smallest diff with highest coverage. Single PR.
3. **Wait 24–48h** post-deploy. Recount NRestarts trend.
4. If crashes continue (likely from cleanup-path scenarios), apply **L1**.
5. Only after L0a+L1, evaluate L2 (shioaji upgrade) — backtraces from coredumps will inform whether this is even needed.
6. Defer L3 unless L0+L1+L2 still leaves residual crashes.

## Pre-flight checklist for mitigation session

Before any code change ships:
- [ ] deploy.sh fixed (uv venv issue) — confirmed in P1 of original handoff
- [ ] systemd-coredump installed + LimitCORE override applied
- [ ] `daemon-reload` performed (currently pending; reload now is safe since no code changes pending; verify next service restart loads new unit definition)
- [ ] coredump capture verified by manually `kill -SEGV` of a test process

## What this session did NOT determine

- **shioaji version** — Phase 5 deferred. Next session: read `.dist-info/METADATA` files (no Python execution), correlate with release notes via web.
- **OHLCV-mmap mechanism** (Class B, n=1) — single sample insufficient. May be coincidental concurrent gap_repair, not separate cause. Watch for recurrence post-mitigation.
- **Why exactly May 04 onset** — multiple candidate commits in burst; bisect impossible without rollback (which is risky).

## Open questions for user

1. May 03–04 commit burst: was it pushed in one batch or staged across hours/days? Reflog timestamps would clarify.
2. Was a Ray batch optimization run on May 04? (param_registry.db = 4GB / mtime May 4 18:05 anomaly remains unexplained — believed unrelated to SEGVs but unresolved.)
3. Is the e343158 commit's "non-blocking startup + delay market-data subscriber" workaround still considered active mitigation, or has it been further iterated since?
4. Should L0a's "remove retry" be the bias even though it increases gap-repair failure rate — i.e., is occasional missed bar acceptable to eliminate SEGV risk?

## Forensic artifacts

- `/tmp/crash_timeline.txt` on VPS (109 crash records, May 04–08)
- `/tmp/random_segv_sample.txt` on VPS (10 random SEGV timestamps used in this analysis)
- `/tmp/quant-engine-api.unit.snapshot.<ts>` on VPS (unit file at session-close)
- All raw journalctl windows captured in this session — re-runnable from agent transcript
