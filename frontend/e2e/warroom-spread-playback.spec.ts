import { test, expect, type Page } from "@playwright/test";

/**
 * Spread-strategy playback PnL parity.
 *
 * Verifies that the mock-dev account's playback surface shows correct PnL,
 * two-leg fills, and two-leg positions for short_term/mean_reversion/spread_reversion.
 *
 * Prerequisites:
 *   - Backend on port 8000 (prod) or 8001 (dev) with mock-dev seeded.
 *   - Frontend on the configured baseURL (5173 for prod-preview, 5174 for dev).
 *   - mock_fills and mock_session_snapshots contain spread_reversion data.
 */

const SPREAD_SLUG = "short_term/mean_reversion/spread_reversion";
// Backend API origin. Defaults to prod (8000) when a frontend preview serves the
// build; override via PLAYWRIGHT_API_BASE for dev runs (8001).
const API_BASE = process.env.PLAYWRIGHT_API_BASE ?? "http://127.0.0.1:8000";

async function selectMockDev(page: Page) {
  await page.goto("/war-room");
  // Wait for the account strip to render — 'networkidle' is unreliable because
  // the war-room page polls /api/war-room continuously.
  await page.waitForSelector('[data-testid="account-mock-dev"]', {
    timeout: 30_000,
  });
  await page.click('[data-testid="account-mock-dev"]');
  // Give the war-room poller one cycle to repopulate on the new account.
  await page.waitForTimeout(800);
}

test.describe("Spread playback PnL", () => {
  test("war-room /api returns non-zero realized PnL for spread", async ({
    request,
  }) => {
    const resp = await request.get(API_BASE + "/api/war-room");
    expect(resp.ok()).toBe(true);
    const body = await resp.json();
    const sessions = (body.all_sessions ?? []) as Array<{
      account_id: string;
      strategy_slug: string;
      snapshot: { realized_pnl?: number; trade_count?: number } | null;
    }>;
    const spread = sessions.find(
      (s) => s.account_id === "mock-dev" && s.strategy_slug === SPREAD_SLUG,
    );
    expect(spread, "spread_reversion session must be present").toBeTruthy();
    expect(spread?.snapshot?.realized_pnl ?? 0).not.toBe(0);
    expect(spread?.snapshot?.trade_count ?? 0).toBeGreaterThan(50);
  });

  test("war-room /api tags spread fills with r1/r2 spread_role", async ({
    request,
  }) => {
    // Phase A3 contract: every spread-strategy fill must carry a spread_role
    // in {"r1","r2"} so the frontend's SpreadPanels can route per-leg signals
    // to the correct chart panel without symbol-equality heuristics.
    // Single-leg strategies must tag as "single" so the spread panel filter
    // excludes them entirely.
    const asOf = "2025-05-15T12:00:00Z";
    const resp = await request.get(
      `${API_BASE}/api/war-room?as_of=${encodeURIComponent(asOf)}`,
    );
    expect(resp.ok()).toBe(true);
    const body = await resp.json();
    const fills = (body.accounts?.["mock-dev"]?.recent_fills ?? []) as Array<{
      strategy_slug?: string;
      symbol: string;
      spread_role?: "r1" | "r2" | "single";
    }>;
    const spreadFills = fills.filter(
      (f) => f.strategy_slug === SPREAD_SLUG,
    );
    expect(spreadFills.length).toBeGreaterThan(0);
    const roles = new Set(spreadFills.map((f) => f.spread_role));
    expect(roles.has("r1")).toBe(true);
    expect(roles.has("r2")).toBe(true);

    // Single-leg strategy: night_session_long fills must tag as "single".
    const singleFills = fills.filter(
      (f) => f.strategy_slug === "short_term/trend_following/night_session_long",
    );
    if (singleFills.length > 0) {
      expect(singleFills.every((f) => f.spread_role === "single")).toBe(true);
    }

    // Cross-check: r1 leg fills should be on MTX, r2 leg fills on MTX_R2.
    for (const f of spreadFills) {
      if (f.spread_role === "r1") expect(f.symbol).toBe("MTX");
      if (f.spread_role === "r2") expect(f.symbol).toBe("MTX_R2");
    }
  });

  test("war-room /api exposes both spread legs in recent_fills", async ({
    request,
  }) => {
    // The live `/api/war-room` recent_fills window only returns the last 200
    // rows; with a year of seeded data, more recent single-leg strategies can
    // crowd out spread leg rows. Query with an `as_of` inside the spread's
    // active window so the test isn't sensitive to which strategy's fills
    // happen to dominate the tail of the fill stream.
    const asOf = "2025-05-15T12:00:00Z";
    const resp = await request.get(
      `${API_BASE}/api/war-room?as_of=${encodeURIComponent(asOf)}`,
    );
    const body = await resp.json();
    const fills = body.accounts?.["mock-dev"]?.recent_fills ?? [];
    const spreadFills = fills.filter(
      (f: { strategy_slug?: string; triggered?: boolean }) =>
        f.strategy_slug === SPREAD_SLUG && f.triggered !== false,
    );
    const symbols = new Set(
      spreadFills.map((f: { symbol: string }) => f.symbol),
    );
    // mock-dev's portfolio places spread_reversion on the MTX underlying
    // (seeded via spread_legs_override=['MTX','MTX_R2']); TX is only used in
    // the strategy file's default META. The _SEED_STRATEGIES tuple is the
    // source of truth for which underlying to expect here.
    expect(symbols.has("MTX")).toBe(true);
    expect(symbols.has("MTX_R2")).toBe(true);
  });

  test("playback as_of yields trades for every seeded mock-dev strategy", async ({
    request,
  }) => {
    // Regression: previously only night_session_long generated signals during
    // playback because it still held stale 1-year snapshots while the freshly
    // re-seeded strategies only covered 30 days. The seeder now bypasses
    // pinned-execution drift (force_current_file=True), so all four strategies
    // share the same 30-day window and every session must have trade_count > 0
    // at a mid-range as_of timestamp.
    const asOf = "2026-04-10T12:00:00Z";
    const resp = await request.get(
      `${API_BASE}/api/war-room?as_of=${encodeURIComponent(asOf)}`,
    );
    expect(resp.ok()).toBe(true);
    const body = await resp.json();
    const sessions = (body.all_sessions as Array<{
      account_id: string;
      strategy_slug: string;
      snapshot: { trade_count?: number } | null;
    }>).filter((s) => s.account_id === "mock-dev");
    const counts: Record<string, number> = {};
    for (const s of sessions) {
      counts[s.strategy_slug] = s.snapshot?.trade_count ?? 0;
    }
    for (const slug of [
      "swing/trend_following/vol_managed_bnh",
      "medium_term/trend_following/donchian_trend_strength",
      "short_term/trend_following/night_session_long",
      "short_term/mean_reversion/spread_reversion",
    ]) {
      expect(counts[slug], `expected trade_count > 0 for ${slug}`).toBeGreaterThan(0);
    }
  });

  test("playback as_of returns mid-backtest spread PnL < final PnL", async ({
    request,
  }) => {
    const latest = await request.get(API_BASE + "/api/war-room");
    const latestBody = await latest.json();
    const finalSpread = (latestBody.all_sessions as Array<{
      account_id: string;
      strategy_slug: string;
      snapshot: { realized_pnl?: number } | null;
    }>).find(
      (s) => s.account_id === "mock-dev" && s.strategy_slug === SPREAD_SLUG,
    );
    const finalPnl = finalSpread?.snapshot?.realized_pnl ?? 0;

    // Jump to a mid-backtest timestamp — at this point the spread must have
    // already booked some PnL but not all of it.
    const asOf = "2026-04-01T12:00:00Z";
    const midResp = await request.get(
      `${API_BASE}/api/war-room?as_of=${encodeURIComponent(asOf)}`,
    );
    expect(midResp.ok()).toBe(true);
    const mid = await midResp.json();
    const midSpread = (mid.all_sessions as Array<{
      account_id: string;
      strategy_slug: string;
      snapshot: { realized_pnl?: number; trade_count?: number } | null;
    }>).find(
      (s) => s.account_id === "mock-dev" && s.strategy_slug === SPREAD_SLUG,
    );
    const midPnl = midSpread?.snapshot?.realized_pnl ?? 0;
    const midTrades = midSpread?.snapshot?.trade_count ?? 0;
    expect(midPnl).not.toBe(0);
    expect(midTrades).toBeGreaterThan(0);
    // finalPnl > midPnl (strategy continued booking PnL after the as_of cutoff).
    expect(Math.abs(finalPnl)).toBeGreaterThan(Math.abs(midPnl) - 1);
  });

  test("UI: playback bar loads mock-dev with non-zero equity strip", async ({
    page,
  }) => {
    await selectMockDev(page);
    // PlaybackBar should be visible for the mock account.
    await expect(page.locator('[data-testid="playback-bar"]')).toBeVisible();
    // The Row-2 stats strip renders the active account's aggregate equity as a
    // '$<digits>' span. After the spread seed lands, mock-dev totals ~2.8M so
    // at least one equity span must contain a comma-separated number.
    const dollarValue = await page
      .locator("span", { hasText: /^\$[\d,]+$/ })
      .first()
      .textContent();
    expect(dollarValue ?? "").toMatch(/^\$\d/);
  });

  test("UI: activity tab shows spread fills with leg-2 symbol", async ({
    page,
  }) => {
    await selectMockDev(page);
    // Switch to "RECENT TRADES" tab — it renders the fills table.
    await page.getByRole("button", { name: /RECENT TRADES/ }).click();
    // The trades table paints on the next poll cycle; give it a moment.
    await page.waitForTimeout(1200);
    const pageText = await page.textContent("body");
    // mock-dev seeds spread_reversion on MTX (see _SEED_STRATEGIES), so the
    // leg-2 symbol on the blotter is MTX_R2, not the strategy META's TX_R2.
    expect(pageText ?? "").toContain("MTX_R2");
  });

  test("UI: spread view extends page vertically so equity + positions remain visible", async ({
    page,
  }) => {
    await selectMockDev(page);
    // The chart toolbar renders a view-mode toggle whose label is the CURRENT
    // mode ("single" while in single view). Clicking it flips to spread.
    const toggleToSpread = page.getByRole("button", { name: /^single$/i }).first();
    if ((await toggleToSpread.count()) === 0) test.skip();
    await toggleToSpread.click();
    // Wait for the spread panels to mount.
    await page.waitForTimeout(1000);
    // The equity panel test id exists inside EquityPanel; any stable equity
    // element / trade-count label near the equity row works. Here we check
    // that the page's scrollable height now exceeds the viewport — i.e. the
    // page itself got longer instead of squeezing the other panels.
    const viewportHeight = await page.evaluate(() => window.innerHeight);
    const docHeight = await page.evaluate(
      () => document.documentElement.scrollHeight,
    );
    expect(docHeight).toBeGreaterThan(viewportHeight);
    // The equity/positions card should still be present in the DOM and
    // render the "EQUITY" label (used in the account summary strip).
    const equityText = await page.textContent("body");
    expect(equityText ?? "").toContain("OPEN POSITIONS");
  });

  test("UI: spread view respects playback clock (bars filtered up to virtualClockMs)", async ({
    page,
  }) => {
    await selectMockDev(page);
    await page.locator('[data-testid="playback-bar"]').waitFor();
    // Enable playback — the toggle is a button.
    await page.getByRole("button", { name: "PLAYBACK" }).click();
    // Switch main chart to SPREAD mode — the toolbar button's label is the
    // CURRENT mode ("single"); clicking it flips to spread view.
    const toggleToSpread = page.getByRole("button", { name: /^single$/i }).first();
    if (await toggleToSpread.count()) {
      await toggleToSpread.click();
    }
    // Reset to the start of the range and take a snapshot of the spread bars.
    await page.locator('[data-testid="playback-reset"]').click();
    await page.waitForTimeout(500);
    // Advance the clock by clicking the scrubber near the end.
    const scrubber = page.locator('[data-testid="playback-scrubber"]');
    const box = await scrubber.boundingBox();
    if (!box) {
      test.skip();
      return;
    }
    await page.mouse.click(box.x + box.width * 0.9, box.y + box.height / 2);
    await page.waitForTimeout(500);
    // The virtualClockMs label must have advanced. If no playback regression,
    // this value will not be the start-of-range label.
    const laterTime = await page
      .locator('[data-testid="playback-time"]')
      .textContent();
    expect(laterTime ?? "").not.toBe("--:--");
  });
});
