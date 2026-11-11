# Run the e2e pilot

Use Node.js 24.8 or newer, Python 3.14, uv, and a running Docker daemon.
Stop this checkout's web dev server first. Run one invocation at a time.

```sh
uv sync --locked
npm --prefix apps/web ci
npm --prefix apps/web run test:e2e
```

The web engine downloads Chromium on its first run. On Linux, install browser
system libraries with `cd apps/web && npx e2e-web install chromium --with-deps`.

The single test signs in through the repository's Keycloak fixture account,
creates and saves a Project with a Graph, adds a builtin Text input, runs it,
and checks its successful execution status. It uses exact locators and `expect`.
No model, provider login, API key, or agent step is configured.

The launcher creates free ports, a temporary SQLite database and workspace,
fresh application keys, and a disposable Keycloak container. It starts FastAPI
and Next, waits for readiness, runs e2e, and removes its own services and data.
It ignores inherited Grafy configuration and never loads the repository `.env`.
Reports remain under `apps/web/.e2e/`; traces and video are disabled because
recordings can contain session cookies. Do not upload runtime data or keys.

```sh
# Watch the same flow:
npm --prefix apps/web run test:e2e -- --headed
# Five independent runs, each with a new stack, stopping on the first failure:
for run in 1 2 3 4 5; do
  npm --prefix apps/web run test:e2e || exit 1
done
```

CI runs the pilot against the real backend on pull requests and main pushes.
Image publishing does not wait for it. This pilot covers only the basic flow;
responsive layouts, gestures, artifact management, and agent interactions need
manual checks. Unit, backend, lint, type, and API contract checks remain separate.

Framework docs ship in `apps/web/node_modules/e2e/docs`. Run
`cd apps/web && npx e2e guide` for the installed version's guide.
