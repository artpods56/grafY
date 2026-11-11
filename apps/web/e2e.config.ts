import type { E2EConfig } from "e2e";
import { web } from "@e2e-dev/web";

const url = process.env.E2E_STACK_ORIGIN;
if (!url)
  throw new Error("Run npm run test:e2e to start the disposable stack.");

export default {
  targets: [
    {
      name: "chromium",
      engine: web({ viewport: { width: 1440, height: 900 } }),
      app: { url },
    },
  ],
  tests: "tests/core-flow.e2e.ts",
  workers: 1,
  retries: 0,
  timeout: 300_000,
  actionTimeout: 120_000,
  assertionTimeout: 30_000,
  // Recordings can include session cookies. Keep them off on CI and local runs.
  trace: "off",
  video: "off",
} satisfies E2EConfig;
