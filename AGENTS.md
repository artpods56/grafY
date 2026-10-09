## Agent skills

### Issue tracker

Issues and specs live in GitHub Issues on `artpods56/grafY` (via the `gh` CLI). See `docs/agents/issue-tracker.md`.

### Triage labels

Custom vocabulary: `triage`, `question`, `4agent`, `4human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` at the repo root, ADRs in `docs/adr/`. See `docs/agents/domain.md`.

## The ways to hurt yourself

1. **Killing by pattern.** Never `pkill -f`, `pgrep | kill`, or kill a PID you
   found by matching a name, path, or worktree string. This machine runs several
   dev servers at once and your own agent process carries this worktree's path
   in its argv. Kill only a process whose PID you captured at spawn.
2. **The shared `.env`.** `.env` is gitignored and holds live local secrets
   (encryption and HMAC keys, OIDC settings). The Justfile sets `dotenv-load`,
   so every `just` recipe reads it; a worktree without one silently falls back
   to built-in defaults. Never print it or commit it. `.env.example` is the
   only shareable copy.
3. **Production paths from a dev box.** `just prod`, `just deploy`, `just
   status`, and `just logs` run Docker Compose against `/etc/grafy/grafy.env`
   and the `/etc/grafy/storage.override.yaml` override; `just minio` drives
   `/opt/minio/compose.yaml`. Those are the live host's files, not sandbox
   state.
4. **A stale vendored SDK wheel.** Plugins resolve `grafy_core` from the
   committed wheels under `plugins/*/wheels`, never from monorepo `libs/core`.
   When `libs/core` changes a module a Plugin imports, run `just sdk-wheel`,
   commit the rebuilt wheels, and update the sha256 pinned in
   `tests/unit/architecture/test_import_boundaries.py` (see
   `docs/design/plugin-development.md`). That test fails when you forget.
5. **Hand-editing generated API types.**
   `apps/web/src/lib/api/generated/grafy.ts` is regenerated from the FastAPI
   schema by `npm run generate:api` in `apps/web`; CI fails on drift via
   `npm --prefix apps/web run check:api`. Change the route or model and
   regenerate, don't edit.
6. **A second API owner.** Collaboration assumes one API process. By default
   (`require_single_api_owner: true` in `libs/shared`) the API holds an
   exclusive workspace lock at startup (`apps/api/src/grafy_api/single_owner.py`).
   A second `just api` over the same workspace root fails by design; don't kill
   your way around it.

## Hit every surface

The commonest defect is a change that works where you tested and is missing
elsewhere. Walk this list and say which entries applied:

- **Contract.** An API route change also changes the web client: regenerate
  with `npm run generate:api` in `apps/web`. `check:api` fails when the
  committed file lags the schema.
- **Builtin families vs Plugins.** A node or artifact behavior may live in
  app-owned builtin families under `apps/api` and in one of `plugins/*` (gis,
  llm, mistral, notarius, ocr, python, sql, typesafe). Provider-shaped features
  need a decision per host, even if the decision is "not here".
- **SDK wheel.** If the change touched a `libs/core` module a Plugin imports,
  the vendored wheels and their pinned digest move with it.
- **Tenancy and capabilities.** Every graph belongs to exactly one Workspace;
  effective permission is role ∩ PAT scope ∩ capability (`CONTEXT.md`). A new
  route needs a Workspace scoping and a capability decision, not just an id
  lookup.
- **Reverse states.** Every way in needs the way out and the way to see it.
  Membership grant needs revoke. Graph archive needs unarchive. `just
  db-upgrade` has `just db-downgrade`. A one-way door is a bug.
- **Docs.** `CONTEXT.md` vocabulary, the relevant `docs/design/*.md`, and
  `docs/adr/*` go stale when a decision changes, not when code compiles.
- **Web traps.** Frontend work follows `apps/web/AGENTS.md`; read it before
  touching `apps/web`, it holds the web-specific hazards.

## Verifying

- Smallest proof first: `uv run pytest tests/unit/<area>/test_<thing>.py`, or
  `npm --prefix apps/web test -- <file>` for the web suite. Architecture
  changes run `tests/unit/architecture/` locally; CI owns everything else.
- Do not run repo-wide suites. `just check` and the full matrix in
  `.github/workflows/ci.yml` belong to CI.
- Persistence tests that need PostgreSQL silently skip unless
  `GRAFY_TEST_POSTGRES_URL` points at an empty disposable database; CI
  supplies one as a service container. A green local run has not exercised the
  relational path without it — say so instead of implying it did.
- Plugin-runtime tests (`tests/integration/executions/`, e.g.
  `test_workspace_plugin_docker.py`) need Docker.
- Wait on events, never sleeps. The suite drives async and collaboration flows
  with `asyncio.Event` and explicit waits (see
  `tests/unit/core/test_callable_nodes.py`). A test that needs a timeout to
  pass is wrong.

## Taste

- Boundaries are enforced by tests, not review comments:
  `tests/unit/architecture/test_import_boundaries.py` fails when the
  application owners it lists (realtime, uploads, node secrets, ...) import
  route modules, or when execution and plugin hosting import HTTP, and
  `apps/web/src/architecture.test.ts` fails on module cycles or a feature
  importing a route or a `/sandbox` spike. Keep them failing for the right
  reason, and extend them when you add a boundary.
- Shared configuration is a leaf package that builds nothing (ADR 0011).
  Builtin families are application code, not Plugin releases (ADR 0007).
- `CONTEXT.md` vocabulary is fixed: "Team" and "organization" both mean a
  shared Workspace; there is no second grouping aggregate and no per-graph
  ACL. Do not invent synonyms in code or docs.
- Durable things are append-only and digest-addressed: graph documents carry
  immutable checkpoints and a Plugin release is a digest-addressed freeze.
  Do not mutate them in place.

## Docs and work artifacts

- `docs/design/` and `docs/adr/` hold decisions, cross-component constraints,
  and traps that are hard to discover from source. If reading the code answers
  the question, leave it out of the docs. When a documented decision changes,
  rewrite the affected text instead of appending a second account.
- `docs/how-to-*.md` are operating procedures (deploy, plugin publication).
  Keep them true to the Justfile and Compose files.
- Do not commit implementation plans, research notes, or agent scratch files.
  Keep working material outside the worktree. The existing `docs/plans/`
  entries are a known cleanup target, not a pattern to copy.
- Track active work in the GitHub issue that owns it on `artpods56/grafY` via
  `gh` (`docs/agents/issue-tracker.md`). A merged PR is the implementation
  record; do not leave a second checklist behind in the repository.
