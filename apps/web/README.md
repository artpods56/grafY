# Grafy Workbench

A ComfyUI-like workbench for assembling typed artifact transformations over the
Grafy runtime. It is built with Next.js 16, StyleX, Base UI
primitives, React Flow, and SWR.

The root route renders the canonical cross-location graph browser after
authentication. New and saved workflows open at their workspace-scoped graph
URLs. The built-in catalog is limited to generic Image, Sequence,
Arithmetic, Text, and Prompt families. OCR and table extraction appear as
external nodes only when the OCR entry-point plugin is installed.

Node configuration is rendered directly inside each node from the live
`config_schema`. Primitive JSON Schema fields use a compact preset: text,
number/integer (including bounds), boolean, or enum selection. Uploaded images and
run artifacts are also managed from the node, so the canvas does not depend on
a separate inspector sidebar. The node header keeps only two local controls:
help from the registered description and removal from the canvas.

The node catalog separates host-assigned built-in families from registered
external plugins and marks external entries. A plugin cannot choose its own
origin. Selecting an operator previews its description, compatible upstream and
downstream nodes, typed input and output ports, and editable configuration
fields before the user adds it to the canvas. Compatibility is derived from the
same artifact types, field projections, bounded conversion paths, and collection
shapes used for live wiring. The Sequence family provides generic `Collect<T>`,
Count, Slice, and Pick item operations; there are no image- or text-specific
collector entries.

Connections own transport behavior. Every edge has an inline control for
choosing the whole output or a schema-derived/explicit nested-field projection,
reviewing its ordered conversion path, showing whether the target receives the
value directly or maps each list item, and removing the connection. Different
outgoing edges from one output can therefore carry different fields without
changing the source node.

## Source of truth

The authoritative backend contract for this app is the workbench implementation:

- `libs/core/src/grafy_core/` owns node, port, artifact, resolver,
  persistence, and runtime behavior.
- `apps/api/src/grafy_api/schemas/workbench.py` owns the HTTP models.
- `apps/api/src/grafy_api/v1/routes/workbench.py` exposes the node
  catalog and execution routes.

The web workbench depends on no routes outside this contract.

## Generated transport types

The web transport contract is generated from the canonical FastAPI app:

```bash
cd apps/web
npm run generate:api
```

This updates:

- `openapi/grafy.json`
- `src/lib/api/generated/grafy.ts`

Refresh the OpenAPI JSON and check that the committed TypeScript types are
current:

```bash
npm run check:api
```

Do not hand-edit the generated TypeScript file. `contract.ts` supplies
short application-facing aliases derived from generated operations and schemas.

The node, port, request, and response envelopes are generated from the API.
Node-specific `config_schema`, `input_schema`, `output_schema`, artifact
`payload_schema`, and run-node `config` remain dynamic JSON objects. This lets
the backend advertise new node shapes without requiring a handwritten frontend
type for every node.

## Running locally

Requirements:

1. Node 20+ and npm.
2. Python 3.12.9 with the repository uv workspace synced.
3. The Grafy API running on `http://127.0.0.1:8000` (the Next.js dev
   server proxies browser `/api` requests to it).
4. `just install-ocr` and `just api-ocr` used from the repository root when OCR
   operators should be available.

```bash
cd apps/web
npm ci
npm run dev
```

Open <http://localhost:3000>.

The API key stays on the server. It is never stored in node configuration or
sent to the browser.

The root route and `/graphs` show the authenticated user's graphs across their
personal and shared workspaces. A workbench keeps its tenancy boundary in the
canonical URL `/workspaces/{workspace_slug}/graphs/{graph_uuid}`; a blank draft
uses `/workspaces/{workspace_slug}/graphs/new`. Reopening a saved graph also
loads accessible materialized outputs for that exact graph revision. These
runtime records are separate from the saved graph's workflow structure and
canvas layout.

## Run browser interaction tests

Install the Chromium build that matches Playwright:

```bash
cd apps/web
npm exec playwright install chromium
```

Run the browser tests in headless mode:

```bash
npm run test:e2e
```

To watch the browser interactions, use headed mode:

```bash
npm run test:e2e:headed
```

The tests open the real Next.js workbench and send trusted browser input to
React Flow. They use Chromium with desktop, phone, and tablet emulation. They do
not cover a physical iOS device or Safari. `e2e/workbench.fixture.ts` replaces
the API boundary with fixed session, workspace, graph-list, invitation, and
node-registry responses. An unexpected API request fails with status 501
instead of reaching a local API process.

The canvas interaction contract differs by input type:

- In the touch projects, one finger pans on the canvas background and two
  fingers zoom from the canvas background. Neither gesture creates a React Flow
  selection rectangle.
- On desktop, a primary-button drag selects and a right-button drag pans.
- Node dragging and port connection gestures keep their existing behavior.

The suite does not cover a pinch that starts with both fingers on the same node.

The popup suite checks a 24-node catalog, search and filter retention when
returning from details, visible Add actions, Canvas lab's Advanced disclosure,
schema navigation, and dialog bounds. It also checks node insertion and port
popups in a short landscape viewport. Run it separately with:

```bash
npm run test:e2e -- e2e/workbench-popups.spec.ts
```

Playwright writes layout screenshots, failure videos and traces, and the HTML report to
`../../output/playwright/` from this directory.

## Browser-local preferences

The frontend uses `localStorage` only for device-local presentation settings:
theme, workspace-rail collapse, and canvas-grid behavior. Workspace selection,
graph documents, collaboration state, sessions, and authorization remain
server-owned. Grafy does not use `sessionStorage` or IndexedDB.

## Current flow

1. `GET /v1/nodes` returns the catalog with each plugin's host-assigned
   `builtin` or `external` origin, typed ports, JSON schemas, and artifact type
   definitions.
2. A new graph opens as an empty `Untitled workflow`; the user adds registered
   nodes from the catalog and connects their typed ports.
3. Node outputs retain their declared artifact identities and remain
   independently connectable to compatible downstream inputs.
4. Connections explicitly select direct or mapped transport behavior where the
   source and target cardinalities permit it.
5. Structural field projection remains available for compound artifacts supplied
   by plugins. The picker is populated from explicit projections and nested
   `string`/`integer` leaves derived from the artifact's JSON Schema; automated
   coverage uses a test/plugin compound type rather than a production tutorial
   node.
6. List-valued edges expose whether the target receives the whole list directly
   or maps the target operation over each item. Mapping is edge state, not node
   invocation configuration.
7. Drag-selecting nodes enables **Run selected**. By default it sends the
   selected nodes, their internal edges, and incoming edges crossing from
   unselected upstream nodes. Each crossing edge pins the exact `ArtifactRef` or
   `ArtifactRefSequence` bound to its source graph id, graph revision, node id,
   and output port; its projection and `direct`/`map` mode still apply. Only
   bindings whose references are accessible through the active runtime are
   available. The upstream source is not re-executed, and its result remains
   untouched.
8. If a required source-port binding is missing, **Run selected** is blocked
   instead of asking the server for a fuzzy "latest" artifact. The error directs
   the user to run the upstream node or choose **Run with dependencies**. That
   separate action expands the selection to its full upstream closure and
   executes every node in the expanded graph. **Run all** executes the complete
   graph.
9. Editing a node's schema-derived controls invalidates stale run results before
   the next execution.
10. `POST /v1/runs` validates the graph, collection modes, projection paths, and
    every stored conversion-path hop before executing it through the runtime.
11. Node results expose values and content URLs served by
   `GET /v1/artifacts/{artifact_id}/content`.

Live running state and selected-run pins remain transient. Successful outputs
for a saved graph are materialized separately from the graph document and are
restored by exact graph revision when the referenced artifacts remain
accessible.

## Project layout

```text
src/
  app/                         # workbench route and global styles
  components/
    canvas/                    # React Flow adapter, edge controls, and node rendering
    ui/dialog.tsx              # field-projection picker primitive
    providers.tsx              # registry SWR and theme providers
    theme.tsx                  # persisted light/dark/system preference
  hooks/use-api.ts             # node registry hook
  lib/
    api/
      generated/grafy.ts    # generated OpenAPI transport types
      contract.ts              # application-facing generated aliases
      workbench.ts             # workbench HTTP calls
    stylex/                    # design tokens
```

## Verification

```bash
npm run check:api
npm test
npm run lint
npm run typecheck
npm run build
```
