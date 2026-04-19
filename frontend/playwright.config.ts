import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  reporter: "list",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:5174",
    trace: "on-first-retry",
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    launchOptions: {
      args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
    },
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
