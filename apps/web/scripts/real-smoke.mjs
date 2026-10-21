#!/usr/bin/env node
/**
 * Entry point for `npm run test:e2e:real`: it builds the disposable environment
 * the real-backend browser smoke test needs, hands it to Playwright, and removes
 * it again.
 *
 * The environment is three free ports from the operating system, so the suite
 * neither expects nor competes with `just web` (3000) or `just api` (8000); a
 * temporary runtime root holding a fresh SQLite database, which is also the API's
 * cwd and therefore where its workspace and its single-owner lock live, so the
 * repository's `.env` and development workspace are never read; and a disposable
 * Keycloak (infra/docker/compose.keycloak.smoke.yaml) under a project name of this
 * run's own, configured by posting a realm derived from the repository's committed
 * one so its client accepts this run's callback instead of the fixed `:3000`.
 * Playwright starts the API and the dev server as its own `webServer` children.
 *
 * Teardown is this process's and happens once: it signals the Playwright run, then
 * either removes the container this run named and the runtime root, or keeps both
 * when `REAL_SMOKE_KEEP=1` asked to inspect them. Nothing here looks a process up
 * by name.
 *
 * `REAL_SMOKE_*` variables carry the run's coordinates to the Playwright config
 * and the spec. They are deliberately not `GRAFY_*`: every `GRAFY_*` variable is
 * product configuration, is generated here, and is dropped from the inherited
 * environment so that neither `.env` nor a developer's shell can supply keys or
 * bypass the login.
 */
import { spawn, spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import {
  existsSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const WEB_ROOT = resolve(import.meta.dirname, "..");
const REPO_ROOT = resolve(WEB_ROOT, "..", "..");
const COMPOSE_FILE = join(
  REPO_ROOT,
  "infra",
  "docker",
  "compose.keycloak.smoke.yaml",
);
const COMMITTED_REALM = join(
  REPO_ROOT,
  "infra",
  "keycloak",
  "realm-import",
  "grafy-realm.json",
);
const OIDC_CLIENT_ID = "grafy-web";
const REALM_ID = "grafy";

function requirePath(label, path) {
  if (!existsSync(path)) throw new Error(`Missing ${label} at ${path}`);
}

/** A port the operating system just gave us and immediately released. */
async function freePort() {
  const server = createServer();
  await new Promise((resolveListen, rejectListen) => {
    server.once("error", rejectListen);
    server.listen(0, "127.0.0.1", () => resolveListen());
  });
  const { port } = server.address();
  await new Promise((resolveClose) => server.close(() => resolveClose()));
  return port;
}

/**
 * This process's environment with every product variable dropped, so a developer's
 * shell cannot reach the stack and the stack's configuration has exactly one
 * author: this file. `NEXT_PUBLIC_GRAFY_*` is included because one of those flags
 * (`NEXT_PUBLIC_GRAFY_DEV_SESSION=1`) hands the dev server a stand-in session with
 * no login at all, which would make this suite green without ever signing in.
 */
function stackEnvironment(overrides) {
  const environment = { ...process.env };
  for (const name of Object.keys(environment)) {
    if (name.startsWith("GRAFY_") || name.startsWith("NEXT_PUBLIC_GRAFY_")) {
      delete environment[name];
    }
  }
  return { ...environment, ...overrides };
}

/** True once `child` is gone; false if it ignored us for `ms`. */
function exitedWithin(child, ms) {
  return new Promise((resolved) => {
    const timer = setTimeout(() => resolved(false), ms);
    child.once("exit", () => {
      clearTimeout(timer);
      resolved(true);
    });
  });
}

function run(label, command, args, options) {
  const result = spawnSync(command, args, { encoding: "utf8", ...options });
  if (result.error)
    throw new Error(`${label} could not start: ${result.error.message}`);
  if (result.status !== 0) {
    const detail = (result.stderr || result.stdout || "").trim().slice(-4_000);
    throw new Error(`${label} failed with status ${result.status}:\n${detail}`);
  }
  return result.stdout ?? "";
}

/**
 * The committed realm, retargeted at this run. Everything a real provider would
 * decide for itself stays as the repository ships it. Two changes are structural
 * and two are there so a single run cannot shoot itself in the foot:
 *
 *   - the client accepts exactly this run's callback and origin, never the
 *     committed `:3000` and never a wildcard, so a redirect to a port nobody owns
 *     is a failure rather than a surprise;
 *   - brute force is off: the journey signs in with a wrong password on purpose,
 *     and the lockout would outlive the run that caused it;
 *   - self-service and password recovery are off: no step needs them and both
 *     render pages this suite would rather not have to ignore.
 */
function deriveRealm(callbackUrl, origin) {
  const realm = JSON.parse(readFileSync(COMMITTED_REALM, "utf8"));
  realm.bruteForceProtected = false;
  realm.registrationAllowed = false;
  realm.resetPasswordAllowed = false;
  const clients = (realm.clients ?? []).map((client) =>
    client.clientId === OIDC_CLIENT_ID
      ? { ...client, redirectUris: [callbackUrl], webOrigins: [origin] }
      : client,
  );
  if (!clients.some((client) => client.clientId === OIDC_CLIENT_ID)) {
    throw new Error(`Committed realm has no ${OIDC_CLIENT_ID} client`);
  }
  return { ...realm, clients };
}

async function postForm(url, fields) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(fields),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(
      `${url} responded ${response.status}: ${JSON.stringify(body)}`,
    );
  }
  return body;
}

/**
 * Creates the run's realm through the provider's own admin API. The alternative, a
 * bind mount of the generated file, only works for a daemon that can see this
 * host path, which Colima and Docker Desktop disagree about.
 */
async function importRealm(issuer, adminUser, adminPassword, realm) {
  const token = await postForm(
    `${issuer}/realms/master/protocol/openid-connect/token`,
    {
      grant_type: "password",
      client_id: "admin-cli",
      username: adminUser,
      password: adminPassword,
    },
  );
  const response = await fetch(`${issuer}/admin/realms`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${token.access_token}`,
      "content-type": "application/json",
    },
    body: JSON.stringify(realm),
  });
  if (response.status !== 201) {
    const detail = await response.text();
    throw new Error(
      `Importing the smoke realm responded ${response.status}: ${detail}`,
    );
  }
}

async function main() {
  const python = join(REPO_ROOT, ".venv", "bin", "python");
  const alembicIni = join(REPO_ROOT, "alembic.ini");
  const playwrightCli = join(
    WEB_ROOT,
    "node_modules",
    "@playwright",
    "test",
    "cli.js",
  );
  requirePath("API interpreter (run `uv sync` at the repository root)", python);
  requirePath("Alembic config", alembicIni);
  requirePath("Playwright CLI (run `npm ci` in apps/web)", playwrightCli);

  const docker = spawnSync(
    "docker",
    ["version", "--format", "{{.Server.Version}}"],
    {
      encoding: "utf8",
    },
  );
  if (docker.status !== 0) {
    const detail = (
      docker.stderr ||
      docker.stdout ||
      docker.error?.message ||
      ""
    ).trim();
    throw new Error(
      `The real-backend suite serves OIDC from a container and could not reach a Docker daemon: ${detail || "docker version exited without output"}`,
    );
  }

  const [webPort, apiPort, issuerPort] = await Promise.all([
    freePort(),
    freePort(),
    freePort(),
  ]);
  const origin = `http://127.0.0.1:${webPort}`;
  const apiOrigin = `http://127.0.0.1:${apiPort}`;
  const issuer = `http://127.0.0.1:${issuerPort}`;
  const callbackUrl = `${origin}/api/v1/auth/oidc/callback`;
  const project = `grafy-real-smoke-${process.pid}`;
  const adminUser = "real-smoke-admin";
  // Test-only, for this process, never printed: the provider it signs in to dies
  // with the container.
  const adminPassword = randomBytes(18).toString("base64url");

  // Deliberately outside the repository: the database, artifact workspace,
  // API-owner lock, and generated realm are never a build output or an artifact.
  const runtimeRoot = mkdtempSync(join(tmpdir(), "grafy-real-backend-smoke-"));

  const stackEnv = stackEnvironment({
    GRAFY_COMMAND_HMAC_KEY: randomBytes(32).toString("hex"),
    GRAFY_CREDENTIAL_ENCRYPTION_KEY: randomBytes(32).toString("hex"),
    GRAFY_OIDC_AUTH_WRAPPING_KEY: randomBytes(32).toString("base64url"),
    GRAFY_OIDC_CLIENT_ID: OIDC_CLIENT_ID,
    GRAFY_OIDC_ISSUER: `${issuer}/realms/${REALM_ID}`,
    GRAFY_PUBLIC_ORIGIN: origin,
    GRAFY_CORS_ORIGINS: origin,
    GRAFY_AUTH_COOKIE_SECURE: "false",
    GRAFY_LOG_LEVEL: "INFO",
    // Kept on purpose: the isolated runtime root gives this API its own
    // single-owner lock instead of relaxing the guarantee.
    GRAFY_REQUIRE_SINGLE_API_OWNER: "true",
    PYTHONDONTWRITEBYTECODE: "1",
    // Read by playwright.real.config.ts to build the two webServer commands.
    REAL_SMOKE_ORIGIN: origin,
    REAL_SMOKE_API_ORIGIN: apiOrigin,
    REAL_SMOKE_PYTHON: python,
    REAL_SMOKE_RUNTIME_ROOT: runtimeRoot,
  });

  /** Only this run's container, addressed by the project name this run chose. */
  const compose = (args) =>
    run(
      `docker compose ${args.join(" ")}`,
      "docker",
      ["compose", "--project-name", project, "--file", COMPOSE_FILE, ...args],
      {
        cwd: REPO_ROOT,
        encoding: "utf8",
        env: stackEnvironment({
          KEYCLOAK_PROJECT: project,
          KEYCLOAK_HOSTNAME: issuer,
          KEYCLOAK_PORT: String(issuerPort),
          KEYCLOAK_ADMIN_USER: adminUser,
          KEYCLOAK_ADMIN_PASSWORD: adminPassword,
        }),
      },
    );

  const keep = process.env.REAL_SMOKE_KEEP === "1";
  /** Only teardown failures, so a red test and a leaked stack do not look alike. */
  const problems = [];
  let testRun = null;
  // The signal's exit code, remembered before teardown starts so an interrupted run
  // reports it whichever path reaches the end first.
  let stoppedBy = null;
  let cleaning = null;

  /** True while the cli is alive: a reaped child has one code set and the other null. */
  const testRunRunning = () =>
    testRun !== null &&
    testRun.exitCode === null &&
    testRun.signalCode === null;

  /**
   * Stops the Playwright run this process spawned. The API and the dev server belong
   * to that cli, are started in process groups of their own, and are only reachable
   * through it, so this starts with the one signal the cli answers: SIGINT, which is
   * also what a terminal sends. Escalating to the cli's own group is the last resort,
   * and the reason it is last: a cli killed before it answers SIGINT takes the two
   * services down with nothing to stop them.
   *
   * The bounds exist because a run that never answers would otherwise hold teardown
   * open forever. Past them the survivors are named rather than chased; nothing here
   * looks a process up by name.
   */
  const stopTestRun = async () => {
    if (!testRunRunning()) {
      return;
    }
    // Listened for before signalling: a child that dies in the same tick is not
    // mistaken for one that ignored the signal. Playwright stops its two services in
    // a couple of seconds; the bound is for the run that does not answer, including
    // one finalising its report, which ignores SIGINT on purpose.
    const interrupted = exitedWithin(testRun, 10_000);
    testRun.kill("SIGINT");
    if (await interrupted) return;
    console.error(
      `[real-backend smoke] playwright pid ${testRun.pid} did not answer SIGINT; killing its group`,
    );
    const killed = exitedWithin(testRun, 10_000);
    signalSpawnedGroup("SIGKILL");
    if (!(await killed) && testRunRunning()) {
      problems.push(`playwright pid ${testRun.pid} outlived SIGKILL`);
    }
  };

  /** Signals the group `detached` gave the cli, so its own children go with it. */
  const signalSpawnedGroup = (signal) => {
    if (!testRun?.pid) return;
    try {
      process.kill(-testRun.pid, signal);
    } catch {
      // Already gone, or no group was made for it; the cli itself is the fallback.
      testRun.kill(signal);
    }
  };

  /**
   * Removes what this run created: the container addressed by the project name this
   * run chose, and the runtime root. `keep` leaves both in place, which is the only
   * reason to ask for them, and prints what a person then has to remove.
   *
   * The compose calls are synchronous, so a signal arriving during one is handled
   * once it returns; that is why the signal handler exits the process itself instead
   * of waiting for the normal path to notice.
   */
  const removeStack = async () => {
    await stopTestRun();
    if (keep) {
      let provider = `project ${project}`;
      try {
        const id = compose(["ps", "-q"]).trim().split("\n")[0];
        if (id) provider = `container ${id} of project ${project}`;
      } catch (error) {
        provider = `${provider} (${error.message})`;
      }
      console.log(
        `[real-backend smoke] kept ${provider}\n` +
          `[real-backend smoke] kept ${runtimeRoot}\n` +
          `[real-backend smoke] remove both with: docker compose --project-name ${project} ` +
          `--file ${COMPOSE_FILE} down --volumes --remove-orphans && rm -rf ${runtimeRoot}`,
      );
      return;
    }
    try {
      compose(["down", "--volumes", "--remove-orphans"]);
    } catch (error) {
      problems.push(`the smoke Keycloak was not removed: ${error.message}`);
    }
    rmSync(runtimeRoot, { recursive: true, force: true });
  };

  /** Teardown runs at most once, however many callers ask for it. */
  const cleanup = () => (cleaning ??= removeStack());

  for (const [signal, code] of [
    ["SIGINT", 130],
    ["SIGTERM", 143],
  ]) {
    process.on(signal, () => {
      stoppedBy ??= code;
      cleanup()
        .catch((error) =>
          console.error(`[real-backend smoke] ${String(error)}`),
        )
        .finally(() => process.exit(stoppedBy));
    });
  }

  try {
    const realm = deriveRealm(callbackUrl, origin);
    // Written only so a kept run can answer "which callback did the provider
    // accept?"; the provider itself is configured through its admin API.
    writeFileSync(
      join(runtimeRoot, "realm.json"),
      `${JSON.stringify(realm, null, 2)}\n`,
    );

    // The database and the owner lock live under GRAFY_WORKSPACE, which defaults
    // to a path relative to the process cwd: the temp runtime root, not the repo.
    run(
      "alembic upgrade head",
      python,
      ["-m", "alembic", "-c", alembicIni, "upgrade", "head"],
      {
        cwd: runtimeRoot,
        env: stackEnv,
      },
    );

    compose(["up", "--detach", "--wait"]);
    await importRealm(issuer, adminUser, adminPassword, realm);

    testRun = spawn(
      process.execPath,
      [playwrightCli, "test", "--config", "playwright.real.config.ts"],
      {
        cwd: WEB_ROOT,
        env: stackEnv,
        stdio: "inherit",
        // Its own process group: a terminal's Ctrl-C reaches this process alone, so
        // the decision to stop the run stays here, and the last-resort kill can take
        // the cli's own children with it.
        detached: true,
      },
    );
    const status = await new Promise((resolved, rejected) => {
      testRun.once("error", rejected);
      testRun.once("exit", (code, signal) =>
        resolved(signal ? `signalled ${signal}` : code),
      );
    });

    await cleanup();
    if (problems.length > 0) {
      console.error(`[real-backend smoke] cleanup: ${problems.join("; ")}`);
    }
    // An interrupted run has no test result worth reporting, whatever the cli said.
    if (stoppedBy !== null) return stoppedBy;
    if (problems.length > 0) return 1;
    return typeof status === "number" ? status : 1;
  } catch (error) {
    await cleanup().catch((cleanupError) =>
      problems.push(`teardown could not finish: ${cleanupError.message}`),
    );
    console.error(
      `[real-backend smoke] ${error.message}${problems.length ? `\nCleanup: ${problems.join("; ")}` : ""}`,
    );
    return stoppedBy ?? 1;
  }
}

process.exitCode = await main();
