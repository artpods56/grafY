<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

<!-- BEGIN:grafy-workbench-rules -->

# React Flow canvas checks

- The standalone Artifact Viewer is deprecated. New artifact presentation uses
  direct canvas cards from Library drops or materialized output-port drops. Do
  not add viewer creation actions. Preserve saved viewer rendering and bindings
  until an explicit document migration replaces them.

- When changing an artifact card's default size, update its drop placement and
  multi-card spacing. Verify a mixed selection lands without overlapping bodies.
- A gesture that places a node, card, or annotation hands the new thing the whole
  selection. Selection has four writers — node ids, edge ids, each card's
  `selected`, each annotation's `selected` — so write them through
  `useCanvasSelection` (`ui/workbench-canvas-selection.ts`) and verify with a real
  pointer drag that the thing held before the drop gave up its plate.
- Do not let global `svg` sizing or media resets constrain React Flow's edge
  layers. Keep any required override scoped to `.react-flow__edges > svg`.
- After changing node dimensions, handles, edge SVG styles, or canvas layout,
  verify at least one real pointer-drag connection in the rendered workbench.
  Compilation and programmatic edge insertion do not prove that wiring works.
- During a connection drag, wait for target-port reveal animations before
  measuring the handle. Playwright trial clicks can scroll clipped ancestors
  and give stale target coordinates.
- After changing canvas pointer/touch handlers or React Flow interaction options,
  run the Playwright gesture suite (`e2e/canvas-gestures.spec.ts`) described in
  `README.md`. Cover touch pan, pinch, cancellation, blank-pane tap deselection,
  node dragging, port wiring, and desktop mouse selection. A resized viewport
  alone does not test touch.

<!-- END:grafy-workbench-rules -->

<!-- BEGIN:web-app-conventions -->

# Web app conventions

## Sandbox

- `/sandbox` is a **development-only** UI spike host (`src/sandbox/`). It
  `notFound()`s in production and is not linked from product navigation.
- Put visual explorations there when they must use real Grafy chrome (tokens,
  overlay, `CatalogNodePreview`, port marks). Do not patch workbench feature
  files to make a spike render. Sandbox may import `features/`; never the reverse.
- Register spikes in `src/sandbox/catalog.ts` and `src/sandbox/SpikeHost.tsx`.
  See `src/sandbox/README.md`.

## Routing

- **Project** is the primary user object (ADR 0020). A Project holds Graphs and
  lives in exactly one Workspace. `/graphs` and
  `/workspaces/{slug}/graphs/{id}` are gone: the workbench route is
  `/workspaces/{slug}/projects/{projectId}`, and `/projects/new` inside a
  Workspace opens an unsaved Project. `/graphs/{id}` stays as a redirect entry so
  an old bookmark lands on the Project that holds it.
- `src/app/page.tsx` (`/`) renders the cross-location browser; `/workspaces` is
  the secondary **Teams & access** administration surface. Do not expose slugs,
  roles, capabilities, or user UUIDs on authoring surfaces.
- Renaming a route segment is a change to three places at once: the pages under
  `src/app`, `features/workbench/routes.ts`, and **the `webServer.url` readiness
  probe in `playwright.config.ts`**. That probe polls for a 2xx; a retired segment
  answers 404, Playwright waits out its timeout and reports "Next never became
  ready" on a healthy server.

## A green typecheck does not prove the app builds

`tsc --noEmit` has passed on a tree where a module declared the same binding twice
and Babel refused to compile it — every Project route returned **HTTP 500** and the
whole browser suite failed with an unhelpful message. The same is true in the other
direction at runtime: a **missing value export** (`import { useThing } from "…"`
where the module no longer exports it) type-checks nothing and throws when the
browser loads the module, so the canvas never mounts and the failure looks like a
timing problem.

So when a route is broken, prove the two things the typecheck cannot:

```bash
npx next dev --webpack -p <port> &   # capture $!
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:<port>/workspaces/<slug>/projects/new
kill <that pid>                    # never a pattern match: several servers run here
```

and read the **browser console** of a failing Playwright test, which names the
missing export in one line.

StyleX has the same blind spot: `npm run check:stylex` compiles every module
with the real Babel plugin and catches a cross-module style import the build
cannot resolve, which `tsc` and Vitest both pass.

## Shared components and call sites

- `src/components/ui` holds the shared controls, Base UI underneath and StyleX
  on top: `Button` and `ButtonLink`, `IconButton`, `Field` with
  `TextInput`/`TextArea`/`Select`, `Switch`, `Checkbox`, `Slider`,
  `ColorWell`/`ColorField`, `SegmentedControl`, `Surface`, `Dialog`, `Menu`, and
  `Notice`. Use them before hand-styling a button, a menu, a toggle, a colour
  well, or an alert. Local overrides go through `xstyle` (applied last), React
  Flow's `nodrag`/`nopan` through `className`. A Base UI trigger draws one with
  `render={<IconButton label="…" />}` and passes its children in.
  `MenuContent` already carries `nodrag nopan nowheel`.
- Take the kit's size rather than overriding it, and say so in the change when you
  do. Controls inside a canvas card use the `dense` step (`Field`, `TextInput`,
  `Select`, `Switch`, `Checkbox`, `Slider`, `ColorWell`): a card's rows are 25px and
  its type is 9px, and a 32px control there costs the card half its visible controls.
- A `role="switch"` or `role="checkbox"` is not a labelable element: a `<label>`
  wrapped around one gives its text to the hidden input, not the control. The kit's
  `Switch` and `Checkbox` point at the label with `aria-labelledby`; if you draw such
  a control yourself, do the same or it has no accessible name.
- `phoneTouch` names the three breakpoints that promise a 44px target — `on` at the
  shell's 620px, `rail` at the workbench's 720px, and `@media (pointer: coarse)` which
  two surfaces still carry locally. Never compose it with a recipe that sets
  `min-height`, and never apply it to a control inside a canvas card, which keeps its
  pixel size at every viewport. Whether the app should have three families is open
  (issue #211); collapsing one into another silently removes a target, so don't.
- `WorkspaceRail` is used by `GraphBrowser`, the Teams & access page, and the
  workspace layout (`[workspaceSlug]/layout.tsx`). Any prop added outside the
  core interface must be optional.
- `graphAgeLabel`, `sortGraphsByRecency`, and `filterGraphsByQuery` live in
  `WorkspaceGraphPanel.tsx` — they are reused outside the panel and should
  remain importable.
- `DialogContent` owns dialog frame geometry through its typed `size` prop.
  Consumers may own their internal layout, but must not override popup width,
  height, or responsive frame constraints inline.
- Use `useMediaQuery` for reactive JavaScript breakpoint state. Keep ARIA and
  behavior breakpoints aligned with the corresponding CSS media query.
- After changing popup geometry, run the Playwright popup suite
  (`e2e/workbench-popups.spec.ts`) at phone, tablet, desktop, and short
  landscape sizes. Verify the popup stays inside the viewport and its primary
  action remains visible. A width cap alone does not prevent an anchored popover
  from being positioned offscreen.

## CSS

- **A `.grafy-*` rule always beats the kit.** The StyleX PostCSS plugin compiles with
  `useCSSLayers: true` and `globals.css` is unlayered, and an unlayered declaration wins
  over a layered one whatever the specificity or the order — so an `xstyle` cannot beat
  a global rule either. Converting a control that `globals.css` styles therefore changes
  nothing a reader can see until the global rule is deleted: the Teams & access selects
  and the member rows still draw the global border, background, radius, and 44px phone
  floor. When you move such a surface onto the kit, name the global selectors that have
  to go with it, and leave the phone target on the control before you remove theirs.
- Global classes use the `.grafy-` prefix with BEM-ish structure:
  `.grafy-workspace-rail__item`, `.grafy-home__section-header`, etc.
- Shared shell and route styles live in `src/app/globals.css`; complex feature
  components may keep component-scoped styles in their `.tsx` file with StyleX.
  Do not split one layout contract between global CSS, StyleX, and inline styles.
- Light/dark theming uses `light-dark()` — do not use raw hex literals for
  component styling.
- StyleX ranks `:hover` above `:disabled`, so a plain `":hover"` colour also
  paints a disabled control. Key hover as `":hover:not(:disabled)"`.
- `--grafy-rail-width` is the single source of truth for sidebar width. Main
  content padding must reference it via `calc(var(--grafy-rail-width, 200px) + …)`.

## Artifact type labels

- `features/workbench/canvas/artifact-type-label.ts` is the single place that
  names an artifact type for a person: the catalog title (`Text value`,
  `Sequence<Text value>`), with the schema version inline as `Text value · v2`
  — the node catalog's separator — only once it is past `@1`. Keep the full
  `id@version` reachable in a tooltip or the port type inspector.
- Every label helper takes its catalog as a required argument. A call site with
  a registry passes `registry.artifact_types`; one without passes `null` on
  purpose, and reads back the full identity (`scalar.text@1`) — never a bare
  id. Omitting the catalog is a type error, so a surface cannot quietly degrade
  to raw ids.
- `artifactTypeKey` in `canvas/artifact-type-key.ts` is identity, not a label:
  port compatibility, handle ids, saved bindings, and API payloads compare it.
  Never swap a label into one of those, and never print one as a card or port
  caption.

## Tests

- `@testing-library/react` is **not** installed. Tests use
  `renderToStaticMarkup`, import pure functions directly, or mount interaction
  tests with `react-dom/client` and `act`.
- Test files need `.tsx` extension when they contain JSX.
- A test double for a Base UI part must honour `render` (clone the element with
  the part's props and children). A trigger drawn through a shared component
  takes its accessible name from that element, so a double that ignores
  `render` drops the name.
- `npm test` runs the Vitest suite (`vitest run`).
- When verifying a worktree, use `GRAFY_E2E_PORT` to give its dev server a free
  port. Do not reuse a server from another checkout; its compiled code does not
  verify this worktree.
- The **Web browser acceptance** job in `.github/workflows/ci.yml` runs every
  spec in `e2e/` on desktop, phone, and tablet only for pushes to `main`, where
  `publish-images` waits for it. Pull requests do not run it, so run the specs
  you touched before pushing. The real-backend smoke job (`e2e-real/`) runs on
  every pull request.
- Run Playwright invocations serially with the default configuration. Separate
  invocations share the output and report directories; a new run can delete
  another run's active traces and cause teardown failures. Parallel invocations
  require distinct output and reporter directories.
- `e2e/` answers the API boundary with fixtures; `e2e-real/` talks to a real
  FastAPI process and a real Keycloak (`npm run test:e2e:real`, its own config
  and output directories). Do not move a step from one suite into the other: the
  mocked suite fails on an unexpected API request on purpose, and the real suite
  is where the two applications are proven to still speak to each other.
- The real-backend suite needs the checkout to itself. Next runs one dev server
  per directory, so stop `just web` for this worktree and run one invocation at a
  time. `scripts/real-smoke.mjs` owns only the provider container, addressed by the
  project name it generated; the API and dev server belong to Playwright's
  `webServer`, which holds their pids. Do not add pattern-based cleanup for either.

## API hooks

- Cross-workspace data (e.g., graphs from all workspaces) requires an explicit,
  typed multi-request SWR key and fetcher. See `useAllWorkspacesGraphs` in
  `src/hooks/use-api.ts`; do not pass an array of URLs to the global string
  fetcher.
- Barrel exports: `src/lib/api/index.ts` re-exports everything.
  Features like `useAuthSession` must be imported from their full file path
  unless a barrel exists.

## Browser APIs and storage

- Workbench IDs must support plain HTTP LAN origins used for mobile testing.
  Use `createUuid` from `features/workbench/model/uuid.ts`; it uses
  `crypto.getRandomValues` when the secure-context-only `crypto.randomUUID`
  API is unavailable.

- Web Storage is for device-local presentation preferences only. Current keys
  cover theme, workspace-rail collapse, and canvas-grid settings.
- Do not persist workspace selection, graph state, collaboration state,
  credentials, authorization data, or server-owned user settings in
  `localStorage` or `sessionStorage`.
- Do not add compatibility reads for retired product-name keys. Preference
  migrations must be explicit and time-bounded when they are genuinely needed.

<!-- END:web-app-conventions -->
