# Web codebase cleanup plan

- **Status:** In progress.
- **Scope:** `apps/web` only. Backend, plugins, and generated API types are out of scope.
- **Branch:** `refactor/web-codebase-cleanup`.
- **Method:** Small behaviour-preserving steps. Every step must leave
  `typecheck`, `npm test`, `lint`, and `prettier --check` green before it is committed.

## Ground rules for this refactor

1. **Extract, do not redesign.** No prop contract changes, no state-model changes,
   no visual changes. Structural moves only, so a reviewer can diff a rename.
2. **One responsibility per file.** A file earns its name when its contents can be
   described in one sentence.
3. **Dead code is deleted, not commented.** A file with no importer and no route is
   removed together with its test.
4. **Tests are not rewritten to fit new internals.** If a move breaks a test import,
   only the import path changes.
5. **No `any`, no `@ts-ignore`, no new `eslint-disable`.**
6. **Verification gate for every commit:**

   ```bash
   cd apps/web
   npm run typecheck && npm test && npm run lint
   npx prettier --check "src/**/*.{ts,tsx,css,md,json}"
   ```

## Baseline (recorded before any change)

| Check | Result |
| --- | --- |
| `npm run typecheck` | exit 0 |
| `npm test` | 101 files / 760 tests passed |
| `npm run lint` | exit 0, 5 warnings (3 unused `_`, 2 `react-hooks/exhaustive-deps`) |
| Largest files | `Workbench.tsx` 4967, `WorkflowNode.tsx` 3779, `globals.css` 3407, `geo-map-artifact-renderer.tsx` 2694, `NodeSelector.tsx` 2450, `useRunExecution.ts` 2020 |

## Findings that drive the work

- **One import cycle:** `canvas/artifact-connections.ts` ↔ `canvas/artifact-viewer.ts`.
- **One god component:** `ui/Workbench.tsx` holds 174 hook calls and 52 local imports;
  logic spans ~4 000 lines before its JSX starts at line 4415.
- **Files that are really many components:** `canvas/nodes/WorkflowNode.tsx` holds ~20
  components; `canvas/nodes/artifact-renderers.tsx` and `geo-map-artifact-renderer.tsx`
  mix a renderer registry with per-type rendering.
- **Cross-feature tangles:** `workbench ↔ workspaces` (11 imports one way, 4 the other),
  `graphs → workbench`, `templates → workbench`.
- **Dead files** (no importer anywhere, no route):
  `features/templates/routes.ts`, `features/workbench/ui/SavedGraphBrowser.tsx`,
  `features/workbench/canvas/archive/bands/BandsTint.tsx`,
  `sandbox/fixtures/chat-completion.ts`,
  `features/workspaces/WorkspaceOverview.tsx` (only its own test imports it; the route
  redirects to `/settings`).

## Work packages

Ordered. Each is independently committable.

| ID | Package | State |
| --- | --- | --- |
| WP0 | Baseline checks recorded | done |
| WP1 | Delete dead files and their orphan tests | done (`d4078a10`) |
| WP2 | Break the `artifact-connections` ↔ `artifact-viewer` import cycle | done (`ba68bb3f`) |
| WP3 | Split `WorkflowNode.tsx` into `canvas/nodes/workflow/` | in progress (worker W1) |
| WP4 | Extract `Workbench.tsx` hook clusters | in progress |
| WP5 | Split `NodeSelector.tsx` | done (`e92a6329`) |
| WP6 | Split `useRunExecution.ts` (state algebra out of the hook) | in progress (worker W3) |
| WP7 | Split `artifact-renderers.tsx` into a registry plus per-type modules | done (`109abe59`) |
| WP7b | Split `artifact-renderers/table-renderer.tsx` (1263 lines still) | todo |
| WP8 | Split `geo-map-artifact-renderer.tsx` (map lifecycle vs per-layer rendering) | todo |
| WP9 | Split `LibraryPanel.tsx` (worker W2) and `WorkspaceLayout.tsx` | in progress (W2) |
| WP10 | Untangle cross-feature imports behind narrow shared modules | todo |
| WP11 | `globals.css` organisation and duplicate-rule sweep | todo |
| WP12 | Lint-warning cleanup, inline-style, raw-hex, orphaned CSS rule sets | todo |
| WP13 | `lib/api` barrel review; drop re-export indirection that hides nothing | todo |

## Worker roster (super.engineering, provider `pi`, model `ihpan/qwen3.8-flash-next-gguf`)

Workers are quiet chats, not panes. They do not commit; the orchestrator verifies and
commits. Their thread ids:

| Worker | Task | Thread id |
| --- | --- | --- |
| W1 | `WorkflowNode.tsx` → `canvas/nodes/workflow/` | `52eb5005-63d8-557e-8c54-7775ee575906` |
| W2 | `LibraryPanel.tsx` → `side-panel/library/` | `fb71841a-…` was stopped and closed; re-created per need |
| W3 | `useRunExecution.ts` → `ui/run-execution/` | `9487a5ee-e396-549d-8327-f32bf6841d2d` |

Dispatch and collect:

```bash
export PATH="$HOME/.superconductor/bin:$PATH"
sc chat new --provider pi --model ihpan/qwen3.8-flash-next-gguf --json
sc chat send <thread_id> --stdin < /tmp/prompt.md
sc chat stop <thread_id> --output json      # a stuck turn
sc chat list --json                          # active_turn flags
```

What the workers have proven:

- They are reliable at verbatim file splits and they respect a written protocol.
- They stall when a shared tree shows another worker's transient errors, and they
  invent confident bug reports about code they did not read. Always re-check a worker
  claim against the tree before acting on it.
- Therefore every worker prompt must say: verify with a **filtered** typecheck
  (`npx tsc --noEmit --incremental false 2>&1 | grep <your path>`) and never wait for
  the whole tree to be green.

Verification the orchestrator uses on a worker result before committing:

1. `npm run typecheck`, `npm test`, `npm run lint`, `npx prettier --check "src/**/*.{ts,tsx}"`.
2. Symbol parity: every top-level symbol of the old file exists exactly once afterwards.
3. Style parity: every `stylex` `key: value` pair of the old file survives unchanged, and
   no key is defined twice across the new modules.

## Log

Work is appended here as packages land, with the verification result for each step.
