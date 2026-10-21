import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

/**
 * The two `webServer` entries are the only place this suite hands a path to a shell,
 * and both come from outside the checkout: the interpreter is the repository's `.venv`
 * and the runtime root is the OS temp directory. A checkout under a path with a space,
 * a quote, or a `$` in it has to start the same server, not a mangled one.
 */

// A path no shell can swallow quietly: a quote that has to be escaped and two forms
// of expansion. The config reads its coordinates at import time, so these are in
// place before it is loaded below.
const NASTY_PATH = `/tmp/grafy's $HOME \`whoami\``;
process.env.REAL_SMOKE_ORIGIN = "http://127.0.0.1:43101";
process.env.REAL_SMOKE_API_ORIGIN = "http://127.0.0.1:43102";
process.env.REAL_SMOKE_PYTHON = NASTY_PATH;
process.env.REAL_SMOKE_RUNTIME_ROOT = NASTY_PATH;

const nextBin = `${fileURLToPath(new URL(".", import.meta.url))}node_modules/next/dist/bin/next`;

/**
 * How a shell splits a command line: `printf` gets the words the shell would hand the
 * program, and nothing is executed.
 */
const shellArgv = (command: string): string[] =>
  execFileSync("/bin/sh", ["-c", `printf '%s\\n' ${command}`])
    .toString()
    .trimEnd()
    .split("\n");

const serverCommands = async (): Promise<string[]> => {
  const { default: config } = await import("./playwright.real.config");
  const { webServer } = config;
  // This config declares two plain entries; Playwright's own type also allows
  // functions, so the entries with a command are the ones asked about.
  return (Array.isArray(webServer) ? webServer : [webServer])
    .filter(
      (server): server is { command: string } =>
        typeof server === "object" && server !== null && "command" in server,
    )
    .map((server) => server.command);
};

describe("the real-backend web servers", () => {
  it("reaches the shell as the paths this run was given", async () => {
    const servers = (await serverCommands()).map(shellArgv);
    const [api, web] = servers;
    if (!api || !web) {
      throw new Error(`the config defined ${servers.length} web servers`);
    }

    expect(api).toEqual([
      NASTY_PATH,
      "-m",
      "uvicorn",
      "grafy_api.main:app",
      "--host",
      "127.0.0.1",
      "--port",
      "43102",
    ]);
    expect(web[0]).toBe(process.execPath);
    expect(web[1]).toBe(nextBin);
    expect(web.at(-1)).toBe("43101");
  });
});
