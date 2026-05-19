# TXO Trading-Terminal Verification Checklist

**Branch under test:** `feature/txo-iv-screener`
**Worktree:** `/home/willy/invest/quant-engine-txo-screener`
**Goal:** confirm the 5-pack upgrade (Pack 0–5 in `.claude/plans/go-to-the-feat-compressed-puffin.md`) is correct end-to-end before the human commits, merges, or trades.

The instructions assume the runner has shell access to the worktree, can run pytest/ruff/tsc, and can drive a browser (Playwright or manual). Where a step requires a live broker, do the paper-mode form first.

---

## 0. Boot & sanity (do these first; everything else depends on them)

| # | Step | Expected | If fails |
| - | ---- | -------- | -------- |
| 0.1 | `cd /home/willy/invest/quant-engine-txo-screener && git status -sb` | branch is `feature/txo-iv-screener`; the working tree contains the renamed doc plus modified screener/api/options/sinopac/options_crawl files plus the new `frontend/src/pages/options/extras.tsx` and the new analytics modules (`scenarios.py`, `portfolio.py`, `strategy_recognizer.py`) and their tests | wrong worktree — bail |
| 0.2 | Backend boot: `NODE_BIN=/home/willy/.nvm/versions/node/v24.13.0/bin/node ./scripts/run-dev.sh > /tmp/dev.log 2>&1 &` then `sleep 15 && tail -30 /tmp/dev.log` | sees `VITE v8.0.1 ready`, listening on `:5174` and `:8001`. No node-version error. | If node error: confirm v24+ on PATH or set `NODE_BIN` to a v22.12+ binary. |
| 0.3 | `curl -s -m 3 -w "\n%{http_code}\n" http://localhost:8001/api/options/screener \| tail -3` | HTTP 200, JSON includes top-level `as_of_freshness_seconds`, `rv_estimator`, `coverage_warning`, and per-strike `gamma`, `theta`, `vega`, `bid_ask_spread_pct`, `iv_smile_resid` keys | If 500: `tail -100 data/logs/backend.log` and look for AttributeError or import errors. |
| 0.4 | `curl -s http://localhost:8001/api/options/positions` and `curl -s http://localhost:8001/api/options/orders` and `curl -s http://localhost:8001/api/options/portfolio-greeks` | Each returns 200 (typically empty `[]` or `{net_delta:0,...}` when no broker connected) | If 500 with `AttributeError: type object 'GatewayRegistry' has no attribute 'get_instance'` — the registry-helper patch in `src/api/routes/options.py` (`_registry`, `_iter_connected_gateways`, `_get_gateway`) is missing. |

---

## 1. Pack 0 — doc relocation (1 minute)

- [ ] `git ls-files docs/analysis/ | grep execution_bug` returns `docs/analysis/execution_bug_fix_live_runner.md` and **not** `…_options.md`.
- [ ] `git log --diff-filter=R -1 --stat -- docs/analysis/` shows the rename was done with `git mv` so history is preserved.

---

## 2. Pack 1 — silent-bug fixes

### 2A. Backend

- [ ] `cd /home/willy/invest/quant-engine-txo-screener && .venv/bin/pytest tests/options/test_iv_screener_gates.py -k 'vrp_nonzero or dedup_one_per_date' -x` — both new tests pass.
- [ ] In the screener payload from step 0.3, `as_of_freshness_seconds` is a non-negative integer; `rv_estimator` is `"parkinson"` or `"close_to_close"`; `coverage_warning` is either `null` or the string `"open_interest_unavailable"`.
- [ ] Run `git show feature/txo-iv-screener:src/data/options_crawl.py | grep -A2 "open_interest=None"` and confirm the explanatory comment is present (no silent None).

### 2B. Frontend (browser)

Open `http://localhost:5174/#/options`. Click the "Options" tab if it isn't already active.

- [ ] Header shows the **freshness chip** between the `?` help button and the account selector. Color follows snapshot age:
  - green "FRESH · Ns" when ≤ 60 s
  - amber "Nm old" when ≤ 5 min
  - red "Nm old · STALE" when older
  - The chip's `title` attribute reads "Snapshot freshness — click Fetch Live to refresh".
- [ ] If the screener payload reports `coverage_warning === "open_interest_unavailable"`, the page shows an amber banner just under the regime banner: `⚠ Open Interest unavailable — liquidity gating uses bid-ask spread + volume only`.

---

## 3. Pack 2 — decision panel

### 3A. Backend

- [ ] `.venv/bin/pytest tests/options/test_greeks_smile.py -x` — 10/10 pass.
- [ ] Pull a single strike from the screener and verify:
  - `gamma` peaks at the ATM strike of each expiry slice.
  - `theta` is negative for both ATM call and ATM put.
  - `vega` is positive.
  - `bid_ask_spread_pct` is non-negative or null when bid/ask is missing.
  - `iv_smile_resid` is signed, near zero for strikes on the smile, larger in magnitude for outliers.

### 3B. Frontend buttons (browser)

- [ ] Click the **Greeks** filter chip. Three extra columns (`Γ Θ/d ν`) appear on **both** the call and put side of every chain table. The values populate (gamma in scientific notation, theta divided by 365, vega rounded). Click again — columns disappear.
- [ ] Filter chips above each chain table:
  - **Expiry**: "All" plus the 4 nearest expiries are clickable. Selecting one collapses the page to a single chain.
  - **Side**: "Both" / "Calls" / "Puts" — selecting "Calls" leaves Put cells as `—` and vice-versa.
  - **|Δ|**: "Any" / "≤0.20" / "0.20-0.40" / "0.40-0.60" / "≥0.60" — picking a band visibly removes rows whose |delta| is outside.
  - **Min vol**: typing `100` removes rows whose volume is below 100 on both sides.
- [ ] The "Best Opportunities" strip appears above the Builder pane when at least one strike has |iv_smile_resid| > 0.01 with adequate liquidity (spread ≤ 10 %, volume > 0). Each card shows strike, expiry, signal, bid/ask/vol. Clicking a card scrolls the matching chain row into focus and outlines the row in gold for ~2.5 s. (Empty stub if no candidates pass the liquidity gate — that is correct, not a bug.)
- [ ] Liquidity badge inside each Vol cell: ✓ green when spread ≤ 10 % and vol ≥ 50; ⚠ amber when 10 < spread ≤ 25 or vol < 50; ✕ red when spread > 25 % or vol == 0; `—` when bid/ask is missing.
- [ ] IV color-coding: when `iv_smile_resid` is non-null, the IV cell is colored relative to the fitted smile (green = cheap, red = rich). When the residual is null it falls back to the original "vs ATM IV" coloring.

---

## 4. Pack 3 — order ticket: scenarios + sizing + portfolio impact

### 4A. Backend

- [ ] `.venv/bin/pytest src/analytics/options/tests/test_scenarios.py -x` — 5/5 pass.
- [ ] `curl -s -X POST http://localhost:8001/api/options/scenarios -H 'content-type: application/json' -d '{"legs":[{"option_type":"C","strike":42000,"side":"buy","qty":1,"price":200,"multiplier":50}],"S_now":42000,"dte_days":30,"sigma":0.2}' | jq .` returns a JSON with `breakeven`, `max_loss`, `max_profit`, `premium`, `margin_estimate`, `pnl_curve` (5 points), `dte_days`. For this leg `breakeven` should be ≈ 42 200 (within one grid step), `premium` negative (paid), `max_profit` is the string `"inf"`.
- [ ] `curl -s http://localhost:8001/api/options/portfolio-greeks` returns `{net_delta, net_gamma, net_theta, net_vega, n_legs, missing_codes}` — zeros and empty list are normal when no positions are open.

### 4B. Frontend buttons (order dialog)

Click any non-empty Bid or Ask cell in the chain (without holding Shift). The order dialog opens.

- [ ] Header shows `BUY` or `SELL` plus strike+type, with the appropriate green/red border.
- [ ] **Scenario panel** appears between contract info and price guidance:
  - "Premium" line is signed (sell legs positive, buy legs negative).
  - "Max loss" / "Max profit" / "Breakeven" / "Margin est." rows are populated.
  - The 5-bucket P&L grid shows S = spot × {0.95, 0.98, 1.00, 1.02, 1.05} with PnL color-coded.
- [ ] **Portfolio impact** panel renders next: "Δ Delta", "Γ Gamma", "Θ Theta (annual)", "ν Vega" — the "before" column is the current book, the "after" column is `→ x.xx` and matches `before + leg contribution`.
- [ ] Sizing preset buttons `1 / 5 / 10 / 25` switch the qty input. The active preset highlights blue.
- [ ] Fill-probability chip on the right of the sizing row: green/amber/red depending on whether the limit price leans toward the aggressive side of the spread.
- [ ] Tick +/- buttons on the price input still work (Pack 1 behavior preserved); price step matches `txoTickSize(price)`.
- [ ] "Outside bid-ask range" warning appears when typing a price below bid or above ask (existing behavior, regression check).
- [ ] Clicking the main side-colored button switches it to a `Cancel | CONFIRM BUY/SELL` row. Cancel returns to step 1; the CONFIRM button is only enabled when an account is selected. (DO NOT click CONFIRM on production — see paper-mode flow below.)

---

## 5. Pack 4 — trade lifecycle: working orders + mark-to-market + auto-refresh

### 5A. Backend

- [ ] `.venv/bin/pytest tests/options/test_orders_routes.py -x` — 18/18 pass (this file is currently untracked in git; verify it exists at `tests/options/test_orders_routes.py`).
- [ ] `curl -s http://localhost:8001/api/options/orders` returns 200 (empty array when no broker connected; populated list when paper-mode is on).
- [ ] `curl -s -X POST 'http://localhost:8001/api/options/orders/zzz/cancel?gateway_id=does-not-exist'` returns 404.
- [ ] `curl -s -X PATCH 'http://localhost:8001/api/options/orders/zzz?gateway_id=does-not-exist' -H 'content-type: application/json' -d '{}'` returns 400 ("Provide at least one of price or quantity").
- [ ] `/api/options/positions` payload: each position has `mark_price`, `unrealized_pnl`, `multiplier` keys (null mark allowed when no recent quote, but the keys must be present).

### 5B. Frontend

- [ ] **Working Orders panel** appears between the Builder pane and the Positions panel **only when** `/api/options/orders` returns at least one row. With a paper account: place a 1-lot deeply OTM limit (≥ 5 strikes away from spot). The row should appear within one auto-refresh cycle (15 s) showing `order_id`, contract, side, qty (filled), price, status, plus `Amend` and `Cancel` buttons.
- [ ] Click **Amend**: the price cell becomes an editable input, plus `Save / ×`. Type a new price 1 tick away → `Save` → row updates with new price. Status moves to `Submitted` or whatever the broker returns.
- [ ] Click **Cancel**: the row disappears within one refresh cycle.
- [ ] **Positions panel**: any open position (paper) shows `Mark`, `Unrealized PnL` (color-coded green/red), and a `Close` button. Click `Close` → the order dialog opens pre-filled with the **opposite** side (e.g. an open Buy position opens a Sell ticket). Verify the strike, type, expiry, and current mark price are pre-filled.
- [ ] **Auto-refresh toggle** in the legend row (next to "Click Bid/Ask to trade · Shift+Click to add to builder"). Default is checked. Uncheck → polling stops; the freshness chip will continue to age until you click Reload manually. Re-check → the chip resets to FRESH (≤60 s) on the next poll.

### 5C. Live caveats

- shioaji's `cancel_order` and `update_order` are reached through `getattr` introspection inside `SinopacGateway`. Verifying their existence requires a live or paper-mode shioaji session. Treat any 500 with the text "shioaji instance has no cancel_order/update_order method" as a paper-mode-only validation fail, not an integration test fail.

---

## 6. Pack 5 — multi-leg builder

### 6A. Backend

- [ ] `.venv/bin/pytest tests/options/test_strategy_recognizer.py -x` — 15/15 pass.
- [ ] `curl -s -X POST http://localhost:8001/api/options/orders/combo -H 'content-type: application/json' -d '{"account_id":"none","legs":[{"contract_code":"TXO39500E6","side":"buy","quantity":1,"price":2400}],"dry_run":true}' | jq .` returns `{status:"dry_run", combo:{name, confidence, notes}, legs:[…]}` — no broker required for dry-run.
- [ ] Repeat with a 2-leg vertical (long lower-strike call, short higher-strike call, same expiry) and confirm `combo.name` looks like `Vertical (Bull Call)` with confidence 1.0.
- [ ] Repeat with 5 legs and confirm 400 (too many legs).

### 6B. Frontend

- [ ] **Builder pane** is visible above the Working Orders panel. With no legs, it shows the dashed "Shift+Click any Bid or Ask to add a leg" hint.
- [ ] Hold Shift and click a **Bid** cell on a call. A leg chip appears in the Builder showing `−1 <strike>C <expiry> @ <price>`, the side colored red (sell). Repeat with a different strike call's **Ask** cell — Shift-click — a leg with `+1 <strike>C` and green tint appears.
- [ ] The Builder header now reads `Builder · Vertical (Bull Call)` (or whatever classifier returned for the chosen pair).
- [ ] The grid below the chips shows aggregate `Premium / Max loss / Max profit / Breakeven` for the combo. Numbers should match a hand calculation for a simple vertical: `max_loss = -(width − credit) × multiplier` etc.
- [ ] The leg chip's `×` button removes the leg. The "Clear all" button at the top-right empties the Builder.
- [ ] With a paper account selected, click `Place combo (N legs, sequenced)`. The toast should read `Combo placed (sequenced): <name>` on success, or `Combo placed (sequenced): <name> · failed at leg K: <error>` on partial failure. The Builder clears on success.
- [ ] **Atomic vs sequenced label**: the toast must include `(sequenced)` because shioaji has no native combo endpoint as of the current SDK. If a future SDK adds one, the label flips to `(atomic)` automatically — this is W5's runtime probe.

---

## 7. Cross-cutting

- [ ] Re-run the full suite: `.venv/bin/pytest tests/options/ src/analytics/options/tests/ -x` — 62+ tests, 0 failures, 0 errors.
- [ ] `cd frontend && npx tsc --noEmit` — exit 0, zero output.
- [ ] `ruff check src/analytics/options/ src/api/routes/options.py src/data/options_crawl.py src/broker_gateway/sinopac.py tests/options/` — should not introduce new lint findings beyond the pre-existing ones (16 pre-existing in `metrics.py` from before this PR).
- [ ] Browser DevTools → Network panel: with auto-refresh on and no broker connected, the page should send a small periodic burst every 15 s (`/screener`, `/positions`, `/orders`, `/portfolio-greeks`). All four return 200; **nothing 500**.

---

## 8. Known limitations (do not file as bugs)

1. **`vrp` is `0.0` until the OHLCV table has TX data.** Pack 1 fixed the wiring; if the local DB doesn't have TX 1m bars, RV stays NaN → VRP rounds to 0. Confirm by inserting a sample row and re-curling `/screener`.
2. **`Open Interest` is always null.** Shioaji's `api.snapshots()` does not expose OI for options. The screener emits `coverage_warning="open_interest_unavailable"` so the UI surfaces this honestly. Real OI requires a TAIFEX settlement-file pipeline (out of scope for this PR — followup).
3. **Combo orders are always sequenced.** As of the current shioaji SDK, no native combo endpoint exists. The gateway probes for `place_combo_order`/`place_strategy_order` at runtime and falls through to leg-by-leg `place_order` with honest partial-fill reporting (`failed_at`, `error`).
4. **Margin estimate is indicative.** TAIFEX SPAN-style margin is broker-derived; the screener uses `max(min_margin, premium + 10 % × spot × multiplier)` per sell leg. Treat as ballpark, not as a sizing input.
5. **W4's `tests/options/test_orders_routes.py` is currently untracked.** Add it to `git add` before committing this PR.

---

## 9. Success criteria for sign-off

- All boxes above are checked.
- No console errors on the Options page during a 60-second idle period (warnings are OK).
- Paper-account roundtrip verified for at least one cancel and one amend (Pack 4) and one 2-leg dry-run combo (Pack 5).
- Risk Auditor signs off that Pack 0 (rename) and Pack 1 (data-quality fixes) made it into the merge commit.

If any check fails, link to the relevant section in `.claude/plans/go-to-the-feat-compressed-puffin.md` and tag the responsible packet (Pack 1–5) for follow-up.
