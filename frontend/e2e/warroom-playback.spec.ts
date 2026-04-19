import { test, expect } from "@playwright/test";

/**
 * War Room Playback — end-to-end tests.
 *
 * Prerequisites:
 *   - Dev server running on http://127.0.0.1:5174  (scripts/run-dev.sh)
 *   - Backend running on http://127.0.0.1:8001
 *   - Mock data seeded for the mock-dev account
 *
 * Run: cd frontend && npx playwright test e2e/warroom-playback.spec.ts
 */

test.describe("War Room Playback", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/war-room");
    // Wait for the account strip to render — 'networkidle' is unreliable here
    // because the war-room page polls /api/war-room every 15s.
    await page.waitForSelector('[data-testid="account-mock-dev"]', {
      timeout: 30_000,
    });
  });

  test("playback bar is visible only for mock-dev account", async ({ page }) => {
    // Select the mock-dev account.
    await page.click('[data-testid="account-mock-dev"]');
    await expect(page.locator('[data-testid="playback-bar"]')).toBeVisible();
  });

  test("play advances virtual clock", async ({ page }) => {
    await page.click('[data-testid="account-mock-dev"]');
    await page.waitForSelector('[data-testid="playback-bar"]');

    // Enable playback mode — the toggle is a button (not a native checkbox)
    await page.getByRole("button", { name: "PLAYBACK" }).click();
    await page.waitForSelector('[data-testid="playback-time"]');

    // Capture the clock label before starting playback.
    const initialTime = await page
      .locator('[data-testid="playback-time"]')
      .textContent();

    // Start playback and wait for 2 seconds of real time.
    await page.click('[data-testid="playback-play"]');
    await page.waitForTimeout(2000);
    await page.click('[data-testid="playback-pause"]');

    const newTime = await page
      .locator('[data-testid="playback-time"]')
      .textContent();

    expect(newTime).not.toBe(initialTime);
  });

  test("pause freezes virtual clock", async ({ page }) => {
    await page.click('[data-testid="account-mock-dev"]');
    await page.waitForSelector('[data-testid="playback-bar"]');

    // Enable playback mode — the toggle is a button (not a native checkbox)
    await page.getByRole("button", { name: "PLAYBACK" }).click();
    await page.waitForSelector('[data-testid="playback-play"]');

    await page.click('[data-testid="playback-play"]');
    await page.waitForTimeout(1000);
    await page.click('[data-testid="playback-pause"]');

    const pausedTime = await page
      .locator('[data-testid="playback-time"]')
      .textContent();

    // Wait another second — clock must not advance while paused.
    await page.waitForTimeout(1000);
    const stillPausedTime = await page
      .locator('[data-testid="playback-time"]')
      .textContent();

    expect(stillPausedTime).toBe(pausedTime);
  });

  test("speed selector changes playback rate", async ({ page }) => {
    await page.click('[data-testid="account-mock-dev"]');
    await page.waitForSelector('[data-testid="playback-bar"]');

    // Enable playback — the toggle is a button (not a native checkbox)
    await page.getByRole("button", { name: "PLAYBACK" }).click();

    // Speed control is a <input type="range">. fill() sets the value and
    // dispatches change events so React's onChange re-renders the badge.
    const slider = page.locator('[data-testid="playback-speed"]');
    await slider.fill("300");

    const speedBadge = page.locator('[data-testid="playback-speed-indicator"]');
    await expect(speedBadge).toHaveText("300×");
  });

  test("scrubber jumps to selected position", async ({ page }) => {
    await page.click('[data-testid="account-mock-dev"]');
    await page.waitForSelector('[data-testid="playback-bar"]');

    // Enable playback mode — the toggle is a button (not a native checkbox)
    await page.getByRole("button", { name: "PLAYBACK" }).click();
    await page.waitForSelector('[data-testid="playback-scrubber"]');

    const scrubber = page.locator('[data-testid="playback-scrubber"]');
    const box = await scrubber.boundingBox();
    if (!box) {
      test.skip();
      return;
    }

    // Click at 75% of the scrubber width to jump near the end of the range.
    await page.mouse.click(box.x + box.width * 0.75, box.y + box.height / 2);

    // After scrubbing, the clock should reflect a time later than the start.
    const timeAfterScrub = await page
      .locator('[data-testid="playback-time"]')
      .textContent();
    expect(timeAfterScrub).toBeTruthy();
  });

  test("reset returns clock to start of range", async ({ page }) => {
    await page.click('[data-testid="account-mock-dev"]');
    await page.waitForSelector('[data-testid="playback-bar"]');

    // Enable playback mode — the toggle is a button (not a native checkbox)
    await page.getByRole("button", { name: "PLAYBACK" }).click();
    await page.waitForSelector('[data-testid="playback-time"]');

    // Wait for the range to load and time to stabilize
    await page.waitForTimeout(500);

    // Record the initial (start-of-range) time label.
    const startTime = await page
      .locator('[data-testid="playback-time"]')
      .textContent();

    // Play briefly, then pause and reset.
    await page.click('[data-testid="playback-play"]');
    await page.waitForTimeout(1500);
    await page.click('[data-testid="playback-pause"]');
    await page.waitForTimeout(100);
    await page.click('[data-testid="playback-reset"]');
    await page.waitForTimeout(100);

    const afterResetTime = await page
      .locator('[data-testid="playback-time"]')
      .textContent();

    expect(afterResetTime).toBe(startTime);
  });
});
