import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  testMatch: "tiff.playwright.ts",
  workers: 1,
  retries: 0,
  timeout: 240_000,
  expect: { timeout: 45_000 },
  outputDir: "../../artifacts/e2e-tiff/test-results",
  use: {
    baseURL: process.env.E2E_STACK_ORIGIN,
    actionTimeout: 15_000,
    channel: process.env.TIFF_BROWSER_CHANNEL ?? "chrome",
    viewport: { width: 1440, height: 1000 },
    trace: "off",
    video: "off",
  },
});
