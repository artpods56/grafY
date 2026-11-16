import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  testMatch: "tiff.playwright.ts",
  workers: 1,
  retries: 0,
  timeout: 180_000,
  expect: { timeout: 30_000 },
  outputDir: "../../artifacts/e2e-tiff/test-results",
  use: {
    baseURL: process.env.E2E_STACK_ORIGIN,
    channel: process.env.TIFF_BROWSER_CHANNEL ?? "chrome",
    viewport: { width: 1440, height: 1000 },
    trace: "off",
    video: "off",
  },
});
