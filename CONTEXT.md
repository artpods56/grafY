# Grafy Workbench Context

## Product scope

The active product is the typed artifact-graph workbench. This repository
intentionally contains only that product slice; legacy extraction pipelines,
Dagster jobs, distributed workers, experiments, and compatibility modules are
outside its scope.

## Domain vocabulary

### Accepted identity vocabulary

These terms are product vocabulary for authentication and tenancy. They are
distinct from the filesystem/workbench data root (`Settings.workspace` /
Compose volume): that path stores runtime files; it is not a collaboration
boundary.

| Term | Meaning |
| --- | --- |
| `User` | Internal account provisioned only after a valid OIDC callback. Profile email/display name are not authorization keys and never link identities. An issuer-asserted email domain may grant membership in a configured shared Workspace. |
| `OidcIdentity` | Exact `(issuer, subject)` link from the configured OpenID Connect provider to one `User`. |
| `Workspace` | Sole collaboration and tenancy boundary. `personal` has one owner and no other members; `shared` holds `viewer` / `editor` / `owner` memberships. |
| `WorkspaceMembership` | Active or revoked role of one user in one workspace, with a monotonic authorization version. |
| `Graph` | Primary user object and post-login destination. Every graph is durably owned by exactly one Workspace even when that Workspace is presented as `My graphs` or a Team save/share location. |
| `GraphFolder` | Optional one-level organization of graphs inside exactly one Workspace. A graph with no folder is `Unfiled`; folders never nest and never widen access. |
| `GraphOrganization` | Workspace-shared graph metadata for optional folder assignment and archive lifecycle state. It is separate from the collaborative graph document and its immutable checkpoints. |
| `UserGraphState` | Per-user state for one workspace-owned graph: starred and last-opened activity. It is never shared graph state and never grants access. |
| `OidcLoginTransaction` | Short-lived, single-use Authorization Code + PKCE handshake state. |
| `AuthSession` | Opaque, revocable browser session (raw secret never persisted). |
| `PersonalAccessToken` (`PAT`) | Workspace-bound bearer credential for SDK, CLI, MCP, and other non-browser HTTP automation; effective permission is token scope ∩ current membership. |
| `PlatformAccessToken` | Deployment-issued bearer credential for global Plugin operations. It names a platform principal and grants only explicit publish, promote, or revoke scopes. |
| `SecurityAuditEvent` | Metadata-only security audit row; never stores credentials, provider payloads, or command/config bodies. |
| `GraphRoomSession` | Ephemeral WebSocket participant identity inside one `(workspace_id, graph_id)` collaboration room. |
| Capability | Fine-grained permission derived from role (and intersected with PAT scopes), such as `edit_graph`, `execute_graph`, or `join_graph_room`. |

“Team” and “organization” in conversation both mean a shared workspace. There is
no second grouping aggregate, per-graph ACL, or public-link grant in the first
delivery.

### Artifact

A typed, versioned value produced or consumed by a node. Its payload may be
inline or stored as content, but its artifact type and schema version are
always explicit.

### Artifact type

The contract for an artifact payload. It owns the stable type id, schema
version, payload schema, display title, materialized JSON shape, declared field
projections and exports, and an exact portable bundle format/version. Another
Plugin may reference the type only by carrying the same complete serialized
contract as a release dependency; a matching id/version with different
contract bytes is a collision. Versioned conversions between artifact types
are deployment-owned canonical behavior, not an asset of either endpoint's
Plugin release.

An inline artifact type also declares every field that contains persisted
artifact references, including the JSON path, target artifact type, and whether
the field contains one reference or many. Isolated execution follows only these
declared references. It stages the exact referenced artifacts as read-only
dependencies in the guest artifact store, without turning them into extra node
ports or granting access to unrelated Workspace artifacts.

An artifact type is a payload contract, so two nodes that move the same payload
share one type. A second type id for an identical contract is a catalog bug, not
a Plugin namespace: an image Plugin that declares `photos.shot@1` over the
`image.raster@1` payload cannot connect to nodes that expect a raster.
Specialized types exist only where the contract differs, as `geo.raster_scan@1`
(CRS, geotransform, bands) and `geo.map_layer@1` (a drawing recipe rather than
pixels) do. A node does not escape this by declaring a type variable: `T`
belongs to generic operations such as Collect, Slice, and Pick. The same holds
for file formats: one deployment-wide type per format, so two plugins that read
CSV share one CSV artifact type instead of each shipping their own.

### File format artifact

An artifact type whose id names a file container: `file.csv@1`, `file.geojson@1`,
`file.tiff@1`. Its contract is encoded bytes plus the declared format, never an
interpreted payload, so a `file.csv@1` artifact is not a Table artifact and a
`file.tiff@1` artifact is not a raster. The `file.` prefix is the marker for the
whole family: an id under `file.*` names a container and every other id names an
interpreted payload, so the type alone says whether anything has interpreted the
bytes yet.

Ingest is extension-driven: the deployment maps a known extension to its format
type, checks the content against it, and rejects the upload when the two
disagree. Where content cannot confirm a format, as with CSV or plain text, the
extension decides. One format can answer to several extension strings, so `.jpg`
and `.jpeg` both produce `file.jpeg@1`, and `.tif` and `.tiff` both produce
`file.tiff@1`. A plugin claims `.las` by declaring that mapping rather than by
shipping an upload node.
Interpretation is always a visible node, so `file.png@1` becomes
`image.raster@1` through a decode node and `file.csv@1` becomes `table.data@1`
through an import node whose delimiter and header choices the user can see and
change.
_Avoid_: upload artifact, source node

### Extension claim

The mapping a `file.*` artifact type declares from one extension string to
itself, carried in the artifact type contract and published with the type's
release. One extension maps to exactly one format type, so a type cannot claim an
extension the deployment already holds, and the deployment refuses the
installation that would collide. A claim states which bytes belong to the format.
Confirming those bytes is the format's own rule.
_Avoid_: file type registration, extension mapping, upload node

### File blob artifact

The format type for bytes whose extension the deployment does not recognize:
`file.blob@1`. It is the fallback member of the same family and carries the same
reading, that nothing has interpreted these bytes yet. A blob has no domain
meaning and projects no fields, and it stays the answer only until the
deployment recognizes the format.
_Avoid_: opaque file, raw file

### Artifact bundle contract

The provider-neutral wire and storage shape used to move one artifact value
across a release runtime boundary. Canonical JSON values use
`inline-json@1`; structured tables use `table-bundle@1`. A bundle format is
independent from the artifact type id, and runtime support is selected by the
exact format/version rather than a hard-coded list of type names. A release is
not runnable when any required bundle adapter is unavailable.

### Artifact reference

A lightweight reference to a persisted artifact. Graph execution moves
references between nodes and materializes Python values only at a node input.

### Upstream output pin

An exact `ArtifactRef` or `ArtifactRefSequence` copied from a materialized output
binding when a selected run begins. The incoming crossing edge remains in the
selected-subgraph request and keeps owning its projection, conversion, and
`direct`/`map` collection mode; the pin supplies that edge's source value
without executing its source node. The server consumes the submitted reference
and never performs a fuzzy "latest artifact" lookup.

### Origin

A node input satisfied by a direct reference to a Library artifact instead of by
an edge from an upstream node. An origin holds the exact `ArtifactRef` or
`ArtifactRefSequence` the user placed there, plus a declared artifact conversion
path when the artifact's type is not already one the input accepts, and it adds
no node to the saved graph; on a `many` port, several artifacts group into one
sequence. It is the same reference kind a selected-subgraph pin carries, and it
names an artifact by identity rather than searching for one. An origin and an
enabled edge never satisfy the same input, though a disabled edge may wait beside
one. An origin whose artifact can no longer be read stays in the saved document
exactly as written and leaves its input unsatisfied. An origin therefore belongs
to the Workspace that owns its artifact: copying a graph or a template into
another Workspace drops the origin and leaves that input unsatisfied, rather than
moving bytes across the tenancy boundary.
_Avoid_: source node, source operator, input node

### Materialized output binding

The durable record of a successful output for one exact saved graph revision,
node, and output port. In this workbench, **latest** means the binding identified
by `(graph id, graph revision, node id, output port)`; it never means the newest
artifact with a matching type or producer. A binding is reusable only when all
of its artifact references are accessible through the active runtime.
Inaccessible references are not advertised as available outputs.

A binding can carry forward to a new graph revision only while its node and
all upstream dependencies retain the same execution meaning. Changing a node's
execution settings or enabled inputs invalidates its outputs and those of every
downstream node reached through enabled edges. This holds even when the changed
node has no materialized output of its own. Layout-only edits preserve reusable
bindings. Invalidation leaves earlier revision bindings and execution history
available for inspection.

### Library artifact

The artifact a Workspace owns, shown in the Library drawer. There is one Library
per Workspace and every member sees it. Uploaded bytes and Run artifacts are
both eligible. A Library artifact is Workspace-owned and independent of any
graph: graphs reference it, and deleting a graph, a revision, or its execution
history never deletes it. It is a retention root in its own right, so nothing
collects it while it sits in the Library. Saving into the Library is promotion
rather than first persist, because the artifact already exists as an upload or a
materialized output binding before anyone saves it. Identity is the exact
artifact reference, so saving the same artifact twice yields one Library
artifact, and picking one never means taking the newest artifact of a matching
type. An artifact has one placement in the Library, and moving it never changes
its reference. Removing an artifact from the Library clears its placement and
leaves the row and its bytes alone. Deleting a Library artifact is refused while
any saved revision or execution history references it, and the refusal names
those graphs. A forced delete writes a new head revision for each referencing
graph, removes the origin from that graph, and leaves the input unsatisfied.
_Avoid_: kept, saved asset, staged, library item, source

### Library folder

A named folder inside the Workspace's Library, used to organize Library
artifacts. Folders nest, and a folder may be empty. A folder holds no payload,
so it is not a retention root, and deleting an empty folder leaves every
artifact and stored byte untouched. Deleting a folder that still holds artifacts
is refused. Creating, renaming, moving, or deleting a Library folder takes the
same capability as saving an artifact into the Library.
_Avoid_: directory, collection

### Run artifact

An output one run of a graph produced, shown in the Runs drawer. The Runs drawer
is per canvas, newest first, grouped by run and then by the node that made the
item, and each row names the revision it came from. Run artifacts are not a
second persist: they exist as materialized output bindings the moment their node
succeeds, which is what incremental execution, pins, and execution history read.
The drawer is a view of those bindings, so an item stays visible after its run
ends, and one reaches the Library only through an explicit save. Saving a Run
artifact into the Library adds a reference to the same identity rather than
moving or copying it, so the row stays in Runs and the artifact then appears in
both drawers.
_Avoid_: produced, generated, result

### Graph execution history

The durable, revision-scoped provenance record for one accepted asynchronous
execution of a saved graph. It records the application execution id, exact graph
revision, requested scope, ordered node closure, lifecycle timestamps and status,
provider workflow id, terminal error, and ordered per-node results with their exact
artifact output envelopes. Executions of unsaved or dirty graph documents remain
ephemeral because they do not identify a durable graph revision.

Execution identities are append-only, and each accepted node is one immutable
`graph_execution_nodes` row with a monotonic lifecycle: requested (stable
request-order position, no terminal result) then terminal (result recorded
exactly once, carrying its own result position, outputs, artifact count,
error, and completion timestamp). Nodes that never reach a terminal result
keep their requested rows. Lifecycle fields on the execution row advance from
queued/running (or cancelling) to one terminal state; a partial unique index
on `(workspace_id, graph_id)` over the queued/running/cancelling statuses makes
`graph_executions.status` the sole authority for one-active-execution per
Workspace-owned Graph, and terminal transitions release that constraint.
History is not the source used for incremental execution:
`materialized_node_outputs` remains the mutable latest-successful-output
projection used for pins, while history preserves every accepted execution across
repeated runs and graph revisions. Historical inspection must never hydrate the
canvas's current run state or make an old artifact eligible as a latest pin.

Artifacts referenced by execution history are retention roots alongside current
materializations and invocation-cache entries. Startup recovery currently marks
unfinished executions as failed and assumes one owning API process; horizontal
workers require an execution lease or heartbeat before they can safely share that
recovery policy.

### Live execution event

A transient, user-visible observation emitted while one managed graph execution
is active. The owning API process assigns every event a monotonic execution-local
sequence and retains a bounded replay window so a browser can subscribe after the
run starts or reconnect without silently missing recent progress. The stream
carries lightweight execution and node lifecycle changes plus explicit progress
reported by a node; the ordinary execution response remains the source of truth
for terminal results and artifact outputs.

Node progress is plain, bounded display text, not a diagnostic dump. A node may
report a current and total count, but it must never include credentials, secret
values, complete input payloads, or other sensitive runtime state. Progress
publication is best-effort observation: a missing or slow subscriber never blocks,
fails, or cancels the node. Live events are not persisted in saved-graph history.

Node events carry an instance path whose first item is the visible node in the
submitted top-level graph and whose remaining items identify nested module call
sites and the emitting leaf node. This instance path is separate from the module
definition path used for cycle detection and invocation caching. The distinction
lets two nodes that invoke the same saved module revision aggregate their child
events under the correct outer canvas node.

Mapped node events also carry an invocation path: the ordered, zero-based item
indices accumulated as execution enters mapped module instances. The separate
local invocation index identifies the emitting node's own MAP item when it has
one. Together they distinguish progress from nested mapped modules without
encoding runtime item identity into the stable canvas node path.

The current Server-Sent Events adapter and its replay window share the existing
single-process execution ownership boundary. Supporting multiple API owners would
also require shared execution state, event replay, cancellation routing, and an
owner lease; adding more HTTP stream endpoints alone would not make execution
multi-worker safe.

### Invocation cache entry

A global, content-addressed reuse record for one node invocation. It is not a
saved-graph output binding and is not keyed by graph revision. Its versioned
digest covers the operator id/version, validated configuration, stable node and
module identity, invocation mode and mapped item index, resolved artifact-type
bindings, exact ordered input containers and artifact SHA-256 values, and opaque
secret revisions. The digest preimage and secret material are never persisted.

Node registrations are fail-closed: the default policy is `never`, while a
deterministic node may declare `exact`. Pure deterministic System nodes use
`exact`; uploads, graph-module wrappers, and provider-backed nodes remain
uncached unless their exact declaration supplies every stable dependency.
Mapping caches scalar item invocations independently and builds the
current aggregate sequence from those item outputs. A hit is valid only while
every referenced artifact row and stored object remains accessible; stale cache
entries are removed generation-safely. Cache entries are artifact-retention
roots, so future artifact garbage collection must include them.

### Field projection

A path from one compound artifact payload to a value that can be materialized as
another artifact type. The registry derives structural projections for nested
JSON Schema `string` and `integer` leaves when canonical scalar targets are
installed; plugins may explicitly override a path when they need a different
target or title. A projection is selected on an edge, persisted by exact path,
and validated again at runtime. It is not a visible adapter node and does not
introduce operation-specific leaf artifact types. Arrays and schema-less dynamic
properties are not inferred as scalar projections.

### Materialized scalar

An artifact type that declares it can materialize one JSON primitive runtime
value. `scalar.text@1` consumes and produces runtime `str`; its writer wraps that
primitive in the stable `{ "value": string }` payload and its resolver unwraps
the payload again. `scalar.integer@1` follows the same boundary for runtime
`int`. Storage envelopes must not leak into node input, output, projection, or
conversion callables.

### Artifact conversion

A deployment-owned, versioned, shape-preserving conversion from one artifact
type to another, such as `scalar.integer@1` to `scalar.text@1`. The exact key and
version identify one immutable contract and implementation; changing either
requires a version bump. A conversion changes the artifact representation;
unlike a field projection, it does not select a nested value. Configurable,
lossy, or domain-significant transformations remain visible nodes.

### Artifact conversion path

A bounded, ordered sequence of exact conversion keys stored on one edge. The
canonical conversions form a directed graph, so declarations `X -> Y` and
`Y -> Z` make `X -> Z` authorable without an adapter node. Each selected path is
simple: it cannot revisit an artifact type, even though the canonical map may
contain conversions in both directions. Deployment construction rejects adjacent
declarations whose runtime target and source types cannot compose. Authoring may
automatically select one unambiguous shortest path, but execution never searches
Plugin registry state. It validates and replays the stored keys against the
immutable deployment map, composes
their pure callables in memory, and materializes only the final target-typed
artifact.

### Spatial artifact model

Spatial sources and map presentation are separate artifact roles. A
`geo.feature_collection@1` is an exact, canonical WGS84 vector dataset whose
features may contain points, lines, polygons, multipolygons, or geometry
collections. Its logical source is stored in bounded chunks; a content-addressed
PMTiles sidecar is a derived rendering projection and never replaces the exact
features. A `geo.raster_scan@1` is an exact georeferenced scan normalized to a
Cloud Optimized GeoTIFF. Its browser-ready XYZ pyramid is likewise a derived
projection, not another workflow artifact.

A `geo.map_layer@1` is an inline, lightweight drawing recipe. It references one
feature collection or raster scan, or declares one public remote WMS source, and
owns visibility, zoom range, opacity, attribution, and vector or raster style.
A `geo.map_document@1` contains only an ordered list of map-layer references, an
optional basemap, and optional initial bounds. It never embeds source geometry,
pixels, PMTiles, or XYZ tiles. The same exact source can therefore participate in
several independently styled maps without data duplication.

The artifact HTTP adapter resolves those references into one small immutable
render descriptor. Vector archives are served through byte-range reads and
raster requests load one stored XYZ tile; storage bucket names and object keys
never cross the API boundary. Renderer controls are local preview overrides
unless a workflow deliberately produces another map-layer artifact.

Remote spatial services follow the same ownership split. WFS import takes a
bounded snapshot and produces an exact feature collection. WMS remains a remote
raster source referenced by a map layer and is fetched through the narrow image
proxy. Spatial service URLs are public, credential-free HTTP(S) endpoints;
secrets, arbitrary proxy targets, redirects, and browser-forwarded credentials
are outside this contract. Attribution remains attached to the source and is
carried into the renderer.

### Prompt message

A provider-neutral conversation message containing a `system` or `identity.py` role,
text, and optional ordered image artifact references. It never embeds or copies
image bytes. System messages cannot carry images.

### JSON Schema

A provider-neutral Draft 2020-12 object schema stored as serialized JSON text in
the nominal `json.schema@1` artifact type. The Schema Builder owns an ordered
field list: primitive and primitive-sequence fields are configured inline, while
an object field or object-sequence item consumes another JSON Schema through a
stable field-owned input plug. The builder inserts connected child schemas into
the parent, so canvas composition occurs at reusable object boundaries rather
than exposing every JSON Schema token as a node. A runtime schema does not create
a new artifact type or dynamic output ports; provider results remain fixed typed
envelopes containing schema-governed JSON objects.

### Node

A typed operation with configuration, graph inputs, and artifact outputs.
Authors can declare a node through a typed callable or explicit configuration,
input, and output models. Both forms describe the same versioned port contracts
and execution semantics. Calling an authored Python function directly returns
its Python value; a graph execution also materializes and persists its artifacts.
Changing the artifact key or value shape of a fixed port requires a new operator
version or an explicit saved-graph migration; the host does not silently rewrite
older contracts.

### Programmatic graph authoring

Programmatic authors build the same versioned `SavedGraphDocument` persisted by
the API and edited by the Workbench. A client resolves each local Node class
against the effective Workspace catalog, embeds the catalog's exact Plugin
release pin, validates port shapes and artifact-type bindings, and submits the
ordinary nested `{ name, document }` graph contract. There is no automation-only
graph representation or execution path. Saved execution reloads the requested
revision on the server and derives the runtime request from that canonical
document; the client cannot replace its topology at execution time.

### Input plug

A stable, ordered input position owned by one node instance for a port that
explicitly supports instance plugs. Each plug accepts exactly one incoming edge
and keeps its identity when reordered, so the saved plug order—not canvas
coordinates or edge creation order—defines execution order. The edge continues
to own its projection and artifact conversion path.

### Builtin family

A node family that ships as part of the workbench application, not as a Plugin
package. Builtin nodes identify by family slug and the deployment's build
digest. They are not Plugin releases and do not carry a release pin.
_Avoid_: bundled plugin, host plugin, system builtin plugin

### Plugin

A uv-managed project that groups nodes, artifact types, and the resolver/writer
factories those types require under one stable slug.
The working copy is a directory; execution trusts an immutable **Plugin
release** and an exact **Plugin installation**, not an ambient import into the
API process. An installation is either globally visible in **System** scope or
owned by one **Workspace**. Module is a separate catalog entry kind, not a
Plugin scope.

Each project owns one loader target in `[tool.grafy.plugin]`; projects without
that declaration use `grafy_plugin:PLUGIN`. System inventory repeats the target
as a deployment assertion, not as a second runtime path. The import name is
never catalog identity. Publishing a Plugin directory under a deployment
**Plugin root** creates revision N. Installing that release may establish a
System or Workspace family.
Coding-agent authoring reserves the deterministic
`<authoring-root>/<workspace-id>/<slug>` working copy, verifies and reviews an
exact freeze, then uses the same publication workflow as human publication.
Diffs do not auto-publish or retarget graph pins. See
[plugin unification](docs/design/plugin-unification.md).

System publication is a separate platform/CI authority and always retains an
OCI artifact. Published Plugins execute in isolated workers. Builtin families
owned by `grafy-workbench` run in-process with the API and are not Plugin
releases. Plugins depend inward on core contracts and ports, never on the API
host or concrete storage adapters.

### Plugin root

A deployment-allowlisted directory under which a Plugin working copy may live
and be published from. Roots are not the node catalog and do not grant
Workspace visibility. Repository-owned `plugins/<family>/` System projects and
mutable Workspace authoring state use separate roots; Workspace working copies
are additionally namespaced by Workspace id.

### Plugin release

An append-only, digest-addressed freeze of one Plugin package: source archive,
lock, inspected node and artifact contracts, canonical-conversion references,
runtime profile, invocation protocol, capabilities, loader contract, publisher
attribution, and immutable OCI artifact. A release has no System or Workspace
scope. The same descriptor bytes do not create another revision.

### Plugin installation

An append-only assignment of one exact Plugin release to either System scope or
one Workspace. The installation owns execution policy, installation authority,
and installation time. Assigning the same release to another scope does not
rebuild or copy its source or OCI artifact.

### Plugin selection

The mutable current installation for one scoped Plugin family. Its public graph
pin is `{scope, slug, release revision}`. A selection has a generation and a
published, deprecated, or withdrawn lifecycle state. Current never means the
greatest retained release revision.

A graph node carries two independent exact identities: the operator
(`notes.table.summarize@1`) and the installed Plugin release
(`{scope: workspace, slug: notes, revision: 4}`). Publishing revision 5 never
moves that pin. Deprecation and withdrawal prevent new insertion while retained
exact pins may run. Exact revocation retains the release and installation but
denies execution.

### Module (workspace library)

A reusable workflow building block hosted by a workspace library. A Saved graph
with Module Input/Output boundaries is only a candidate until someone
**publishes a release**. Call sites pin an immutable Module release
(`graph.module.{source_graph_id}@{revision}`). Publication states are
published, deprecated, and withdrawn. Withdraw hides a Module from Add node /
library browse; existing pins keep resolving. There is no hard delete of
releases in v1. Cross-workspace reuse is **Import into workspace** (copy-by-value).
Publish release requires Editor or Owner; Deprecate and Withdraw require Owner.

### Template (New graph library)

An immutable, sanitized copy source captured from one exact Saved graph
revision. **Use template** creates a new independent Saved graph in an explicit
My graphs or Team save location, with a chosen name and optional one-level
Folder. It copies graph structure and safe configuration by value, but never
secrets, execution history, materialized artifacts, uploads, caches, or invalid
runtime capabilities. Later source or Template changes never mutate an existing
copy. Templates appear in New graph / Library; unlike Modules, they are not
callable, do not have contracts or pinned releases, and are not inserted as
nodes.

### Node catalog / Add node

The effective Workspace catalog contains app-owned builtin families, selected
global System Plugin releases, selected Plugin releases owned by that
Workspace, and published Modules as a separate entry kind.
Every insertable Plugin node supplies an exact scoped release pin and a derived
runnable or disabled reason from the same admission policy used by compilation.
Builtin nodes are identified by family slug and the deployment's build digest;
they do not carry a Plugin release pin.

Grafy's builtin families contain broadly reusable operations: Image, Sequence,
Arithmetic, Text, Schema, and Table. A builtin artifact type must have precise,
producer-neutral meaning and be independently reusable. A builtin node must be
broadly reusable, deterministic, dependency-light, and must not duplicate
projection, conversion, mapping, or other edge/runtime behavior.
Image owns the producer-neutral `image.raster@1` artifact, its storage writer,
and the deterministic decode that turns a `file.png@1` or `file.tiff@1` artifact
into a raster. Table owns
the producer-neutral `table.data@1` artifact: stable ordered columns with
duplicate-friendly display titles, declared value types, and rectangular rows
keyed by column id. SQL results
embed this table and expose it through an explicit field projection; source-specific
table interpretation remains with its producer.

Sequence provides `Collect<T>`, Count, Slice, and Pick item; image- and
text-specific collectors are not separate builtin nodes. Schema provides one
recursive JSON Schema Builder, and the LLM Plugin provides deterministic
prompt-message construction; provider-backed execution remains an optional
System Plugin.
OCR table fragments remain OCR-owned because deciding how Markdown rows become
headers, columns, and inferred values is a source-specific normalization rather
than a shape-preserving artifact conversion. Optional System families provide
remote or domain-specific nodes through the same release schema. SQL remains
isolated-only because user-authored queries are executable code and validation
is not a sandbox. [R45: Untrusted Query Isolation]

### Port

A named node input or output that declares one or more accepted concrete
artifact types or a single named artifact-type variable, plus cardinality. An
input that declares several concrete types accepts any one of them; an origin
or edge whose artifact type is none of them is refused unless a declared
artifact conversion reaches one of them. Every use of the same variable on one
node shares one concrete binding owned by that node instance. Ports may
carry one artifact, an ordered artifact sequence, or variadic incoming edges when
explicitly declared. Port cardinality describes the value seen by one operator
invocation; it does not decide how many times the operator runs.

### Optional input and connection state

Requiredness belongs to an input port's contract. A required input must receive
an active connection before its node can run; an optional input may be omitted
and lets its input model apply the declared default. Omission and explicit
nullability remain separate contract properties. A missing optional artifact is
never represented by inventing a null artifact.

Enabled state belongs to the edge that connects two ports. A disabled edge stays
in the saved graph, retains its route, projection, conversion path, collection
mode, and target-slot reservation, and remains structurally validated so it can
be enabled again safely. It does not participate in execution ancestry, mapping,
required-input satisfaction, pin resolution, or compiled input values. Runtime
edge requests therefore contain active edges only. Existing saved edges default
to enabled when the field is absent.

### Edge collection mode

The transport policy stored on an edge. `direct` passes the produced value to
the target with its collection shape unchanged. `map` connects a produced
sequence to one required item input, calls the target operator once for each
item, broadcasts its other inputs, and aggregates required item outputs into
source-position-aligned sequences. The runtime derives its internal invocation
policy from incoming edges. A target has at most one map driver; zip, Cartesian,
and implicit flattening semantics are not part of the contract.

Ordered sequence consumers that need cross-item context receive a `direct` MANY
input and execute once. `map` is reserved for invocations whose items are
independent; it must not be used to assemble or process one conversation message
at a time. Revision-scoped materialized outputs are whole-node bindings, not
per-item checkpoints.

A node instance participating in concurrent MAP execution must be task-reentrant.
Its `run` calls may overlap on the same event loop, so implementations must keep
invocation-local state in the call and must not mutate that state on the shared
node instance. Implementations may clean up after task cancellation but must not
suppress it, so failed or cancelled MAP invocations can drain their active items.
Reusable runtime collaborators follow the same concurrency boundary: production
SQL unit-of-work sessions are task-local, while the in-memory adapter serializes
its transactions to preserve deterministic commits.

The host keeps graph execution responsibilities separate. `RunGraph` coordinates
run preflight, compilation, pin resolution, execution, and successful
materialization binding. Preflight checks saved-revision and secret bindings;
compilation resolves topology, contracts, projections, conversion paths, and
invocation policy into an immutable plan. A graph execution port receives that
prepared plan and executes it in-process: one coordinator visit per logical
node, with scalar MAP items running concurrently inside the node executor,
bounded by `GRAFY_MAP_MAX_CONCURRENCY` (default `4`). Their completion order is
not observable: aggregation remains aligned to source position. When one item
fails, unfinished sibling items are cancelled on a best-effort basis.

The shared graph coordinator only propagates graph state, skips failed
dependents, and assembles the run result. Node execution owns input assembly,
opaque secret revisions, ONCE/MAP expansion, and source-position-aligned MAP
aggregation. Edge value resolution applies the already compiled projection and
conversion chain.
`NodeRuntime` executes and persists exactly one scalar node invocation; it does
not schedule graphs or implement collection mapping. Grafy remains the source
of truth for artifacts, invocation caching, materialized outputs, and encrypted
node secrets; decrypted secrets and live runtime collaborators never leave the
process.

Local execution visits logical nodes sequentially. Only the scalar items within
one MAP invocation may overlap. If execution later moves to a remote single
worker, the transport boundary belongs above `RunGraph`: submit a serializable
run request, then perform preflight and compilation inside that worker. The
current design does not define multi-worker or per-node remote scheduling.

### Collect node

The generic cardinality-changing operation `Collect<T>`. A Collect node instance
binds `T` to one concrete artifact type; every ordered input plug then accepts
either one `T` artifact or one `T` sequence, and its output is a sequence of `T`.
It appends scalar references and expands sequence references exactly one level in
plug order, producing a fresh `ArtifactRefSequence` without rewriting its
artifact items. Different shapes may be combined, but different artifact types
may not. If any source sequence is unordered, that unordered state propagates to
the result. Collection is node behavior; every incoming edge remains `direct`,
and `map` is not valid for a Collect input.

### Workflow graph

A set of configured node instances and directed edges. The graph must be
validated for operator identity and version, edge collection modes, port
existence, required inputs, effective cardinality, compatibility, declared
projections and conversions, and cycles before any node executes. Edge value
handling has one fixed order: optional field projection, zero or more stored
artifact conversions, then `direct` or `map` collection handling.

### Saved graph

A durable workbench document containing a workflow graph plus user-authored
canvas layout. It stores configured node identities, positions, semantic edge
endpoints, origins, ordered instance input plugs, node artifact-type bindings,
projections, conversion paths, collection modes, and edge routing offsets. A generic binding
survives even when its incident edges are temporarily removed; users reset it
explicitly before binding the node to another artifact type. Registry metadata,
callbacks, selection, viewport state, and execution results are derived or
runtime state and are not part of the saved aggregate.
Materialized output bindings are durable runtime records keyed to a saved
revision, not fields inside the saved graph. Upstream output pins belong to an
individual run request and remain transient. Drafts may be saved before they
are executable.

Saved graphs use optimistic revisions. Replacing a graph requires the revision
last read by the caller so competing edits are reported instead of silently
overwriting one another.

### Workbench

The user-facing graph editor and its execution interface. Ordinary node
configuration is rendered on the node from JSON Schema; interactions that own
dynamic graph structure, such as Schema Builder fields and their input plugs,
use a dedicated node body. Nested artifact fields and collection
mapping are selected on each edge. Compatible declared conversion paths are also
stored and displayed on the edge; a unique route may be selected automatically
when the user connects otherwise-incompatible ports. The complete
graph or a selected subgraph can be executed. By default, selected execution
includes internal and incoming crossing edges and reuses the exact materialized
output binding for each unselected source port. If a required binding is
missing, the run is blocked and the workbench directs the user to run the
upstream node or run with dependencies. `Run with dependencies` is a separate
action that expands the selection to its full upstream closure and executes that
expanded graph. Pins and live running state remain transient; revision-scoped
materialized outputs are restored when a saved graph is reopened.

Every saved graph presented as a supported product workflow must be reproducible,
inspectable, and editable through the production Workbench UI. HTTP
APIs, scripts, and direct graph-document manipulation may automate only authoring
operations that the UI itself exposes; they must not populate hidden
configuration or create graph states that a user cannot subsequently maintain in
the UI. Registry schemas and backend validation establish that a state is
representable, not that it is product-authorable.

When a node requires essential configuration that the generic JSON Schema form
cannot render or edit, the dedicated Workbench interaction must be implemented
before that configuration is used in a persisted workflow. End-to-end acceptance
therefore includes creating or editing the workflow through the real UI, not only
saving it through an API and executing it successfully. Any deliberate
low-level-only exception requires explicit user approval and must be identified
as unsupported or experimental rather than presented as a completed UI workflow.
