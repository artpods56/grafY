import { defineConfig } from "@playwright/test";
import { join, resolve } from "node:path";

/**
 * The real-backend browser suite: a real FastAPI process, the repository's own
 * OIDC provider, and the Next dev server that proxies `/api` for the browser. No
 * `page.route` fixture answers anything, so this is the suite that proves the two
 * applications still speak to each other.
 *
 * `e2e/` keeps its own mocked-API config and its own output directories, so
 * `npx playwright test` never starts a backend and this config never reuses one.
 *
 * The environment comes from `scripts/real-smoke.mjs` (`npm run test:e2e:real`),
 * which owns the disposable runtime root, database, ports, keys, and Keycloak, and
 * passes the coordinates here. Starting the two services is left to Playwright's
 * own `webServer`: it knows their pids, stops them on every exit path, and prints
 * their output in the run's own log. Nothing in this file kills a process it did
 * not start.
 */

const WEB_ROOT = resolve(__dirname);

const fromLauncher = (name: string): string => {
  const value = process.env[name];
  if (!value) {
    throw new Error(
      `${name} is not set. These specs need the disposable stack that the launcher builds: npm run test:e2e:real`,
    );
  }
  return value;
};

const origin = fromLauncher("REAL_SMOKE_ORIGIN");
const apiOrigin = fromLauncher("REAL_SMOKE_API_ORIGIN");
const python = fromLauncher("REAL_SMOKE_PYTHON");
const runtimeRoot = fromLauncher("REAL_SMOKE_RUNTIME_ROOT");
const nextBin = join(WEB_ROOT, "node_modules", "next", "dist", "bin", "next");

/**
 * Playwright hands each `webServer` command to a shell, so a path has to survive that
 * shell: the runtime root is the OS temp directory and a checkout can sit under a
 * path with a space or a quote in it. Single quotes keep everything between them
 * literal, so a literal quote has to step outside and back in.
 */
export const shellQuote = (value: string): string =>
  `'${value.replace(/'/g, "'\\''")}'`;

export default defineConfig({
  testDir: "./e2e-real",
  outputDir: "../../output/playwright-real/test-results",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  // One API process owns the workspace, database, and ports for this run.
  workers: 1,
  retries: 0,
  // The dev server compiles each route on first sight, so a cold click can wait on
  // a webpack build. These are the suite's ceilings, not the mocked suite's.
  timeout: 300_000,
  expect: { timeout: 30_000 },
  reporter: [
    ["line"],
    [
      "html",
      { open: "never", outputFolder: "../../output/playwright-real/report" },
    ],
  ],
  webServer: [
    {
      // The API runs from the run's runtime root, which is where its workspace,
      // SQLite database, and single-owner lock are. Product configuration is the
      // launcher's to write and this process's to inherit; Playwright adds it to
      // the inherited environment, which is why the launcher sanitizes first.
      command: `${shellQuote(python)} -m uvicorn grafy_api.main:app --host 127.0.0.1 --port ${new URL(apiOrigin).port}`,
      cwd: runtimeRoot,
      url: `${apiOrigin}/ready`,
      timeout: 120_000,
      // Never adopt a server this run did not start: a `just api` belongs to
      // another checkout and would be the wrong database.
      reuseExistingServer: false,
    },
    {
      command: `${shellQuote(process.execPath)} ${shellQuote(nextBin)} dev --webpack --hostname 127.0.0.1 --port ${new URL(origin).port}`,
      cwd: WEB_ROOT,
      // Set, not merely absent: Next fills unset variables from `apps/web/.env.local`,
      // and that flag would give this dev server a stand-in session with no login.
      // A real process environment value wins over the file, so the login this
      // suite exists to prove cannot be switched off from a developer's checkout.
      env: {
        GRAFY_API_UPSTREAM: apiOrigin,
        NEXT_TELEMETRY_DISABLED: "1",
        NEXT_PUBLIC_GRAFY_DEV_SESSION: "",
      },
      // The first request to a route compiles it, which is slower than booting.
      url: `${origin}/graphs`,
      timeout: 240_000,
      // Next allows one dev server per directory; adopting one that is already
      // running would mean testing another worktree's source.
      reuseExistingServer: false,
    },
  ],
  use: {
    // A trace records request headers, so it would carry this run's Grafy session
    // cookie into `output/playwright-real/`, which CI uploads on failure. In CI the
    // failure evidence is the screenshot, the video, and the DOM snapshot in
    // error-context.md; reproduce with REAL_SMOKE_KEEP=1 for a trace and the
    // provider container's own log, both of which stay on the developer's disk.
    trace: process.env.CI ? "off" : "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "real-desktop",
      use: {
        browserName: "chromium",
        viewport: { width: 1440, height: 900 },
      },
    },
  ],
});
