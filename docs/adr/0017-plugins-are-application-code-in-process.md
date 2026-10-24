# ADR 0017: Plugins are application code loaded in-process

- **Status:** Accepted (ends Plugin releases, installations, selections, revocations,
  publication, the Docker sandbox, the egress broker and the Python node)
- **Supersedes:** ADR 0005, ADR 0006, ADR 0012, ADR 0013, ADR 0015
- **Amends:** ADR 0007 (its builtin-family / Plugin split collapses into one kind of
  application-owned node family)
- **Related:** `docs/design/plugin-unification.md`, `docs/design/plugin-development.md`,
  `CONTEXT.md` (Plugin, Builtin family)

## Context

A **Plugin** used to be a separately published thing: a source tree built into an OCI
image, pushed to a registry, promoted to a **release**, **selected** for the System
namespace, **pinned** per node inside a saved graph, and executed in a Docker sandbox
whose traffic left through an egress broker. ADR 0007 had already made builtin families
application code identified by the deployment build digest, and ADR 0015 had already made
every Plugin System-owned, so the whole release lifecycle had exactly one publisher: this
repository.

Two reasons justified that machinery, and neither survives.

1. **Arbitrary user code.** `python.transform` runs code written by whoever saved the
   graph, so it needed a sandbox. It was the only operator that did. Once it is gone, no
   user-authored code executes inside the platform, and the isolation no longer buys the
   security it was designed for.
2. **Independent versioning.** A pinned node keeps running the exact release it was saved
   against. On this repository that cost more than it returned: roughly 15.8k lines of
   backend production code, 22k lines of tests, four tables, 175 release-pin references,
   nine vendored SDK wheels and two Compose stacks. Worse, it split single domains across
   a process boundary — a Plugin writes `geo.raster_scan` while the API serves that
   artifact's tiles — so working on one feature meant working on both sides of a wire
   format and every edge case where they disagreed.

n8n draws the same line: built-in nodes are in-process packages and only Code-node user
code runs in isolated task runners.

## Decision

### Every Plugin is application code

The packages under `plugins/` are uv workspace members of this repository. They depend on
`grafy-core` from the workspace rather than on a vendored wheel, and they are installed
into the API process. Each still exports a `Plugin` object, and the composition root
installs them into the same `PluginRegistry` as the `libs/workbench` builtin families,
from one static tuple. Development, tests and production take the same path;
`GRAFY_DEV_PLUGINS` and the checked-in System inventory are gone. A family absent from the
tuple does not exist.

Families keep their own package and their own third-party dependencies, so a heavy native
or provider dependency set stays out of `grafy-workbench`. What they lose is the ability
to be versioned, published, or executed somewhere else.

### Node identity is the deployment build digest

A Plugin node identifies its implementation the way a builtin does:
`BuiltinImplementationIdentity(build_digest)`, the digest of the source archive the
deployed image was built from. `PluginImplementationIdentity`, the `plugin` node kind and
`plugin_release_pin` leave the saved-graph document, the collaboration command set, run
requests, the node catalog and the cache keys. `_node_execution_signature` and the
invocation-cache key take that identity like every other node does, so a cache hit against
code that has since changed is not reachable.

### There is no sandbox and no release lifecycle

Removed: the Docker plugin runtime with its admission, artifact-transport and network
policy modules, the egress broker, OCI publication and the publisher registry flow,
releases, installations, selections, revocations, the four plugin tables, the runtime
capability manifest, the Platform Access Token that authenticated publication, and the
vendored SDK wheels with `just sdk-wheel`.

### The Python node is removed

`external.python` goes: `python.transform`, `python.inspect`, the apply and inspect
service and routes, and the presets under `libs/workbench/presets/`, which are Python
source. So does `external.python`'s functionality in saved graphs: Split text, Replace
text, Join text and As Markdown do not come back as builtin operators. A Saved Graph that
still contains a `python.*` node fails to compile with a diagnostic that names the node
and its operator, exactly as the operators ADR 0013 retired; its document and historical
revisions are kept as they are, not rewritten.

### The safety properties move into code

The sandbox network policy protected internal hosts from user-supplied destinations. Each
destination now carries that check where it is dialed.

- **One egress guard.** `grafy_core.egress` rejects embedded credentials and query
  strings, resolves the host, refuses the address set unless every answer is a global
  address, and pins the connection to one of those answers while TLS validates the
  original hostname. It generalises what WMS and WFS already did, and applies to the LLM,
  Mistral and Typesafe `base_url`, to WFS and WMS, and to the SQL node's PostgreSQL
  `host`. The deployment's own Postgres, MinIO and Keycloak are unreachable from node
  configuration because they are not global addresses.
- **Operators allowlist, authors never.** Destination policy is one operator-owned
  setting listing exact trusted destinations. Node configuration, a graph and a Workspace
  can never widen it. This is what replaces the sandbox's network namespace: a self-hosted
  private PostgreSQL or a local model server is reachable by declaration, not by default.
- **The DuckDB subprocess worker is unchanged**, with its rlimits and its DuckDB
  lockdown, because user-authored SQL is still executable code that must not run in the
  API process.
- **Native work stays out of process and gets bounded.** GDAL already ran as
  `gdalinfo` / `gdal_translate` / `gdal2tiles.py` subprocesses. Those invocations move to
  a bounded subprocess pool with an address-space and CPU cap, a wall-clock timeout, a
  concurrency limit and an environment scrubbed of credentials, so a segfault or an OOM
  kill inside libgdal cannot take down the API worker holding collaboration websockets.
- **Node secrets are untouched.** The additional authenticated data (v1, v2) covers
  workspace, graph, node, operator id and version, secret name and dependency values —
  never a release pin — so stored ciphertext decrypts as before. Only where a node's
  secret *declarations* come from changes: the in-process registry, not a release
  descriptor.

### Existing data stays readable without a rewrite

Saved graph documents, graph revisions and collaboration heads are append-only
checkpoints, so nothing rewrites them. Reading normalises instead: a `plugin_release_pin`
key is dropped and `kind: "plugin"` is read as `kind: "builtin"` before validation, and
the same normalisation covers recovered run requests. The document keeps `schema_version`
7 on purpose, so the previous code can still parse documents the new code writes.
`UpdateNodePluginReleaseCommand` leaves the command union; API and Workbench ship in the
same deploy, so a stale client is rejected rather than silently re-pinned.

Stored artifact provenance keeps whichever identity wrote it; no read path validates that
metadata dict, so it stays as historical fact. Materialized-output signatures and
invocation-cache keys change shape, which makes outputs produced by sandboxed runs read as
stale; they are recomputed on first execution after the deploy.

The four plugin tables and `platform_access_tokens` are dropped by one migration whose
downgrade recreates them empty. Rolling back the application after that migration is
forward-only, because the code it would roll back to needs releases that no longer exist.

## Consequences

- **Every deploy invalidates Plugin-node caches.** The build digest covers the whole
  source archive, so a deploy drops the invocation cache and the materialized outputs of
  every Plugin node, including expensive LLM and GIS work that previously survived a
  deploy because its pin had not moved. This is accepted as the price of one identity
  rule; a per-family source digest is the obvious later refinement and is deliberately
  not part of this decision.
- **The API image grows and moves.** It installs every family and gains GDAL
  (`gdal-bin`, `python3-gdal`, `python3-numpy`, `python3-pil`). GDAL 3.8 is the floor the
  GIS plugin needs, so the base moves from Debian bookworm, which ships 3.6, to trixie.
- **The API dials from the host's own network.** With no Docker network namespace behind
  it, the guard is the mechanism and the deployment's egress restriction becomes the
  backstop rather than the enforcement point. `docs/deploy/*` says so.
- **Local and self-hosted destinations need a declaration.** Loopback model servers and
  private PostgreSQL hosts were reachable from a sandbox with no configuration; they are
  reachable now only through the operator allowlist.
- **The `external.*` slugs stay.** They are opaque identifiers recorded in stored
  documents, catalog responses and secret bindings, and renaming them would rewrite user
  data for no behavioural change.
- **Domain-module ownership becomes possible.** With the producer and the consumer of
  `geo.raster_scan` in one process and one dependency layer, a `geo` module can own its
  nodes, its artifact types and its tile route. That move still needs its own decision
  about which layer may own an HTTP router, and this ADR does not settle it: family
  packages keep importing nothing from `grafy_api`, and the boundary test keeps that
  direction enforced. Tile-on-demand behind
  `/v1/workspaces/{ws}/artifacts/{id}/geo/raster/{z}/{x}/{y}.png` is out of scope here and
  nothing in this decision blocks it.
