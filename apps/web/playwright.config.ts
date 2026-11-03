import { defineConfig } from "@playwright/test";

const port = process.env.GRAFY_E2E_PORT ?? "3000";
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "./e2e",
  outputDir: "../../output/playwright/test-results",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : 2,
  reporter: [
    ["line"],
    [
      "html",
      {
        open: "never",
        outputFolder: "../../output/playwright/report",
      },
    ],
  ],
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "desktop-chromium",
      use: {
        browserName: "chromium",
        viewport: { width: 1440, height: 900 },
      },
    },
    {
      name: "mobile-chromium",
      use: {
        browserName: "chromium",
        viewport: { width: 390, height: 844 },
        deviceScaleFactor: 3,
        hasTouch: true,
        isMobile: true,
      },
    },
    {
      name: "tablet-chromium",
      use: {
        browserName: "chromium",
        viewport: { width: 834, height: 1194 },
        deviceScaleFactor: 2,
        hasTouch: true,
        isMobile: true,
      },
    },
  ],
  webServer: {
    command: `npm run dev -- --hostname 127.0.0.1 --port ${port}`,
    // Readiness has to be a route that answers 2xx: the Workbench moved to a
    // Project address, and probing the retired /graphs segment would leave
    // Playwright waiting on a 404 until the timeout, for a server that is fine.
    url: `${baseURL}/workspaces/mobile-test/projects/new`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
