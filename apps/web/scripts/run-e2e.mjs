#!/usr/bin/env node
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

function stackEnvironment(overrides) {
  const environment = { ...process.env };
  for (const name of Object.keys(environment)) {
    if (name.startsWith("GRAFY_") || name.startsWith("NEXT_PUBLIC_GRAFY_")) {
      delete environment[name];
    }
  }
  return { ...environment, ...overrides };
}

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
      `Importing the e2e realm responded ${response.status}: ${detail}`,
    );
  }
}

async function main() {
  const python = join(REPO_ROOT, ".venv", "bin", "python");
  const alembicIni = join(REPO_ROOT, "alembic.ini");
  const e2eCli = join(WEB_ROOT, "node_modules", "e2e", "dist", "cli", "bin.js");
  requirePath("API interpreter (run uv sync --locked)", python);
  requirePath("Alembic config", alembicIni);
  requirePath("e2e CLI (run npm ci in apps/web)", e2eCli);
  const services = [];
  const startService = (command, args, options) => {
    const child = spawn(command, args, {
      ...options,
      stdio: "inherit",
      detached: true,
    });
    services.push(child);
    return child;
  };
  const ready = async (url, child, timeout) => {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      if (child.exitCode !== null || child.signalCode !== null) {
        throw new Error(`Service exited before ${url} was ready`);
      }
      try {
        const response = await fetch(url, {
          signal: AbortSignal.timeout(2_000),
        });
        if (response.ok) return;
      } catch {
        /* Retry the readiness condition until its deadline. */
      }
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    throw new Error(`Service readiness timed out: ${url}`);
  };

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
      `The e2e pilot serves OIDC from a container and could not reach a Docker daemon: ${detail || "docker version exited without output"}`,
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
  const project = `grafy-e2e-pilot-${process.pid}`;
  const adminUser = "e2e-pilot-admin";
  const adminPassword = randomBytes(18).toString("base64url");

  const runtimeRoot = mkdtempSync(join(tmpdir(), "grafy-e2e-pilot-"));

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
    GRAFY_REQUIRE_SINGLE_API_OWNER: "true",
    PYTHONDONTWRITEBYTECODE: "1",
    E2E_TELEMETRY_DISABLED: "1",
    E2E_STACK_ORIGIN: origin,
  });

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

  const keep = process.env.E2E_STACK_KEEP === "1";
  const problems = [];
  let testRun = null;
  let stoppedBy = null;
  let cleaning = null;

  const testRunRunning = () =>
    testRun !== null &&
    testRun.exitCode === null &&
    testRun.signalCode === null;

  const stopTestRun = async () => {
    if (!testRunRunning()) {
      return;
    }
    const interrupted = exitedWithin(testRun, 10_000);
    testRun.kill("SIGINT");
    if (await interrupted) return;
    console.error(
      `[e2e pilot] e2e pid ${testRun.pid} did not answer SIGINT; killing its group`,
    );
    const killed = exitedWithin(testRun, 10_000);
    signalSpawnedGroup("SIGKILL");
    if (!(await killed) && testRunRunning()) {
      problems.push(`e2e pid ${testRun.pid} outlived SIGKILL`);
    }
  };

  const signalSpawnedGroup = (signal) => {
    if (!testRun?.pid) return;
    try {
      process.kill(-testRun.pid, signal);
    } catch {
      testRun.kill(signal);
    }
  };

  const removeStack = async () => {
    await stopTestRun();
    for (const child of services.reverse()) {
      if (child.exitCode !== null || child.signalCode !== null) continue;
      const stopped = exitedWithin(child, 10_000);
      process.kill(-child.pid, "SIGTERM");
      if (!(await stopped)) {
        const killed = exitedWithin(child, 10_000);
        process.kill(-child.pid, "SIGKILL");
        if (!(await killed))
          problems.push(`Service pid ${child.pid} outlived SIGKILL`);
      }
    }
    if (keep) {
      let provider = `project ${project}`;
      try {
        const id = compose(["ps", "-q"]).trim().split("\n")[0];
        if (id) provider = `container ${id} of project ${project}`;
      } catch (error) {
        provider = `${provider} (${error.message})`;
      }
      console.log(
        `[e2e pilot] kept ${provider}\n` +
          `[e2e pilot] kept ${runtimeRoot}\n` +
          `[e2e pilot] remove both with: docker compose --project-name ${project} ` +
          `--file ${COMPOSE_FILE} down --volumes --remove-orphans && rm -rf ${runtimeRoot}`,
      );
      return;
    }
    try {
      compose(["down", "--volumes", "--remove-orphans"]);
    } catch (error) {
      problems.push(`the e2e Keycloak was not removed: ${error.message}`);
    }
    rmSync(runtimeRoot, { recursive: true, force: true });
  };

  const cleanup = () => (cleaning ??= removeStack());

  for (const [signal, code] of [
    ["SIGINT", 130],
    ["SIGTERM", 143],
  ]) {
    process.on(signal, () => {
      stoppedBy ??= code;
      cleanup()
        .catch((error) => console.error(`[e2e pilot] ${String(error)}`))
        .finally(() => process.exit(stoppedBy));
    });
  }

  try {
    const realm = deriveRealm(callbackUrl, origin);
    writeFileSync(
      join(runtimeRoot, "realm.json"),
      `${JSON.stringify(realm, null, 2)}\n`,
    );

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

    const api = startService(
      python,
      [
        "-m",
        "uvicorn",
        "grafy_api.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        String(apiPort),
      ],
      { cwd: runtimeRoot, env: stackEnv },
    );
    await ready(`${apiOrigin}/ready`, api, 120_000);
    const web = startService(
      process.execPath,
      [
        join(WEB_ROOT, "node_modules", "next", "dist", "bin", "next"),
        "dev",
        "--webpack",
        "--hostname",
        "127.0.0.1",
        "--port",
        String(webPort),
      ],
      {
        cwd: WEB_ROOT,
        env: {
          ...stackEnv,
          GRAFY_API_UPSTREAM: apiOrigin,
          NEXT_TELEMETRY_DISABLED: "1",
          NEXT_PUBLIC_GRAFY_DEV_SESSION: "",
        },
      },
    );
    await ready(`${origin}/`, web, 240_000);

    testRun = spawn(
      process.execPath,
      [e2eCli, "run", ...process.argv.slice(2)],
      {
        cwd: WEB_ROOT,
        env: stackEnv,
        stdio: "inherit",
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
      console.error(`[e2e pilot] cleanup: ${problems.join("; ")}`);
    }
    if (stoppedBy !== null) return stoppedBy;
    if (problems.length > 0) return 1;
    return typeof status === "number" ? status : 1;
  } catch (error) {
    await cleanup().catch((cleanupError) =>
      problems.push(`teardown could not finish: ${cleanupError.message}`),
    );
    console.error(
      `[e2e pilot] ${error.message}${problems.length ? `\nCleanup: ${problems.join("; ")}` : ""}`,
    );
    return stoppedBy ?? 1;
  }
}

process.exitCode = await main();
