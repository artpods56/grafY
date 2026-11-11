# Grafy Workbench

A ComfyUI-like workbench for assembling typed artifact transformations over the
Grafy runtime. It is built with Next.js 16, StyleX, Base UI
primitives, React Flow, and SWR.

Node configuration is rendered directly inside each node from the live
`config_schema`. Primitive JSON Schema fields use a compact preset: text,
number/integer (including bounds), boolean, or enum selection. Uploaded images and
run artifacts are also managed from the node, so the canvas does not depend on
a separate inspector sidebar. Drag Library artifacts or a materialized output
port onto the canvas to render artifacts as cards. The standalone Artifact
Viewer is deprecated; existing saved viewers continue to work, but the toolbar
and canvas menu no longer create them. The node header keeps only two local
controls: help from the registered description and removal from the canvas.

Selecting an operator previews its description, compatible upstream and
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
3. The Grafy API running on `http://127.0.0.1:8000` (the Next.js dev
   server proxies browser `/api` requests to it).

```bash
cd apps/web
npm ci
npm run dev
```

Open <http://localhost:3000>.

The API key stays on the server. It is never stored in node configuration or
sent to the browser.

## Run the end-to-end pilot

See [how to run e2e](../../docs/how-to-run-e2e.md) for the single real-backend flow.

## Browser-local preferences

The frontend uses `localStorage` only for device-local presentation settings:
theme, workspace-rail collapse, and canvas-grid behavior. Workspace selection,
graph documents, collaboration state, sessions, and authorization remain
server-owned. Grafy does not use `sessionStorage` or IndexedDB.

## Verification

```bash
npm run check:api
npm test
npm run lint
npm run typecheck
npm run build
```
