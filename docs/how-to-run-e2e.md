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

## TIFF canvas verification

The TIFF test uses a running **local test** stack with the repository Keycloak
realm (`owner` / `owner`), the API, Next, MinIO and the internal tiler. Do not
point it at production: it uploads four artifacts and leaves a saved
`TIFF archive demonstration` Project for inspection. Configure the API and
read-only tiler account using the deployment guide's “Add the tiler” procedure,
with local ports and a separate bucket/account. Keep generated keys in ignored
local files. The test does not stop the stack.

Generate synthetic archival scans with the tiler's GDAL environment:

```sh
cd apps/tiler
uv run python scripts/create_canvas_fixtures.py ../../artifacts/e2e-tiff/fixtures
cd ../..
E2E_STACK_ORIGIN=http://127.0.0.1:3000 \
TIFF_FIXTURE_DIR="$PWD/artifacts/e2e-tiff/fixtures" \
npm --prefix apps/web run test:e2e:tiff
```

The fixtures are a 12032 × 8192 RGB register, 16-bit grayscale, three pages,
and alpha. They contain invented records, not historical personal data.
The browser defaults to installed Chrome; set `TIFF_BROWSER_CHANNEL=chromium`
and install Playwright Chromium if needed. Tests sign in through SSO, upload
through the public upload API, save direct canvas cards and a checkpoint, then
exercise zoom, pointer pan and page navigation. Network URLs and phase counts
are retained in `artifacts/e2e-tiff/requests.json`, with canvas and zoom PNGs.
Wrong-Workspace reads must return 403/404. Recording is off so session cookies
are not included. A passing source/type check does not substitute for this run.
