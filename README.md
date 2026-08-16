# Grafy Workbench

Grafy is a node-first workbench for building and running typed artifact
graphs. Nodes declare typed ports, while edges may select schema-derived or
explicit fields from compound artifacts or apply an ordered path of declared,
versioned artifact conversions before a downstream node executes.

Each edge declares how its value is transported. `direct` passes a compatible
value with its collection shape unchanged; `map` connects a sequence to one
item input, invokes the target once per item, broadcasts its other inputs, and
returns ordered output sequences. The runtime derives invocation from those
edges, so mapping is explicit workflow structure rather than hidden node state.

Field projection and artifact conversion are distinct compatibility primitives.
Nested JSON Schema `string` and `integer` leaves are automatically exposed as
the installed canonical scalar artifact types. Structural projection remains a
runtime capability for compound artifact types supplied by plugins; its
behavioral coverage uses a test/plugin compound type rather than a production
tutorial node. A declared conversion can then materialize a projected integer
as `scalar.text@1`. If the registry declares `X -> Y` and `Y -> Z`, the
workbench can persist and execute the exact `X -> Y -> Z` path on one edge.
These choices remain visible without adding boilerplate adapter nodes.
Configurable or domain-significant transformations remain nodes.

## Architecture

```mermaid
flowchart LR
    Agents["Codex and other MCP clients"] --> MCP["FastMCP graph tools"]
    MCP --> API["FastAPI workbench API"]
    Web["Next.js workbench"] --> API
    API --> Core["Typed artifact-graph runtime"]
    API --> Persistence["SQLAlchemy repositories + UoW"]
    AgentWorker["Durable coding-agent worker + generated-node executor"] --> Persistence
    Persistence --> SQL["SQLite or PostgreSQL"]
    SQL --> Graphs["Saved graph documents"]
    SQL --> Bindings["Revision-scoped output bindings"]
    SQL --> Cache["Content-addressed invocation cache"]
    SQL --> Secrets["Encrypted graph/node secrets"]
    API --> Storage["Local or S3 artifact object storage"]
    AgentWorker --> Storage
    API -->|"HMAC-signed generated-node execution"| AgentWorker
    AgentWorker --> Sandboxes["Isolated sandbox workspaces"]
    API -. "discovers entry points" .-> Plugins["Installed node plugins"]
    Plugins --> Core
```

- `apps/web` owns the canvas, node rendering, schema-driven controls, and edge
  projection/conversion/mapping editor.
- `apps/mcp` owns the mountable FastMCP Streamable HTTP tools for agent graph
  discovery and collaboration-aware authoring. The API mounts it at `/mcp` and
  injects request-scoped PAT actor context; the package does not import
  FastAPI routes, persistence, storage, or plugin implementations.
- `apps/api` owns plugin discovery, runtime composition, and the HTTP adapters
  for execution and saved-graph CRUD under `/v1`.
- `apps/agent-worker` owns the durable coding-agent loop and the private,
  HMAC-authenticated generated-node execution endpoint. The verified prototype
  uses the explicitly enabled trusted-development Docker adapter. A managed
  Daytona adapter exists, but remains provisional until its whole-sandbox
  revocation and snapshot behavior pass a live provider acceptance test.
- `libs/agent` owns the provider-independent authoring tools, coding-agent
  contracts, source verification, and sandbox boundary.
- `libs/core/src/grafy_core` owns artifacts, nodes, ports, projections,
  conversions, runtime execution, saved-graph aggregates and use cases, the
  plugin contract, and the generic Image, Sequence, Arithmetic, Text, Schema,
  Prompt, and Table built-in operator families.
- `libs/persistence` owns the async SQLAlchemy repository and unit-of-work
  adapters for saved graphs and graph materialization bindings. Alembic is the
  only schema authority.
- `libs/storage` owns the local and S3-compatible object stores.
- `plugins/ocr` is an independently packaged example plugin. It owns OCR and
  table-extraction nodes, their artifacts and persistence/resolution, the
  server-side Mistral adapter, and its Mistral SDK dependency.
- `plugins/gis` owns exact WGS84 vector sources, georeferenced raster scans,
  OGC WFS/WMS integration, lightweight map-layer recipes, and ordered map
  composition. MapLibre renders derived PMTiles and XYZ projections without
  downloading complete source artifacts into the browser.
- `plugins/llm` owns provider-backed generation. Its generic OpenAI-compatible
  Chat Completions node wraps the official OpenAI Python SDK, consumes built-in
  prompt messages and an optional runtime JSON Schema, and keeps credentials
  outside core.
  The older Mistral-specific structured node remains available for existing
  graphs.
- `plugins/sql` owns engine-neutral parameterized statement artifacts, the
  existing atomic PostgreSQL batch executor, and an isolated DuckDB executor
  for joining materialized `table.data@1` artifacts. PostgreSQL connection
  identity is node configuration, while its password remains in encrypted
  node-secret storage.
- `CONTEXT.md` defines the product vocabulary and active scope.
- `docs/workbench-interaction-plan.md` records the current interaction decisions,
  their rationale, acceptance criteria, and deliberately deferred work.

There is intentionally no legacy extraction pipeline, Dagster deployment,
message broker, generic job platform, or platform API in this workspace.

Saved graph documents contain workflow structure and canvas layout, not run
state. Successful outputs are recorded separately as durable materialization
bindings. A "latest" output is therefore exact: it is the binding for one graph
id, graph revision, node id, and output port, and it is reusable only while all
referenced artifacts are accessible to the active runtime. A default selected
run reuses those bindings without executing unselected sources. If a required
binding is missing, the workbench blocks the run and offers running the upstream
node or **Run with dependencies**; that separate action executes the selection's
full upstream closure.

Execution reuse is a separate concern from those revision-scoped bindings.
Nodes default to `never` caching; deterministic built-ins opt into the `exact`
policy explicitly. An exact invocation key covers the operator version,
validated configuration (including defaults), stable node/module identity,
invocation mode and mapped item index, resolved artifact-type bindings, exact
ordered input refs and SHA-256 values, and opaque secret revisions. Mapped nodes
cache each item independently, so a failed or newly added item does not force
already completed items to execute again. Provider, OCR, upload, and graph-module
wrapper nodes remain uncached unless their own declaration can supply every
required stable identity. Cache entries store only the final digest and artifact
refs; stale or inaccessible refs are evicted lazily.

## Register a plugin

Plugins are ordinary Python distributions that export one
`grafy_core.plugins.Plugin` declaration through the `grafy.plugins`
entry-point group:

```toml
[project.entry-points."grafy.plugins"]
my_plugin = "my_package.plugin:PLUGIN"
```

Install the distribution in the API environment and restart the API. FastAPI's
lifespan discovers installed entries, validates collisions, freezes the catalog,
and exposes the contributed nodes, artifact types, and active conversions
  through `/v1/nodes`. The host marks explicitly installed Image, Sequence,
  Arithmetic, Text, Schema, Prompt, and Table families as `builtin`, and marks
  entry-point plugins as `external`; plugins cannot self-assign that origin. The
  node catalog exposes and visually separates those origins. Sequence provides
  generic Collect, Count, Slice, and Pick item operations; Arithmetic works
  directly with canonical integer scalars. Table owns the producer-neutral table
  artifact and conversion nodes used by SQL and OCR outputs. Schema provides one
  recursive, interactive JSON Schema Builder; Prompt provides the deterministic
  message constructor used by provider plugins. The OCR and LLM packages
contribute optional external nodes, while the API package has no OCR, LLM, or
Mistral dependency. Installing a plugin also installs the third-party
dependencies declared by that plugin.

### Query artifact tables

The SQL plugin keeps statement authoring separate from execution. Connect one
or more **Raw SQL statement** nodes and one or more named table-artifact inputs
to **Query artifact tables**. Relation names are stable node configuration, so
renaming or reordering a relation does not discard its graph connection.

```mermaid
flowchart LR
    CSV["CSV or table-producing node"] -->|"table.data@1 as parcels"| Query["Query artifact tables"]
    Remote["Remote query result"] -->|"table.data@1 as owners"| Query
    SQL1["Raw SQL statement 1"] --> Query
    SQL2["Raw SQL statement 2"] --> Query
    Query -->|"ordered table.data@1 sequence"| Downstream["GIS, export, or another query"]
```

Every statement artifact must contain exactly one read-only query. All queries
see the same immutable relation snapshot and produce one ordered table output;
the node returns no outputs when any query fails. Canonical `:name` parameters
remain reusable by both executors—the DuckDB adapter translates them to native
bindings without interpolating values into SQL.

DuckDB runs in a fresh subprocess with bounded input/output, rows, wall time,
CPU, file descriptors, and spill space, plus a DuckDB engine memory limit.
External files, replacement scans, extension installation/loading, and
configuration changes are disabled.
DuckDB configuration is defense in depth rather than a complete operating-
system sandbox; production deployments should additionally run the job worker
in a networkless, least-privileged container or VM with no application data or
credential mounts.

### Report live node progress

Nodes may publish short, user-visible progress messages through their execution
context. The managed execution API streams those messages from
`GET /v1/executions/{execution_id}/events`, and the workbench displays them on
the node that emitted them. Messages from a graph module's child nodes are
grouped under that module instance.

```python
async def run(
    self,
    context: NodeExecutionContext,
    config: ImportConfig,
    inputs: ImportInput,
) -> ImportOutput:
    await context.progress("Preparing the payload")
    await context.progress("Uploading records", current=40, total=100)
    ...
```

Function nodes may opt into the same context by declaring
`(context, config, inputs)` instead of `(config, inputs)`. Progress is ephemeral
and bounded: it is not saved in execution history or graph documents, and a
missing subscriber never blocks or fails node execution. Messages must remain
short status text; do not include credentials, secrets, full inputs, payloads,
or one-time URLs. The JSON execution endpoint remains the source of truth for
the terminal result.

## Run locally

Requirements:

- Python 3.12.9
- [uv](https://docs.astral.sh/uv/)
- [just](https://github.com/casey/just)
- Node.js 20+ and npm
- For the optional GIS plugin: GDAL 3.8+ with writable PMTiles, COG, and PNG
  drivers, plus `gdal2tiles.py`. The API plugins container includes these tools.

Install both workspaces:

```bash
just install
```

The default installation contains the API, MCP adapter, core, persistence,
storage, and web application; it does not install OCR or Mistral. Enable the
optional OCR plugin with:

```bash
just install-ocr
```

Enable the optional LLM plugin with:

```bash
just install-llm
```

Enable the optional GIS plugin with:

```bash
just install-gis
```

Install every optional plugin together with the default workspaces using:

```bash
just install-all
```

Start the API and web app in separate terminals:

```bash
just api
just web
```

Generated-node authoring additionally needs the long-running agent worker. For
local development, copy the commented generated-node settings from
`.env.example`, set the API and worker HMAC variables to the same independently
generated value, configure OpenRouter, and explicitly enable the trusted Docker
adapter. Then start a third terminal:

```bash
just agent-worker
```

The API connects to the worker on `http://127.0.0.1:8091`; generated code and
dependency commands run in isolated containers, not in FastAPI. The Docker
adapter is for a trusted local Docker daemon only. The checked production
Compose deployment does not enable agent authoring yet.

For a VPS deployment behind an existing Nginx instance, use the production
[Docker Compose guide](infra/docker/README.md). The Compose services publish
only loopback-bound ports, run migrations before the API, and keep the database
and local artifact objects in one durable volume.

On a configured production host, deploy the checked-out branch and wait for
healthy services with:

```bash
just deploy
```

Use `just status`, `just logs`, and `just minio-status` for routine operations.
The production recipes read `/etc/grafy/grafy.env` and merge
`/etc/grafy/storage.override.yaml`; override those paths with
`GRAFY_ENV_FILE` and `GRAFY_COMPOSE_OVERRIDE` when required.

### Upgrade an existing Notarius checkout

The Grafy release uses `GRAFY_*` environment variables. Rename every
`NOTARIUS_*` key before starting the new code; unprefixed provider variables
such as `PREFECT_API_URL` and `MISTRAL_API_KEY` do not change.

External plugins must also move their dependency and import names to
`grafy-core` and `grafy_core`, then publish through the `grafy.plugins`
entry-point group. The old Python package and plugin-entry-point namespaces are
not retained as aliases.

Local defaults reuse `.notarius-artifacts/workbench` and its
`notarius.sqlite3` database only when the corresponding Grafy workspace or
database does not exist. New installations write `.grafy-artifacts/workbench`
and `grafy.sqlite3`. Legacy chunked table and JSON-collection manifests remain
readable; new manifests use the `grafy.*` storage-format identifiers.

For an existing Compose deployment, point `GRAFY_DATA_VOLUME` at the exact old
Docker volume name and keep the existing SQLite filename in
`GRAFY_DOCKER_DATABASE_URL` for the first Grafy deployment. Inspect the names
before starting anything:

```bash
docker volume ls
# Examples from the former local and production project names:
GRAFY_DATA_VOLUME=notarius_notarius-data
GRAFY_DATA_VOLUME=graphy_notarius-data
GRAFY_DOCKER_DATABASE_URL=sqlite+aiosqlite:////data/workbench/notarius.sqlite3
```

After Grafy is healthy against the existing data, volume and database files
may be renamed during a separately backed-up maintenance window. Do not let
Compose create an empty `grafy-data` volume and mistake it for a successful
migration.

### Assemble graphs through MCP

The local FastMCP server exposes six deliberately narrow tools over the public
Grafy HTTP API:

- `search_nodes` searches the live node catalog without returning every large
  schema.
- `inspect_node` returns the complete schema and port contract for one exact
  operator id and version.
- `list_graphs` and `get_live_head` inspect the catalog and collaborative head.
- `submit_graph_command` applies one semantic collaboration command.
- `create_graph` bootstraps a new graph at sequence 1.
- `replace_graph` performs collaboration-aware epoch reset of a checkpointed
  head.

MCP is mounted on the API at `/mcp` (stateless Streamable HTTP). Create a
workspace-bound personal access token in the browser, then point an MCP client
at `http://127.0.0.1:8000/mcp` (or the gateway `/mcp`) with
`Authorization: Bearer <token>`. Workspace identity comes from the PAT and is
not a tool argument.

The repository includes `.codex/config.toml` for an HTTP MCP client once a PAT
is available:

```toml
[mcp_servers.grafy]
url = "http://127.0.0.1:8000/mcp"
default_tools_approval_mode = "auto"
startup_timeout_sec = 30
tool_timeout_sec = 60

[mcp_servers.grafy.tools.create_graph]
approval_mode = "prompt"

[mcp_servers.grafy.tools.replace_graph]
approval_mode = "prompt"

[mcp_servers.grafy.tools.submit_graph_command]
approval_mode = "prompt"
```

Supply the PAT through the client's Authorization configuration for that
server. Read tools run directly; mutating tools keep explicit prompt policies.

`just api` applies pending Alembic migrations before starting FastAPI. Saved
graphs, artifact metadata, and materialization bindings are stored in SQLite at
`.grafy-artifacts/workbench/grafy.sqlite3` by default, together with exact
invocation-cache entries. Override
`GRAFY_DATABASE_URL` with another SQLite URL or a
`postgresql+asyncpg://...` URL for PostgreSQL. Useful
migration commands are `just db-current`, `just db-history`, and
`just db-revision "describe change"`.

After a default installation, `just api-ocr` installs the OCR extra and starts
the API in one command. Use `just api-ocr` whenever that plugin should be
available; `just api` keeps the API environment on its minimal package graph.
Use `just api-llm` for the OpenAI-compatible and Mistral LLM nodes.
Use `just api-gis` to discover the spatial import, layer, and map-composition
nodes.

### Compose vector and raster maps

The GIS workflow separates exact data from rendering instructions:

```mermaid
flowchart LR
  SQL["SQL table with WKT"] --> F["Table to geo features"]
  WFS["Import OGC WFS"] --> F2["Exact feature collection"]
  TIFF["Import GeoTIFF"] --> R["Exact raster scan"]
  F --> VL["Vector map layer"]
  F2 --> VL2["Vector map layer"]
  R --> RL["Raster map layer"]
  WMS["Remote WMS map layer"] --> C["Collect map layers"]
  VL --> C
  VL2 --> C
  RL --> C
  C --> M["Compose map"]
```

`geo.feature_collection@1` is the exact WGS84 vector source. Its stored JSON
chunks remain authoritative; a PMTiles archive is generated only as a browser
projection. `geo.raster_scan@1` is a canonical Cloud Optimized GeoTIFF, with a
derived XYZ pyramid for browser rendering. `geo.map_layer@1` references one
source and owns its style, visibility, opacity, attribution, and zoom range.
`geo.map_document@1` contains only an ordered list of layer references, a
basemap choice, and optional initial bounds.

For database WKT, configure **Table to geo features** with the geometry column
and its actual source CRS; the node reprojects supported point, line, polygon,
multi-geometry, and geometry-collection values to exact EPSG:4326 features.
Create a **Vector map layer** for each vector source and a **Raster map layer**
for each GeoTIFF. Collect the `geo.map_layer@1` outputs in drawing order, then
connect the ordered sequence to **Compose map**. The preview loads only after an
explicit click and exposes local order, visibility, opacity, zoom, vector style,
label, and raster image controls.

External GeoServer-compatible services follow the same model. **Import OGC
WFS features** takes a bounded snapshot into an exact feature artifact. **Remote
WMS map layer** keeps the remote raster live and proxies only requested image
tiles. For Atlas Fontium, use
`https://data.atlasfontium.pl/geoserver/ows`; example layer names include
`geonode:powiaty`, `geonode:miejscowosci`, and historical raster layers exposed
by its capabilities document. Service URLs must be public and credential-free,
and WMS layers require explicit bounds and attribution.

This is a clean-break development contract: rerun old GIS nodes to create the
new source projections and reference-only map artifacts. The API intentionally
does not reconstruct or page legacy embedded map documents.

Open <http://localhost:3000>. The API is available at
<http://localhost:8000>; its health endpoint is `/health`.

The workbench defaults to local artifact storage and a local API URL. Set
`GRAFY_STORAGE_BACKEND=s3` plus the S3 settings shown in `.env.example` for
AWS S3 or an S3-compatible service such as MinIO. `MISTRAL_API_KEY` is required
by Mistral OCR and structured-output nodes and must remain server-side.

The OpenAI-compatible node uses a write-only key configured on a saved node,
not an environment-specific provider variable. Generate one stable encryption
key for the Grafy server and put it in `.env` before configuring node keys:

```bash
openssl rand -base64 32
```

Assign the result to `GRAFY_CREDENTIAL_ENCRYPTION_KEY`. Keep that value
stable and backed up: replacing or losing it makes existing encrypted node
keys unusable. Graph documents, run requests, artifact payloads, and read APIs
never contain provider keys. Stored ciphertext is bound to graph id, node id,
operator version, secret name, and the normalized `base_url`; changing the URL
deletes the old binding and requires explicitly applying a key for the new
endpoint. Removing a node likewise deletes its encrypted node secrets, so
reusing the node id cannot reactivate an old credential.

### Try OpenAI-compatible generation

Build one provider-neutral prompt graph, then connect it to the generic external
LLM node:

```mermaid
flowchart LR
  SText["Text: system instructions"] --> SMessage["Prompt message: system"]
  UText["Text: user request"] --> UMessage["Prompt message: user"]
  Images["Image sequence (optional)"] --> UMessage
  SMessage --> Collect["Collect prompt messages"]
  UMessage --> Collect
  Child["Child Schema Builder"] -->|"object field / sequence items"| Schema["Schema Builder"]
  Schema -. "json.schema@1 (optional)" .-> LLM["OpenAI-compatible Chat Completion"]
  Collect --> LLM
```

Add the system message to Collect before the user message. Keep the Collect to
LLM edge in `direct` mode so the LLM receives the ordered conversation once;
`map` would invoke it independently for every message. Configure the node's
base URL, model, generation limits, and write-only API key after saving the
graph. The default endpoint is OpenAI, while the same node can target an
OpenAI-compatible LiteLLM or OpenRouter base URL. Remote endpoints must use
HTTPS; plain HTTP is accepted only for localhost and loopback development.

Connect Schema Builder only when structured output is needed. It emits Draft
2020-12 JSON text with an object root. Add primitive fields inside the node;
choose Schema, or Sequence with Schema items, to expose a field-owned input
socket for another builder. The request uses Chat Completions `json_schema`
response format and Grafy validates the returned object locally. For
example:

```json
{
  "type": "object",
  "required": ["title"],
  "properties": {
    "title": { "type": "string" }
  },
  "additionalProperties": false
}
```

The OpenAI-compatible and Mistral adapters accept PNG, JPEG, GIF, and WebP image
artifacts on user messages. They bound one request to eight images, 20,000,000
bytes per image, and 50,000,000 image bytes in aggregate before base64 encoding.

Node secrets currently use trusted-collaboration semantics. Any visitor who can
access a graph can run it without retrieving the configured key. Because this
repository does not yet have authentication or graph roles, those visitors can
also replace or remove the key through the API. Put the Grafy API behind
HTTPS and an access-controlled boundary before exposing it to untrusted users.

## Verify

Run the full retained contract:

```bash
just check
```

The check runs backend tests, Python and TypeScript lint/type checks, verifies
that the generated OpenAPI client is current, and builds the production web
bundle. It enables the OCR and LLM extras while running Python tests and type
checks so the external plugins remain covered without becoming default runtime
dependencies.

To exercise the runtime without the browser:

```bash
just smoke
```

## Containers

The API Dockerfile's default `api` target contains no OCR, LLM, or Mistral
dependency. The Compose stack explicitly selects its `api-plugins` target so the
optional OCR and structured-output nodes are available in that deployment. A
one-shot migration service must complete before the API starts. SQLite, uploads,
and artifact objects share the durable `grafy-data` volume.

```bash
just docker-up
just docker-down
```
