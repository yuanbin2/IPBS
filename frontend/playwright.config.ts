import { defineConfig, devices } from "@playwright/test";

const localBrowserChannel = process.env.E2E_BROWSER_CHANNEL;
const frontendPort = process.env.E2E_FRONTEND_PORT || "5173";
const frontendUrl = `http://127.0.0.1:${frontendPort}`;

export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.mjs",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 45_000,
  expect: { timeout: 8_000 },
  outputDir: "test-results",
  reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  use: {
    baseURL: frontendUrl,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{
    name: "chromium",
    use: {
      ...devices["Desktop Chrome"],
      ...(localBrowserChannel ? { channel: localBrowserChannel as "msedge" | "chrome" } : {}),
    },
  }],
});
