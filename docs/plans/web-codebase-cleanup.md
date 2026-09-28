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

## Gate

A step is done only when all of these pass from `apps/web`:

```bash
npm run typecheck
npm test
npm run lint
npm run check:stylex                                   # added by this refactor
npx prettier --check "src/**/*.{ts,tsx}"
npm run build
```

`check:stylex` and `build` are not optional. The StyleX Babel plugin fails the
production build on imports that `tsc` and Vitest both accept, and that is how commit
`109abe59` shipped a broken build (fixed in `a0730fcc`).

**Visual-parity oracle.** The StyleX bundle filename is a content hash. Build the tree at
the last pre-split commit into a scratch directory (`git archive <sha> apps/web | tar -x
-C /tmp/base && ln -s <repo>/apps/web/node_modules /tmp/base/apps/web/node_modules`) and
compare `.next/static/css/*.css`. Byte-identical bundles mean no rule and no cascade order
changed, which is the only proof that matters when StyleX rules of equal specificity are
involved. Verified at `596739a3`: the tree emits `fcb709c66d72cbd5.css`, byte-identical to
the build at `d4078a10`, so every split since the dead-code deletion changed no CSS at all.

## Log

| Commit | Package | Evidence |
| --- | --- | --- |
| `d4078a10` | WP1 dead code: `SavedGraphBrowser`, `WorkspaceOverview` + test, `templates/routes.ts`, `sandbox/fixtures/chat-completion.ts`, `canvas/archive/bands` | −890 lines; ADR 0001 naming example repointed |
| `ba68bb3f` | WP2 cycle: `canvas/artifact-origin-edge.ts` | module graph reported 1 cycle → 0 |
| `109abe59` | WP7 `artifact-renderers/` split | build was broken by it, fixed in `a0730fcc` |
| `e92a6329` | WP5 `NodeSelector` → `ui/node-selector/` | 2450 → 1214 lines |
| `80c7d5ac` | WP4a fit-view geometry, drop hit-tests, module boundaries | `Workbench.tsx` −174; new `model/module-boundary.ts` + 3 tests, falsified |
| `d4e295c8` | WP6 `useRunExecution` → `ui/run-execution/state.ts` | 2021 → 1871; 22 new tests |
| `0ff7349f` | WP12a lint config + two memo fixes | `Workbench.tsx` −2 lint warnings; edges dep removed, `activeArtifactViewers` memoised |
| `a0730fcc` | registry cycle + StyleX-resolvable constants + `check:stylex` | 3 modules failing the StyleX compile → 0 |
| `9ad17bb9` | `src/architecture.test.ts` | cycles, features→app/sandbox, generated-types entry point |
| `30adc841` | WP9a `LibraryPanel` → `side-panel/library/` | 1296 → 571; no importer or test path changed |
| `59f3c6b2` | WP3 `WorkflowNode` → `canvas/nodes/workflow/` | 3778 → 26 lines in the entry file |
| `596739a3` | WP8 geo-map → `canvas/nodes/geo-map/` | 2694 → 166 lines in the entry file |

After `596739a3`: typecheck 0 errors, 104 files / 790 tests green, eslint silent,
`check:stylex` clean over 324 modules, prettier clean, `npm run build` green.

## Notes for whoever continues

- Workers write confident nonsense as often as they write code. Every claim in this file
  was re-checked against the tree or a build before it was recorded here. Do the same.
- `artifactTypeKeyDisplay`, `ArtifactTypeFormat`, and `artifact-renderers.tsx` do not
  exist. Two workers independently reported breakage caused by them. Trust `git grep`.
- A shared style module may export a `stylex.create` result, never that result plus a
  plain constant: the StyleX plugin cannot resolve the plain constant across modules and
  the build fails.
- `docs/design/frontend-navigation-graph.md` is stale: it says `/workspaces/[slug]` renders
  `WorkspaceOverview`, which this pass deleted; the route redirects to `/settings`.

## Follow-ups deliberately left open

Each was investigated and stopped on purpose, not overlooked.

1. **~200 lines of orphaned `.grafy-*` CSS** in `src/app/globals.css`:
   `grafy-auth-threshold__eyebrow`, `grafy-flow-controls`, `grafy-workspace-create__hint`,
   `grafy-workspace-empty__mark`, `grafy-workspace-member-form`,
   `grafy-workspace-overview__actions`, `grafy-workspace-overview__copy`,
   `grafy-workspace-overview__header`, `grafy-workspace-overview__section`,
   `grafy-workspace-overview__section-heading`, `grafy-workspace-sort`. The
   `workspace-overview` group is what `WorkspaceOverview` left behind in `d4078a10`.
   Caution before deleting: a naive substring scan reports `grafy-select-item` and
   `grafy-tabs-trigger` as orphans too, and both are false positives - `workspace-layout__
   nav-toggle--select-item` contains the first as a substring of a different class.
   Verify any sweep with `npm run build` plus a screenshot pass on the workspaces pages.
2. **`Workbench.tsx` is 4432 lines and nothing in the repository renders it.** An earlier
   entry here recorded "1878"; that number belongs to `useRunExecution.ts` and was
   attached to the wrong file. `WorkbenchBody` is one function of roughly 3,900 lines
   containing 67 `useCallback`s, 14 `useEffect`s and 16 `useRef`s, and there is no
   `Workbench.test.tsx`. Deleting the authoring gate out of the viewer-commit path left
   every one of the 653 workbench tests green. That is the real defect: not the line count
   but the absence of any seam through which the wiring can be tested. The two clusters
   moved out in round two below each arrived with their own falsified tests for exactly
   that reason.
3. **The secret-module label override is inert.** `.grafy-node-card__label--secret` is
   emitted after `.grafy-node-card__type-tag--library` with equal specificity and no
   `!important`, so the library colour wins when both classes land on one element. A
   browser pass confirmed the computed colour either way. Decide with the product owner
   whether secret nodes should look different, then delete or fix the specificity.
4. **Remaining hotspots**, measured with `wc -l` over non-test, non-sandbox, non-generated
   source: `Workbench.tsx` 4432, `useRunExecution.ts` 1870,
   `artifact-renderers/table-renderer.tsx` 1265, `NodeSelector.tsx` 1214,
   `WorkspaceLayout.tsx` 1172 (see the revert note: its importers resolve through relative
   paths), `ExecutionHistoryDrawer.tsx` 928,
   `canvas/nodes/workflow/config-fields.tsx` 910, `useSavedGraphLifecycle.ts` 882,
   `ContextualNodeDiscovery.tsx` 835. A split that touches no `stylex.create` block cannot
   change the bundle, so the style-free ones remain the safe order of attack.

## Round two: the two style-free files and the first two Workbench clusters

| Commit | Package | Evidence |
| --- | --- | --- |
| `35d8570d` | `ui/workbench-artifact-viewers.ts` - the viewer/annotation commit rule | `Workbench.tsx` 4754 -> 4569; 4 new tests, 5 mutations killed |
| `0f0aa1d3` | `ui/workbench-node-commands.ts` - node gestures, with the duplicated config-and-plugs block written once | `Workbench.tsx` 4569 -> 4432; 6 new tests, 5 mutations killed |
| `de911dd6` | `ui/saved-graph-dirtiness.ts` - the unsaved-work policy as one pure function | 9 new tests, 4 mutations killed; no existing test edited |
| `1a7908b0` | `room/command-outbox.ts` - command correlation out of the socket session | `graph-room-session.ts` 1034 -> 827; 6 new tests, 3 mutations killed |

Gate after `1a7908b0`: typecheck 0 errors, **108 files / 815 tests**, eslint silent,
prettier clean, `check:stylex` clean over 332 modules, `npm run build` green, and the
three stylex bundles still byte-identical to the build at `d4078a10`.

Two things worth keeping from this round:

- The room worker's outbox boundary is the pattern to reuse: a class that owns a transport
  *and* the correlation of in-flight work should hand correlation a read-only pointer plus
  a readiness gate, take messages in, and return frames and settle-decisions out. The
  extracted module then needs no socket to be tested.
- `saved-graph-dirtiness.ts` exists mainly to say out loud that `isDirty` and `workAtRisk`
  are different questions. A canvas that differs from the last checkpoint may still be safe
  to reload because the room journal holds those edits; a canvas the disconnected room
  refused to take is not. That distinction decides whether a reload warns the user, and it
  was previously four inline expressions.

## What did not go well

- A worker split `WorkflowCanvas.tsx` at 02:30 and the app build failed. Typecheck,
  vitest, eslint and prettier were all green. Cause: a style module that exported `MONO`
  next to `stylex.create` results, which the StyleX Babel plugin cannot resolve across
  modules - it inlined the class name in one file and left `styles.mono` in another.
  `scripts/check-stylex.mjs` (`npm run check:stylex`) compiles every style module and
  fails on unresolved `styles.x`.
- Two workers reported a repo-wide breakage caused by `artifactTypeKeyDisplay`,
  `ArtifactTypeFormat` and `artifact-renderers.tsx`, none of which exist, and one of them
  reverted clean committed work on the strength of it. Both also "found" that
  `WorkspaceRail`'s styles had been changed to `!important` and had to restore values they
  had never touched.
- Consequence: workers get verification commands filtered to their own files and a direct
  instruction never to revert. Even then a revert happened, which is why nothing was
  committed without the whole gate running over the shared tree first.
- Useful output: 4 splits landed (LibraryPanel, WorkflowNode 3778 lines into
  `canvas/nodes/workflow/`, geo-map 2694 into `canvas/nodes/geo-map/`, NodeSelector,
  `useRunExecution`) and one worker correctly concluded, after reproducing emitted-rule
  order changing, that `WorkspaceRail` must not be split - and left the styles alone.

## Reverted: the WorkspaceLayout split

A worker landed `WorkspaceContext.tsx`, `WorkspaceRail.tsx`, `WorkspaceRouteStatus.tsx`,
`workspace-presentation.ts`, `session-presentation.ts` and `workspace-rail-preferences.ts`
at 05:50. The move preserved every literal (compared as a sorted multiset of string and
numeric literals against `git show HEAD:...`) and the built CSS came back byte-identical,
so it was not a styling problem. It was left with 103 typecheck errors because importers
still pulled the moved symbols from `WorkspaceLayout`, and the worker kept editing while
the gate ran. Reverted to `78889ca7` for the source tree; the gate is green again.

If this split is retried, the missing step is the importer pass: `useWorkspaceContext`,
`workspaceDisplayName`, `resolveSelectedWorkspace`, `WorkspaceRail` and friends are
imported from `./WorkspaceLayout` by relative paths across `src/app/workspaces`,
`src/features/graphs` and `src/features/workbench`, so a `grep` for the `@/` alias form
finds none of them.

## Round three: three more files, and the drawer's styles move proved by hash

| Commit | Package | Evidence |
| --- | --- | --- |
| `3e0c9568` | `ui/workbench-artifact-cards.ts` - card placement, grouping, drop position | `Workbench.tsx` 4432 -> 4356; 7 tests, 5 mutations killed |
| `73667029` | `ExecutionHistoryDrawer.styles.ts` + `execution-history-query.ts` + `execution-history-display.ts` | drawer 928 -> 490; 10 tests, 4 mutations killed; **CSS byte-identical** |
| `ee80e736` | `artifact-renderers/table/{column-picker,page-navigation,styles,constants}` | `table-renderer.tsx` 1265 -> 662; **CSS byte-identical** |

Gate after `ee80e736`: typecheck 0 errors, 110 files / 832 tests green, eslint silent,
prettier clean, `check:stylex` clean over 342 modules, `npm run build` green, and the three
stylex bundles byte-identical to the build at `d4078a10`.

Two things this round settled:

- **A `stylex.create` block can move between modules safely, but only the hash says so.**
  Two packages moved whole styles files and both came back byte-identical. That does not
  make it generally safe - the same specificity hazard from `WorkspaceRail` still applies -
  it means the check is cheap enough that nobody may skip it.
- **A "query" module must not import a stylesheet.** The drawer worker first put the
  display helpers (`statusStyle` reads the style object) next to the SWR loaders in one file
  named `execution-history-query.ts`. The modules were split again into `...-query.ts` and
  `...-display.ts`; the second now owns the styles import and the first has none.

### Where to go next, measured

`wc -l` over non-test, non-sandbox, non-generated source, with `grep -c stylex` as the risk
flag:

| File | Lines | stylex | Note |
| --- | --- | --- | --- |
| `ui/Workbench.tsx` | 4356 | 0 | still no test renders it; ~60 `useCallback`s left in `WorkbenchBody` |
| `ui/useRunExecution.ts` | 1870 | 0 | safest large target next; `ui/run-execution/state.ts` already shows the shape |
| `ui/NodeSelector.tsx` | 1214 | 100 | `ui/node-selector/styles.ts` already exists; the rest is one component |
| `workspaces/WorkspaceLayout.tsx` | 1172 | 0 | safe, but do the importer pass (see the revert note) |
| `canvas/nodes/workflow/config-fields.tsx` | 910 | 43 | split inside `workflow/`, styles move must be hash-checked |
