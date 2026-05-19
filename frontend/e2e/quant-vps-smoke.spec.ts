import { test, expect } from "@playwright/test";

const BASE_URL = (
  process.env.PLAYWRIGHT_BASE_URL ?? "https://quant-vps.taild2baa3.ts.net"
).replace(/\/$/, "");

test.use({ ignoreHTTPSErrors: true });

test("Tailscale production WebUI renders and core APIs respond", async ({
  page,
  request,
}) => {
  test.setTimeout(60_000);
  const health = await request.get(`${BASE_URL}/api/health`);
  expect(health.ok()).toBe(true);

  const meta = await request.get(`${BASE_URL}/api/meta`);
  expect(meta.ok()).toBe(true);
  const metaBody = (await meta.json()) as { git_commit?: string };
  expect(metaBody.git_commit).toMatch(/^[0-9a-f]{7,}$/);

  const response = await page.goto(`${BASE_URL}/`, {
    waitUntil: "domcontentloaded",
    timeout: 60_000,
  });
  expect(response?.ok()).toBe(true);
  await page.waitForSelector("#root", { timeout: 15_000 });
  await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});

  const renderSignal = await page.evaluate(() => {
    const root = document.querySelector("#root");
    return {
      rootChildren: root?.children.length ?? 0,
      textLength: document.body.innerText.trim().length,
      uiNodes: document.querySelectorAll("button,a,canvas,svg,table").length,
    };
  });
  expect(renderSignal.rootChildren).toBeGreaterThan(0);
  expect(renderSignal.textLength + renderSignal.uiNodes).toBeGreaterThan(20);

  const browserApiStatuses = await page.evaluate(async () => {
    const paths = ["/api/health", "/api/meta", "/api/sessions"];
    const statuses: Record<string, number> = {};
    for (const path of paths) {
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 8_000);
      try {
        const response = await fetch(path, { signal: controller.signal });
        statuses[path] = response.status;
      } finally {
        window.clearTimeout(timeout);
      }
    }
    return statuses;
  });

  expect(browserApiStatuses["/api/health"]).toBe(200);
  expect(browserApiStatuses["/api/meta"]).toBe(200);
  expect(browserApiStatuses["/api/sessions"]).toBe(200);
});
