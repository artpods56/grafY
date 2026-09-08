<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

<!-- BEGIN:grafy-workbench-rules -->
# React Flow canvas checks

- Do not let global `svg` sizing or media resets constrain React Flow's edge
  layers. Keep any required override scoped to `.react-flow__edges > svg`.
- After changing node dimensions, handles, edge SVG styles, or canvas layout,
  verify at least one real pointer-drag connection in the rendered workbench.
  Compilation and programmatic edge insertion do not prove that wiring works.
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

- Graph is the primary user object. `src/app/page.tsx` (`/`) and `/graphs` both
  render the canonical cross-location graph browser after authentication.
- `/workspaces` is the secondary **Teams & access** administration surface.
  A personal workspace is presented as **My graphs**; a shared workspace is
  presented by its Team name. Do not expose slugs, roles, capabilities, or user
  UUIDs on graph-authoring surfaces.
- `/workspaces/{slug}` remains the location administration overview and
  `/workspaces/{slug}/graphs/{id}` remains the workspace-scoped workbench route.
  These routes preserve tenancy but are not the primary discovery hierarchy.

## Shared components and call sites

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

## CSS

- Global classes use the `.grafy-` prefix with BEM-ish structure:
  `.grafy-workspace-rail__item`, `.grafy-home__section-header`, etc.
- Shared shell and route styles live in `src/app/globals.css`; complex feature
  components may keep component-scoped styles in their `.tsx` file with StyleX.
  Do not split one layout contract between global CSS, StyleX, and inline styles.
- Light/dark theming uses `light-dark()` — do not use raw hex literals for
  component styling.
- `--grafy-rail-width` is the single source of truth for sidebar width. Main
  content padding must reference it via `calc(var(--grafy-rail-width, 200px) + …)`.

## Tests

- `@testing-library/react` is **not** installed. Tests use
  `renderToStaticMarkup`, import pure functions directly, or mount interaction
  tests with `react-dom/client` and `act`.
- Test files need `.tsx` extension when they contain JSX.
- `npm test` runs the Vitest suite (`vitest run`).

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
