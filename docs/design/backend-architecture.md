# Backend architecture reference

This reference describes current source ownership. Product vocabulary lives in
[CONTEXT.md](../../CONTEXT.md), and architectural decisions live in
[docs/adr](../adr/). In particular, [ADR 0007](../adr/0007-builtin-families-are-application-code.md)
supersedes the historical host-eligible Plugin execution model.

## Packages and dependency direction

| Owner | Responsibility |
| --- | --- |
| `apps/api/src/grafy_api` | HTTP and room transport, application composition, graph execution, and the catalog of operators this build registers. |
| `apps/mcp/src/grafy_mcp` | MCP tools through an injected graph-workspace operations contract. |
| `libs/core/src/grafy_core` | Domain models, application workflows, ports, node runtime, artifact contracts, portable cache and storage readers. |
| `libs/persistence/src/grafy_persistence` | SQL repositories, transaction adapters, table metadata, database setup, and baseline persistence operations. |
| `libs/storage/src/grafy_storage` | Local and S3 object-store adapters. |
| `libs/workbench/src/grafy_workbench` | Application-owned builtin families: image, sequence, value, text, schema, table, and file. |
| `plugins/{gis,image,llm,mistral,sql,table,typesafe}` | Node families with their own packages and provider dependencies, installed into the API process and registered by `apps/api/src/grafy_api/services/families.py`. |
| `libs/client/src/grafy_client` | Python HTTP client contracts and operations. |

Core defines ports; persistence and storage implement them. Core does not import
those concrete adapters, API, FastAPI, SQLAlchemy, or published Plugin packages.
API composition constructs the adapters. Published Plugins do not import each
other or host application implementations.

```mermaid
flowchart LR
    API[API composition and workflows] --> Core[Core domain and ports]
    API --> Persistence[SQL persistence]
    API --> Storage[Object storage]
    Persistence --> Core
    Storage --> Core
    Plugins[Published Plugin code] --> Core
```

These arrows denote imports, not the order of runtime calls. A core workflow can
call a port implemented by persistence without importing persistence.

## Composition and lifecycle

`grafy_api.main.create_app` registers transport and configures lifespan. Lifespan
loads `BuiltinNodeCatalog` using the deployment build digest, selects storage
through `grafy_api.storage.configured_file_storage`, constructs domain services,
and optionally starts the Docker Plugin runtime.

`services/composition.py` builds `WorkbenchComponents`, including compilation,
execution, artifact reads, catalog, and runtime dependencies. `AppResources`
retains that bundle rather than copying its fields. `AppIdentity` owns the
identity and authentication services. Request dependencies retrieve these typed
resources; domain services receive their dependencies directly.

Shutdown closes the graph-room hub, execution manager, optional Plugin runtime,
and artifact HTTP client in that order. The API's owner lease and database
lifecycle remain in `main.py`. In-memory room coordination requires the configured
single API owner; multiple workers are not an interchangeable deployment mode.

## HTTP, authentication, and collaboration

`v1/routes/<feature>/views.py` owns request handling and HTTP error translation.
Route-local models describe transport. Route files need not contain application
services merely to satisfy a directory pattern.

Authentication's cookie, OIDC, PAT, and abuse-handling code remains under
`v1/routes/auth`. Workspace transport models belong to `v1/routes/workspaces`. Core
identity policy and transaction-local workspace authorization live in
`grafy_core.application.identity`.
Graph workflows authorize through that shared policy, including ordered checks
for cross-workspace copies.

Core `CollaborationService` owns head commands and checkpoints. Shared
`application/graph_creation.py` stages the saved graph, revision, head, and initial
checkpoint for creation workflows. Saved graphs and Modules retain their own
workflows and identities.

`grafy_api.realtime` owns the room hub and post-commit publishing. The publisher
receives its dependencies instead of finding request resources. HTTP/WebSocket
adapters remain under collaboration routes.

`graph_contracts.py` owns graph transport. `CollaborativeHeadResponse` is the one
head shape: collaboration metadata (room epoch, collaboration sequence, checkpoint
sequence and checkpoint revision) paired with the canonical `SavedGraphDocument`.
`GET /v1/workspaces/{workspace_id}/graphs/{graph_id}/head/document`, the command and
checkpoint responses, and the room frames in `grafy_api.realtime.protocol` all carry
that shape, so no client normalisation step sits between the server and the canvas.
There is no flattened head, no `plugin_release` alias, and no per-node release pin:
the canonical node field names an operator, not a release. Shared layout and
edge-conversion rules live beside the canonical models.

## MCP

API-owned `mcp/mount.py` authenticates workspace-bound PAT requests and binds a
request-scoped caller. `mcp/operations.py` implements the operations interface
used by the independent MCP package. MCP does not import API routes, persistence,
object storage, or Plugin implementations. Token scope and current workspace
membership both constrain access.

## Node families and the catalog

Every operator in this build is application code loaded in-process (ADR 0017). A family
is either a builtin under `libs/workbench` or a package under `plugins/`; both are
installed into the API environment and registered into one static
`grafy_core.plugins.PluginRegistry`, and a node identifies by family slug plus the
deployment build digest. There is no release pin, no installation, no selection and no
revocation to consult: a family that is not in `services/families.py` has no nodes, no
artifact types and no catalog entry.

The publication and isolated-hosting modules that used to sit under
`apps/api/src/grafy_api/plugins`, the guest protocol under `grafy_core.runtime`, and the
standalone egress broker are removed. Nothing reads a retired shape: a stored
document is parsed at its own schema version only, and a node whose stored `kind` is
neither `builtin`, `module` nor `call` fails validation instead of being rewritten.

`grafy_api.catalog.CatalogSnapshot` owns catalog assembly from the installed family
declarations and Module library results. An entry is what this build registered,
so it carries no release identity and no readiness decision: a family that was
not installed has no entry at all. The upload extension table is built from the
same artifact declarations and refuses two owners for one extension.
`PluginRegistry` retains immutable family declarations and lookup indexes.
Canonical artifact conversions remain deployment-owned in core.

## Graph execution

`grafy_api.execution` owns preparation, compilation, scheduling, cancellation,
queue lifecycle, history, materialization, and node execution. HTTP endpoints and
`RunResultPresenter` remain under execution routes. The route model module declares only
this build's transport models: durable requests and events come from their owning
modules, with no re-exported aliases. See the
[execution ownership reference](../../apps/api/src/grafy_api/execution/README.md).

Preflight resolves each node's contract and secret requirements once, and the
compiler reuses that preparation. Saved-graph and nested-Module paths share request
conversions while selecting their own topology.

`GraphExecutionCoordinator` schedules graph work; `NodeExecutionService` executes
nodes; core `NodeRuntime` owns node-level materialization, invocation, and output
persistence. These are different responsibilities. Edge projection reads artifact
rows through the core artifact unit-of-work port, then preserves exact-reference
checks, projection, conversion order, and provenance. It does not use the HTTP
artifact reader.

```mermaid
flowchart LR
    Request[Run request] --> Prepare[Preflight and compiler]
    Prepare --> Coordinator[Graph coordinator]
    Coordinator --> Node[Node execution]
    Node --> Builtin[Builtin family in the API process]
    Node --> Plugin[Plugin package in the API process]
```

The core persistent invocation-cache adapter shares cache semantics with the node
runtime. Queued recovery depends on stable request serialization. MAP ordering,
cancellation, nested execution, and materialization each have behavioral tests.
The startup recovery fence covers both durable queue rows and transient activity
markers. Transient activity is registered before preparation and removed after task
cleanup. Startup only clears stale markers when it holds the exclusive API owner lease;
otherwise it retains them and refuses startup. Startup recovery has lifespan tests;
background and synchronous execution races have SQLite and PostgreSQL coverage.
Synchronous routes use manager-owned activity while retaining HTTP capacity through
presentation. Saved runs also register activity before preparation, so
marking saved history interrupted cannot bypass recovery authority.

## Artifact contracts, reads, and infrastructure

`grafy_api.artifact_availability` resolves exact references and batches storage
presence checks for application workflows. Each operation loads fresh state.
Availability is weaker than cache content-integrity validation; do not substitute
one for the other. HTTP summaries, content responses, GIS tile/render handling,
and the WMS client remain in the artifact transport service.

Core owns producer-neutral stored contracts, including spatial payloads, styles,
map references, and feature metadata. GIS public aliases reuse those contracts.
API models retain explicit compatibility differences where required response
fields or historical reader acceptance differ from producer validation. GDAL,
provider calls, and raw raster upload inputs remain in GIS.

Core `spatial_storage` shares feature-page reconstruction and canonical byte/hash
validation. `stored_models` shares typed stored-model reads. Format-specific table
and collection readers retain their own manifest/chunk semantics.

`grafy_api.node_secrets` and `staged_uploads` own their application workflows.
Storage adapters only implement object IO. Sensitive capabilities and secret
resolution must remain explicit at those workflow boundaries.

## Persistence and deployment

`grafy_persistence.adapters.repositories` and `grafy_persistence.schema` are
packages grouped into identity, graphs, artifacts, execution, uploads, and library.
`schema/base.py` owns shared metadata; the schema package loads the tables, and
`orm.py` maps them. `column_types.py` owns shared Pydantic/enum SQL conversion.
Alembic revisions under `infra/db/migrations` govern deployed schema changes. The
history is one baseline revision for the current schema and its downgrade drops
that schema.

Transaction adapters open task-local sessions and expose the repositories required
by each port. Writes commit explicitly. Context exit rolls back on error and
closes the session; it does not implicitly commit success. Core in-memory runtime
adapters preserve task isolation, cloning, and rollback for supported local use.

Docker definitions under `infra/docker` compose the gateway, API, web, and optional
PostgreSQL, Keycloak, and Plugin runtime services. Local and S3 object stores are
alternative adapters. Plugin egress has its own executable and Docker definition;
it does not require importing the API application.

## Enforcement and verification

`tests/unit/architecture/test_import_boundaries.py` enforces package dependency
rules and compatibility export identity. Execution and Plugin runtime scans
resolve absolute and relative Python imports, forbid HTTP route/framework imports
and historical host loaders, and keep Plugin hosting independent of graph
execution. Shared application owner checks cover realtime, graph contracts,
artifact availability, node secrets, and staged uploads. Static checks do not
claim to sandbox arbitrary dynamic imports.

Behavior lives in `tests/unit/api`, `tests/unit/core`, `tests/unit/client`, and the
feature suites under `tests/integration`. Frontend tests are colocated with their
TypeScript consumers. Schema comparison, generated client consistency, and
extracted-wheel checks protect contracts that directory checks cannot prove.
