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
| `Operator` | Deployment-level account named in `GRAFY_OPERATOR_EMAILS` by its verified, issuer-asserted email (the same trust as domain Workspace grants). Only an operator may disable or re-enable a `User`, through `/v1/admin/users/{id}`; it is not a Workspace role, carries no Workspace access, and is never conferred by a PAT. An operator cannot disable their own account. |
| `FeedbackReport` | What a signed-in `User` sends from the app about one picked screen element or a whole page: kind, message, the element's description, and optionally a cropped screenshot. It belongs to the deployment, not to a Workspace: the Workspace the page was in is recorded as context after checking the reporter's membership. Only an `Operator` reads, resolves, reopens, links to a GitHub issue, or deletes one, at `/admin/feedback`. |
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
| `SecurityAuditEvent` | Metadata-only security audit row; never stores credentials, provider payloads, or command/config bodies. |
| `GraphRoomSession` | Ephemeral WebSocket participant identity inside one `(workspace_id, graph_id)` collaboration room. |
| Capability | Fine-grained permission derived from role (and intersected with PAT scopes), such as `edit_graph`, `execute_graph`, or `join_graph_room`. |

“Team” and “organization” in conversation both mean a shared workspace. There is
no second grouping aggregate, per-graph ACL, or public-link grant in the first
delivery.

### Artifact

A typed, versioned value that a node can produce or consume and that a user or
agent can author when its registered type accepts JSON authoring. Its payload
may be inline or stored as content. Its artifact type and schema version are
always explicit. Authoring an edit creates a new immutable artifact in the
same Workspace and can record a reference to the prior artifact as provenance.

### Artifact type

The contract for an artifact payload. It owns the stable type id, schema
version, payload schema, display title, materialized JSON shape, declared field
projections and exports, and an exact portable bundle format/version. Another
Plugin may reference the type only by carrying the same complete serialized
contract as an artifact-type dependency; a matching id/version with different
contract bytes is a collision. Versioned conversions between artifact types
are deployment-owned canonical behavior, not an asset of either endpoint's
family.

An inline artifact type also declares every field that contains persisted
artifact references, including the JSON path, target artifact type, and whether
the field contains one reference or many. Isolated execution follows only these
declared references. It stages the exact referenced artifacts as read-only
dependencies in the guest artifact store, without turning them into extra node
ports or granting access to unrelated Workspace artifacts.

`html.page@1` stores the artifacts its template reads under `sources`, keyed by the name the page's author chose. Those names and target types vary, so the type declares no artifact-reference field, and copy, deletion and retention do not follow them.

An artifact type is a payload contract, so two nodes that move the same payload
share one type. A second type id for an identical contract is a catalog bug, not
a Plugin namespace: an image Plugin that declares `photos.shot@1` over the
`image.raster@1` payload cannot connect to nodes that expect a raster.
Specialized types exist only where the contract differs, as `geo.feature_collection@1`
(exact WGS84 geometry rather than pixels) and `geo.map_layer@1` (a drawing recipe
rather than pixels) do. A node does not escape this by declaring a type variable: `T`
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
Configurable interpretation is a visible node, so `file.csv@1` becomes
`table.data@1` through an import node whose delimiter and header choices the
user can see and change; parameterless container conversions such as
`file.txt@1` to `scalar.text@1` and `file.{png,jpeg,webp,tiff,bmp}@1` to
`image.raster@1` run as canonical artifact conversions on the edge.
_Avoid_: upload artifact, source node

### File JSON artifact

`file.json@1` is the container for a `.json` file. Ingest confirms the bytes
parse as a JSON object or array. It does not assert GeoJSON or SGKP shape.
_Avoid_: json file, generic json

### Extension claim

The mapping a `file.*` artifact type declares from one extension string to
itself, carried in the artifact type contract and registered with the type. One
extension maps to exactly one format type, so a type cannot claim an extension
the deployment already holds, and composition refuses a family whose claim would
collide. A claim states which bytes belong to the format.
Confirming those bytes is the format's own rule.
_Avoid_: file type registration, extension mapping, upload node

### Confirmation rule

The closed check a file format artifact declares for its bytes: `magic`, `json`,
`json_document`, or `none`. `json` means a JSON object, `json_document` means a
JSON object or array, and `magic` means the bytes match a declared signature.
Agreement is a prefix check rather than a full parse, so a truncated or corrupt
file fails in the edge conversion or in the visible import node.

### File blob artifact

The format type for bytes whose extension the deployment does not recognize:
`file.blob@1`. It is the fallback member of the same family and carries the same
reading, that nothing has interpreted these bytes yet. A blob has no domain
meaning and projects no fields. Recognizing the format later does not rewrite a
stored blob: a Plugin that claims an extension types the next upload, and rows
already stored stay `file.blob@1`. Nothing claims those bytes afterwards. No port
takes a blob and no node retypes one, so they reach no typed node until the
deployment claims their extension and they are uploaded again. A blob never gains
a format in place.
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

### Origin

A node input satisfied by a direct reference to a Library artifact instead of by
an edge from an upstream node. An origin holds the exact `ArtifactRef` or
`ArtifactRefSequence` the user placed there, plus a declared artifact conversion
path when the artifact's type is not already one the input accepts, and it adds
no node to the Graph; on a `many` port, several artifacts group into one
sequence. It names an artifact by identity rather than searching for one. An origin and an
enabled edge never satisfy the same input, though a disabled edge may wait beside
one. An origin whose artifact can no longer be read stays in the Graph document
exactly as written and leaves its input unsatisfied. An origin therefore belongs
to the Workspace that owns its artifact: copying a graph into another Workspace
drops the origin and leaves that input unsatisfied, rather than moving bytes
across the tenancy boundary.
_Avoid_: source node, source operator, input node

### Project

The Workspace-owned collaborative document and the unit of append-only
checkpoints. A Project is the collaboration room and the object folders,
archive, starring and last-opened state attach to. It holds named **Graphs** and
the results its nodes have produced. Every Project belongs to exactly one
Workspace; effective permission is role ∩ PAT scope ∩ capability. There is no
per-Project ACL. A Project's name is separate from its Graphs' names.
_Avoid_: saved graph, workspace document, canvas

### Graph

A named definition inside a Project: a typed interface (inputs and outputs
declared by `graph.input` / `graph.output` boundary nodes), nodes, edges, origins
and its own canvas layout. Any Graph can be run directly or called from a sibling
Graph. Graph ids are unique within their Project.
_Avoid_: workflow, module

### Call node

A node that places a sibling Graph of the same Project. Its ports are that Graph's
interface. The reference is live: caller and callee are checkpointed together, so
there is no release or pin. The call relation is acyclic and a Graph that still has
callers cannot be removed. Changing a Graph's interface surfaces the broken
connections at its call sites as connection issues instead of rejecting the edit.
A call node never becomes an instance; expansion inlines the callee.

### Node instance

`(project, graph, call path, node id[, map index])`: the unit that owns a
fingerprint and a derived state. A node called twice has two instances.

### Fingerprint

A digest over a node instance's operator id and version, implementation identity,
config, secret state, artifact type bindings, ordered input plugs and, for each
incoming connection, the upstream fingerprint, projection and conversion path.
Origins contribute their artifact identity. Node ids, positions and the instance
key never enter it, so identical content with identical upstream shares one
fingerprint. A `NEVER`-cache node also carries its refresh generation. An operator
the build does not register is an error, never a default policy.

### Result store

Append-only map from fingerprint to the successful outputs of a computation,
scoped by Workspace. Entries are never mutated. Failures are recorded on the
instance, not in the store. The only mutable per-instance record is its pointer to
the last result and last failure, so a stale node keeps showing what it last
produced. The store subsumes the invocation cache and the materialized output
binding. It has no garbage collection yet.

### Instance state

Derived, never stored: **fresh** when the current fingerprint has a result,
**queued** or **running** while a computation for it is in flight, **failed** when
the last attempt at this fingerprint failed, otherwise **stale**. An edit during a
Run leaves the instance stale; the Run's result is stored under the fingerprint it
started with. A service node has no stored result, so stale is omitted: it shows
an in-flight or failed condition, or nothing.

### Refresh generation

The counter a `NEVER`-cache node carries in its fingerprint. Refreshing is a
Project command (`refresh_node`), so every participant sees it and a checkpoint
records it.

### Run

A demand for a set of target node instances to become fresh. It schedules only the
stale part of their upstream closure. Any number of Runs are active in one Project,
started by any member with `start_run`. Computations are single-flight per
fingerprint; cancelling a Run withdraws its demand and cancels a computation only
when no active Run still needs it. A Run record holds who started it, its targets
and its status (`running`, `succeeded`, `failed`, `cancelled`, `interrupted`); it
holds no outputs. On API restart unfinished Runs are marked `interrupted` and stored
results stay fresh.
_Avoid_: execution, workflow run

### Provider credential

An encrypted, write-only provider key with a label, provider kind, and verification
status. A Personal credential belongs to a user. A Shared credential belongs to one
Workspace, and only members with `manage_secrets` can create, rotate, verify, or
delete it in the vault. A node's Graph binding can select a Shared credential,
require a Personal credential, or select a deployment default. A user's selection
takes precedence for Runs that user starts. Selections live outside the Graph
document and its checkpoints.

A Shared credential's Graph binding contributes its revision to the Workspace's
fingerprints. A binding that requires Personal credentials contributes the binding
mode. Personal selections and Personal credential identities stay out of shared
fingerprints. Runs still share stored results and in-flight work at the Workspace
fingerprint.

### Library artifact

The artifact a Workspace owns, shown in the Library drawer. There is one Library
per Workspace and every member sees it. Any stored Workspace artifact is
eligible, including uploads, node results, and artifacts authored on the
canvas. A Library artifact is Workspace-owned and independent of any
Project: Projects reference it, and deleting a Project or a checkpoint
never deletes it. It is a retention root in its own right, so nothing
collects it while it sits in the Library. Saving into the Library promotes an
artifact that already exists in the Workspace. Identity is the exact
artifact reference, so saving the same artifact twice yields one Library
artifact, and picking one never means taking the newest artifact of a matching
type. An artifact has one placement in the Library, and moving it never changes
its reference. Removing an artifact from the Library clears its placement and
leaves the row and its bytes alone. Deleting a Library artifact is refused while
any Project head or checkpoint references it, and the refusal names those
Projects. A forced delete removes the origin from each referencing Project head and
leaves the input unsatisfied.
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

An output a node instance's result holds, shown in the Generated drawer. The drawer
is a view of the Project's stored results (the last result of each instance), so an
item stays visible after the node goes stale and one reaches the Library only through
an explicit save. Saving into the Library adds a reference to the same identity
rather than moving or copying it.
_Avoid_: produced, generated, result

### Room instance and Run events

Transient room frames: `run.started` / `run.finished` announce the active-Runs list
with who started each, and `instances.changed` carries instance-state deltas keyed by
full instance key. Instance state is recomputed and diffed per Project after
scheduler transitions, accepted command batches and secret changes. Frames are
best-effort observation and never block or cancel a computation; the REST list of
Runs and instance states is the source of truth. The room assumes one API owner.

### Agent

A canvas object on a Graph that holds conversations with a model. It is not a node:
it is never an instance, never scheduled, and links to it never enter a fingerprint.
Its setup (name, instructions, model, connected context and tools) is Graph document
content. A Graph may hold several Agents. It uses the deployment default model unless
whoever configures it gives it an endpoint and key of their own.
_Avoid_: assistant, chatbot, bot

### Agent conversation

The append-only event history of one thread with one Agent, owned by the Project:
messages, tool calls, tool results and turn outcomes. Events are never edited;
continuing from an earlier point forks a new conversation. Readable by anyone with
`view_project`.

### Turn

One user message and everything the Agent does until it answers, stops or is
cancelled. Sent over HTTP with a client-chosen turn id, run by the API owner, streamed
to the Project room. One turn runs at a time per conversation. Interrupted by an API
restart like a Run.
_Avoid_: request, job, request/response pair

### Turn receipt

The durable record that a send was accepted, written in the same transaction as its user
message: who asked, which Agent and canvas state it will run on, which sequence its
message took, and how it ended. A repeated send is answered from it instead of run again.
Its terminal state is claimed once, by the cancel, the model failure or the restart
recovery that gets there first. Streamed text is never the receipt: the message stored
when the turn ends replaces it, and is what the next turn reads as history.
_Avoid_: job record, run, outbox

### Agent tool link

The connection from a node or call node's tool handle to an Agent. The node's open
inputs become parameters the model fills, or are hidden; inputs wired from upstream
stay fixed; chosen outputs are returned to the model. A tool call runs as a
computation with no instance, so it is cached but never changes what the node shows.

### Field projection

A path from one compound artifact payload to a value that can be materialized as
another artifact type. The registry derives structural projections for nested
JSON Schema `string` and `integer` leaves when canonical scalar targets are
registered; plugins may explicitly override a path when they need a different
target or title. A projection is selected on an edge, persisted by exact path,
and validated again at runtime. It is not a visible adapter node and does not
introduce operation-specific leaf artifact types. Arrays and schema-less dynamic
properties are not inferred as scalar projections.

### Materialized scalar

An artifact type that declares it can materialize one JSON primitive runtime
value. `scalar.text@1` consumes and produces runtime `str`. The declaration
stores that primitive in the stable `{ "value": string }` payload and loads
the payload back out as `str`. `scalar.integer@1` does the same for runtime
`int`. Storage envelopes must not leak into node input, output, projection, or
conversion callables.

### Artifact conversion

A deployment-owned, versioned, shape-preserving conversion from one artifact
type to another, such as `scalar.integer@1` to `scalar.text@1`. The exact key and
version identify one immutable contract and implementation; changing either
requires a version bump. A conversion changes the artifact representation;
unlike a field projection, it does not select a nested value. Configurable,
lossy, or domain-significant transformations remain visible nodes.

`file.txt@1` to `scalar.text@1` and `file.{png,jpeg,webp,tiff,bmp}@1` to
`image.raster@1` are the conversions that start at a File format artifact.
`file.txt@1` reads the stored bytes and decodes them as UTF-8, dropping a
leading byte-order mark, and the raster image conversions verify that the image
container parses cleanly as its declared format, with no choices to make, so
they need no node; corrupt or mismatched bytes fail the conversion step.
Formats with parsing options, such as CSV or Excel tables, still go through a
visible import node.

### Artifact conversion path

A bounded, ordered sequence of exact conversion keys stored on one edge. The
canonical conversions form a directed graph, so declarations `X -> Y` and
`Y -> Z` make `X -> Z` authorable without an adapter node. Each selected path is
simple: it cannot revisit an artifact type, even though the canonical map may
contain conversions in both directions. Deployment construction rejects a step
whose source declaration is not the artifact type produced by the previous
step. Authoring may automatically select one unambiguous shortest path, but
execution never searches plugin registry state. It validates and replays the
stored keys against the immutable deployment map, awaits each conversion, and
materializes only the final target-typed artifact.

### Spatial artifact model

Spatial sources and map presentation are separate artifact roles. A
`geo.feature_collection@1` is an exact, canonical WGS84 vector dataset whose
features may contain points, lines, polygons, multipolygons, or geometry
collections. Its logical source is stored in bounded chunks and stays the only
copy of the geometry: no derived rendering projection is written beside it, and
reading one feature or querying matched features reads the stored chunks. A
map draws a collection by fetching those chunks whole, as one GeoJSON document
served on request, and styling it in the browser; a collection too large to
fetch whole is refused rather than tiled. A map raster is an uploaded georeferenced
`file.tiff@1` read on demand by the tiler, which renders one XYZ tile per
request; nothing precomputes a pyramid or a Cloud Optimized copy.

A `geo.map_layer@1` is an inline, lightweight drawing recipe. It references one
feature collection, one georeferenced TIFF, or an ordered list of them as a
mosaic, or declares one public remote WMS source, and owns visibility, zoom
range, opacity, attribution, and vector or raster style.
A `geo.map_document@1` contains only an ordered list of map-layer references, an
optional basemap, and optional initial bounds. It never embeds source geometry,
pixels, or tiles. The same exact source can therefore participate in
several independently styled maps without data duplication.

The artifact HTTP adapter resolves those references into one small immutable
render descriptor. A raster layer in it is a tile source: a TIFF, a mosaic or a
remote WMS read through TileJSON plus one tile per request. A feature layer
names its collection's GeoJSON URL and property fields. Storage bucket names
and object keys never cross the API boundary. Renderer
controls are local preview overrides
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
against the deployment catalog, records the operator id and version, validates
port shapes and artifact-type bindings, and submits the
ordinary nested `{ name, document }` graph contract. There is no automation-only
graph representation or execution path. A Run reloads the requested
revision on the server and derives the runtime request from that canonical
document; the client cannot replace its topology at execution time. MCP tools
author through the same client and the same REST routes, never a service beneath
them, and place artifact cards only in the forms the Workbench creates (ADR 0023).

### Input plug

A stable, ordered input position owned by one node instance for a port that
explicitly supports instance plugs. Each plug accepts exactly one incoming edge
and keeps its identity when reordered, so the saved plug order—not canvas
coordinates or edge creation order—defines execution order. The edge continues
to own its projection and artifact conversion path. A port may declare spare
plugs (Collect does): the canvas keeps one empty plug there for the next member,
and a Run ignores any plug no edge feeds. Every other plug must be fed.

### Builtin family

A node family that ships inside the `grafy-workbench` package rather than in its
own package under `plugins/`. Builtin nodes identify by family slug and the
deployment's build digest.
_Avoid_: bundled plugin, host plugin, system builtin plugin

### Plugin

A node-family package under `plugins/<family>/` that the API process loads at
composition: nodes, artifact types, and the declarations that load and store
those types, under one stable slug. A Plugin is application code, not a
deployable. It ships in the API's own image and lockfile, is installed into the
same `PluginRegistry` as the builtin families from one static tuple, and its
nodes identify by family slug and the deployment's build digest — exactly as a
builtin family does. Which families exist is a build decision: a family absent
from the tuple has no nodes, no artifact types and no catalog entry.
_Avoid_: release, revision, installation, selection, revocation, publication,
promotion, registry, sandbox, isolated-only, system plugin

A Plugin keeps its own package and third-party dependencies, so a heavy native
or provider dependency set stays out of `grafy-workbench`. It depends inward on
core contracts and ports, never on the API host or concrete storage adapters,
and it owns no HTTP route. What ADR 0017 took away is the ability to be
versioned, published, or executed in another process; the import name is still
never catalog identity, and the slug is.
See [ADR 0017](docs/adr/0017-plugins-are-application-code-in-process.md).

Python execution and its presets are retired, and there is no SQL family.
All registered nodes use the deployment build identity.

### Egress guard

The single place that decides whether a destination named in node configuration
may be dialed: it resolves the host, refuses the address set unless every answer
is a global address, and holds the connection to one of those answers by
dialing the validated address. Every user-supplied destination goes through it
— LLM and Mistral `base_url`, WFS and WMS — so the deployment's own Postgres, MinIO and Keycloak are
unreachable from a graph. A trusted private destination comes from operator
configuration only; a node, a graph and a Workspace can never widen it.
_Avoid_: egress broker, network policy, sandbox network

### Pack

A code-defined, task-oriented discovery bundle, shown in the Workbench as a
Tool pack: a curated set of steps and engines managed per Workspace (for
example `Essentials`, `Document OCR`, `Maps & GIS`, or `Historical Map
Toponyms`). A Pack groups explicit node operator ids across one or more
builtin families and Plugins and may automatically include every enabled
Provider node satisfying declared Service contracts. Deployment configuration
(`GRAFY_CATALOG_CONFIG`) sets the default subscriptions for new Workspaces and
deployment-wide Pack or operator-id disablement. Only Workspace owners
subscribe or unsubscribe Packs through `manage_packs`, except `always_on`
Packs (`Essentials` is always on). Packs govern discovery only: hiding a node
or unsubscribing a Pack sets `catalog_visible: false` without removing the
node from the registry. Subscriptions change the picker and leave stored
Graphs, execution, and result identity intact; they never break existing saved
Projects and never enter node fingerprints.
_Avoid_: plugin bundle, plugin marketplace, artifact bundle contract

### Node catalog / Add node

The node registry describes every installed operator by id and version. The
catalog lists every registered node from the builtin families and Plugins
installed in this deployment, grouped for browsing into the Workspace's
subscribed Packs, plus client-synthesized sibling Graph call nodes and Graph
boundary nodes (`Graph input` / `Graph output`, gated by the `subgraphs`
Pack). Saved Graphs resolve their nodes against that registry, including steps
hidden from Add node. Every registered node remains present in the Workspace
catalog response even when hidden by deployment configuration or Pack
subscriptions (`catalog_visible: false`), so existing saved Projects hydrate
and run cleanly. An operator id absent from the deployment registry is a
compile error.

Grafy's builtin families contain broadly reusable, dependency-light, vendor-neutral operations: Image, Sequence, Value, Text, Schema, Table, File, and OCR. A builtin artifact type must have precise, producer-neutral meaning and be independently reusable. A builtin node must be broadly reusable, deterministic, dependency-light, and must not duplicate projection, conversion, mapping, or other edge/runtime behavior.
Image owns the producer-neutral `image.raster@1` artifact, its storage writer, and the deterministic decode that turns a `file.png@1` or `file.tiff@1` artifact into a raster. Table owns
the producer-neutral `table.data@1` artifact: stable ordered columns with
duplicate-friendly display titles, declared value types, and rectangular rows
keyed by column id, plus generic Markdown table extraction (`table.extract_from_markdown`) and concatenation.

Sequence provides `Collect<T>`, Count, Slice, and Pick item; image- and
text-specific collectors are not separate builtin nodes. Schema provides one
recursive JSON Schema Builder, and the LLM Plugin provides deterministic
prompt-message construction; provider-backed execution stays in the
`external.llm` Plugin. Plugin families provide vendor/gateway providers, heavy
native-dependency domains, and experimental project-specific vertical pipelines
through the same registry as the builtin families.

### Service contract

A nominal protocol under `grafy_core.contracts` registered with an id, version and title (such as `DocumentOcr` / `ocr.document@1`, `TextBoxDetector` / `ocr.box_detector@1`, and `CropTextReader` / `ocr.crop_reader@1`). A class implements the contract only by subclassing it; a matching method name is not enough. The object that satisfies it is built while a consumer runs and is gone when that computation ends. It is never an artifact: it is never stored, never logged, and never part of metadata. Contracts whose consumers cache per-tile or per-crop calls expose `cache_identity()` returning deployment, optional immutable revision, and request options; a `None` revision bypasses the provider cache.
_Avoid_: DI service, capability provider object

### Service port

A node input or output typed as a service contract (or, on an output, a class
that subclasses one). It carries contract keys, not an artifact type, and on a
service output carries contract-scoped declared features. Its type identity is
a service contract key. A service output feeds only a compatible service
input, and the reverse. A node with a service output has no input ports,
exactly one service output port, and implements one service contract in v1.
The planner never plans a service node; the consumer's runner builds the
connected provider in-process and validates any `RequiresServiceFeature`
optional outputs generically. An Agent tool never offers a service input to
the model; it leaves that input to the Graph.
_Avoid_: OutPort/InPort for services

### Provider node

A node with no input ports and a single service output implementing one
contract in v1. It has no artifact inputs. Its config and node-scoped secrets
shape the live object the consumer's runner builds in-process. The planner
never schedules it. Its config and key enter the consumer's fingerprint
through `upstream_fingerprints`.
_Avoid_: capability node, OCR vendor node as a synonym for every provider

### TIFF text regions

A result on one page of a stored TIFF. It records the native window that was
read and the detected polygons in full-resolution source page pixels, with the
top-left as the origin. A `TextBoxDetector` takes the window PNG and returns
window-relative polygons, optionally with readings. The detection node places
them in source pixels before persistence. The result references the exact
Workspace artifact so its card can overlay the polygons on that page as it zooms.

A prepare node joins boxes on one baseline into a span in source pixels. The
join can cover several words. When the rotated envelope would extend past the
members' pixel bounds, the span uses their convex hull. Recognition reads the
span once through a `CropTextReader`, stitching native TIFF reads for larger
crops. A filter node keeps name-like readings. The places table gives each
candidate's name, confidence, page, and centroid. It strips explicit Cyrillic
settlement prefixes and skips readings with explicit water-feature prefixes.
The collection node combines readings from multiple TIFF sheets into one places
table. Each row includes the source TIFF artifact ID alongside its page and
pixel coordinates.

### OCR node

The app-owned builtin (`Document OCR`, `ocr.read_document`) that takes a
`RasterImage | PdfFile` document and a `DocumentOcr` (`ocr.document@1`)
service input. It names no vendor and accepts no remote document URL. It
produces transcription markdown. Its optional `blocks` and `regions` ports
each require a feature of that engine's contract (`RequiresServiceFeature`).
The runner omits an unsupported output from the stored result and records it
in `unsupported_outputs`, so a downstream node fed by that port fails naming
the provider, not with an empty artifact.
_Avoid_: Mistral node / Reducto node (those are Provider nodes or the legacy
read-with-vendor operators)

### Port

A named node input or output that declares one or more accepted concrete
artifact types or a single named artifact-type variable, plus cardinality — or,
for a service port, the service contract keys it accepts or produces. An
artifact input that declares several concrete types accepts any one of them; an
origin or edge whose artifact type is none of them is refused unless a declared
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
in the Graph document, retains its route, projection, conversion path, collection
mode, and target-slot reservation, and remains structurally validated so it can
be enabled again safely. It does not participate in execution ancestry, mapping,
required-input satisfaction, or fingerprint inputs. Runtime
edge requests therefore contain active edges only. Existing saved edges default
to enabled when the field is absent.

### Edge collection mode

The transport policy stored on an edge. `direct` passes the produced value to
the target with its collection shape unchanged. `map` connects a produced
sequence to one input, calls the target operator once for each item,
broadcasts its other inputs, and aggregates required item outputs into
source-position-aligned sequences. That input is not variadic and may be
optional. The edge selects it. A single-value input receives the item itself; a
sequence input receives a sequence of one holding the item, so a sequence feeding
a sequence input may be passed whole or mapped. An empty source sequence fails the
run. The runtime derives its internal invocation policy from incoming edges. A
target may have several map edges, one per input; their sequences pair items by
position and must have equal lengths. With several map inputs, every sequence
must be ordered. Cartesian products and implicit flattening are not part of
the contract.

Ordered sequence consumers that need cross-item context receive a `direct` MANY
input and execute once. `map` is reserved for invocations whose items are
independent; it never assembles items into one value, so mapping prompt messages
into a completion runs one single-message conversation per message rather than
building one conversation. Node results are whole-node entries in the result store, not per-item checkpoints.

A node instance participating in concurrent MAP execution must be task-reentrant.
Its `run` calls may overlap on the same event loop, so implementations must keep
invocation-local state in the call and must not mutate that state on the shared
node instance. Implementations may clean up after task cancellation but must not
suppress it, so failed or cancelled MAP invocations can drain their active items.
Reusable runtime collaborators follow the same concurrency boundary: production
SQL unit-of-work sessions are task-local, while the in-memory adapter serializes
its transactions to preserve deterministic commits.

The host keeps Run responsibilities separate. The Run service plans a Run from the
expanded Project Graph and its fingerprints and hands computations to the kernel
scheduler (one concurrency budget per Project, single-flight per fingerprint). The
node computation runner reads upstream results from the result store by fingerprint,
applies each edge's projection and conversion chain, and executes ONCE/MAP semantics;
scalar MAP items run concurrently inside the node executor, bounded by
`GRAFY_MAP_MAX_CONCURRENCY` (default `4`), and aggregation stays aligned to source
position. `NodeRuntime` executes and persists exactly one scalar node invocation; it
does not schedule graphs or implement collection mapping. Grafy remains the source of
truth for artifacts, stored results and encrypted provider credentials; decrypted secrets and
live runtime collaborators never leave the process. In-flight state lives in the single
API owner; the current design defines no multi-worker or remote scheduling.

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

The set of configured node instances and directed edges of one Graph. It must be
validated for operator identity and version, edge collection modes, port
existence, required inputs, effective cardinality, compatibility, declared
projections and conversions, and cycles before any node executes. Edge value
handling has one fixed order: optional field projection, zero or more stored
artifact conversions, then `direct` or `map` collection handling.

### Graph document

The durable content of one Graph: a workflow graph plus user-authored canvas layout. It stores configured node identities, positions, semantic edge
endpoints, origins, ordered instance input plugs, node artifact-type bindings,
projections, conversion paths, collection modes, and edge routing offsets. A generic binding
survives even when its incident edges are temporarily removed; users reset it
explicitly before binding the node to another artifact type. Registry metadata,
callbacks, selection, viewport state, and execution results are derived or
runtime state and are not part of the saved aggregate.
Results are durable records keyed by fingerprint in the result store, not
fields inside the document. Drafts may be saved before they are executable.

Artifacts render directly on the canvas as node-less artifact cards, either
carrying artifact references or following a node output. The standalone Artifact
Viewer is deprecated and cannot be added from the toolbar or canvas menu. Saved
viewers retain their rendering, links, modes, and interaction bindings during
the transition. Cards present artifacts and execute nothing. Separate cards may reference the same
artifact. New input connections record one source card identity per artifact reference, with cardless Library contributions marked separately, so editing
or removing one copy does not change another copy’s connections. Older saved
connections without source card identities retain value-based matching. One reference
presents one artifact; a sequence presents them in the order the card passes them
on, and two artifact types never share one card. Passing a card into a node writes an origin on that input, and
the origin stays the executable truth: the card owns the order, so reordering a
bound card rewrites the origin that carries it, and removing the card removes
what it passed in. The reference is durable document state and is never dropped
when the artifact is deleted, becomes inaccessible, or cannot cross a Workspace
or Workspace boundary; the card stays and reports the reference as missing until
the user removes the card deliberately.

Collect replaces selected, unconnected artifact cards with one sequence card.
It requires the same artifact type and schema version, orders cards top to
bottom then left to right, and preserves each contribution in its own input plug,
including separate cards referencing the same artifact or producer output.
Adding an artifact already present in a collection adds another member. Ungroup
replaces that sequence with individual cards in its current order. Neither
operation deletes artifacts. Cards with producer links, viewer bindings, or
input origins must be disconnected before grouping or ungrouping. Tidy-up
changes card positions without changing references or sequence order.

Image cards keep the filename and artifact contract above the image, dimmed
when unselected. Info and action controls sit outside the image. Single values
use one connector ring; sequences use two, including a sequence of one item.

Project commands are validated batches applied against the live head. An accepted
batch is durable as soon as it commits. Checkpoints are immutable snapshots of the
live head that can be restored as a new revision.

### Selection link

A stored presentation binding between two artifact cards: rows or features
selected in the source card are shown in the target card. A link names up to
eight field pairs and its effects (`focus`, `filter`, `highlight`) and lives in
the graph document's presentation beside the cards it joins; removing either
card removes it. Matching is exact: a target row or feature matches when every
paired field equals the selected value, so both sides need a shared key. The
selection itself is per session and never saved. A preview takes part by
publishing its fields and selection and by applying effects; tables and maps do.
The canvas draws a link as a dashed line between its cards, and the card menu
creates, edits and removes it.

### Workbench

The user-facing graph editor and its execution interface. Ordinary node
configuration is rendered on the node from JSON Schema; interactions that own
dynamic graph structure, such as Schema Builder fields and their input plugs,
use a dedicated node body. Nested artifact fields and collection
mapping are selected on each edge. Compatible declared conversion paths are also
stored and displayed on the edge; a unique route may be selected automatically
when the user connects otherwise-incompatible ports. Any Graph can be run directly, and any node can be a Run target: a Run schedules
only the stale part of its upstream closure, so getting one value does not rerun
the Graph. State is shared: every participant sees the same fresh, stale, queued,
running and failed instances and the same active Runs.

Every Project presented as a supported product workflow must be reproducible,
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
