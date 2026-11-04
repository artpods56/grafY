# ADR 0004: Unify System and Workspace Plugin releases

- **Status:** Superseded by ADR 0005
- **Date:** 2026-08-24
- **Scope:** Plugin identity, publication authority, catalog visibility, runtime
  selection, and compatibility cutover
- **Designs:** [Plugin unification](../design/plugin-unification.md),
  [Plugin development](../design/plugin-development.md), and
  [backend architecture](../design/backend-architecture.md)

## Context

Grafy currently has two lifecycle models for executable nodes. Host-installed
Plugins are discovered from explicit built-ins or Python entry points and run
in the API process without an immutable graph pin. Workspace Plugins are
published as immutable source and OCI artifacts, appear only in their owning
Workspace, carry exact release pins, and run in an isolated container.

That split makes `builtin` and `external` look like durable domain kinds even
though they describe how the current deployment happened to load Python code.
It also means a saved graph cannot name the exact host implementation it used.
Removing a host implementation in a later release can therefore make an old
graph irrecoverable even when Grafy still has an artifact store capable of
retaining old Plugin releases.

The product needs globally available first-party Plugins and Workspace-local
Plugins authored by people or coding agents. Both need reproducible exact
releases. A graph module remains a published graph boundary rather than a
Plugin distribution and must not be forced into this lifecycle.

## Decision

### Use one release model with two visibility scopes

A Plugin release has exactly one scope:

- `system` has no Workspace owner and is visible in every Workspace; or
- `workspace` has exactly one Workspace owner and is visible only there.

The public release pin is `{scope, slug, revision}`. The database uses an
internal UUID primary key so System ownership can remain null while partial
unique indexes preserve independent System and per-Workspace revision
sequences. The internal UUID is not graph identity.

Scope controls ownership and visibility only. It does not choose a runtime.
System distribution metadata is independently one of `bundled`, `optional`,
or `published`; execution policy is independently `host-eligible` or
`isolated-only`. Workspace releases are always `isolated-only`.

Module catalog entries use `entry_kind=module`. They do not have Plugin scope,
distribution, or release pins.

### Separate immutable release facts from mutable selection and admission

Publication appends immutable release facts: source, lock, catalog and
capability contracts, protocol and runtime-profile identities, execution
policy, distribution, publisher attribution, and a retained OCI artifact.
Every System release retains OCI even when it may run in-process.

One mutable family selection points to an exact release and carries a
generation plus published, deprecated, or withdrawn catalog state. Current is
never inferred from the greatest revision. Promotion and rollback move this
pointer without changing a release row. An exact revocation is recorded
separately from family selection: it retains the release and artifacts but
denies execution.

Deprecated and withdrawn families are unavailable for new insertion, while
existing exact pins may continue to run. Revoked exact releases cannot run.
Ordinary selection changes affect new top-level runs. Emergency revocation
also cancels affected active runs or occurs during a maintenance drain.

### Use distinct publication authorities

A Workspace owner with `publish_plugin` may publish only to that Workspace.
The Workspace publication path fixes scope and execution policy; a caller or
coding agent cannot request System scope or host eligibility.

System publication is a separate platform/CI authority with explicit audit
attribution. It stages source and OCI first, produces an exact release, and
does not implicitly select the newest revision. Deployment builds and verifies
an exact host-binding manifest from those frozen bytes before an explicit
promotion. Candidate dependency fetch, tests, and inspection run in a one-shot
publisher sandbox rather than the long-lived API process.

### Derive one effective catalog without origin branches

For a requested Workspace, the effective catalog contains:

1. explicitly selected System releases;
2. explicitly selected releases owned by that Workspace; and
3. published Modules as separate `module` entries.

Catalog facts expose entry kind, Plugin scope, System distribution, exact
selected revision, and a derived runnable or disabled reason. `builtin` and
`external` are transitional compatibility fields only; they are removed after
System baselines and graph pins are cut over. Workspace Plugin families may not
shadow a System slug, operator identity, artifact contract, or conversion.

### Resolve exact releases before selecting a runtime

Compilation first resolves the exact scoped pin and applies one shared release
admission decision. Catalog readiness, compilation, and the defensive runtime
boundary use that same decision so a crafted request cannot bypass revocation,
protocol, profile, capability, artifact-format, or adapter checks.

The in-process fast path is allowed only when all of these are true:

- the release is System and `host-eligible`;
- it is the exact selected release in the run's captured selection generation;
- the deployment explicitly allowlists it; and
- the loaded catalog, descriptor, loader target, and build bytes match the
  baked host-binding manifest.

A mismatch fails readiness or startup; it never retargets the pin to whatever
code is installed. Historical or non-allowlisted System releases and every
Workspace release require their retained OCI artifact. SQL remains
`isolated-only` because validating a query is not a process sandbox. [R45: Untrusted Query Isolation]

### Make artifact and invocation contracts portable before moving code

Serialized releases carry exact artifact schemas, materialized JSON shapes,
projections, exports, portable bundle formats, referenced contract identities,
and conversion declarations. Runtime support is selected by exact format and
version rather than an artifact-type name whitelist. Isolated execution
preserves the same bounded progress, terminal errors, cancellation, cache
identity, and provenance semantics as in-process execution.

First-party implementations move to `plugins/<family>/` only after those
contracts are producer-neutral. Core retains shared contracts and runtime
primitives, not first-party business implementations. Graph-module boundary
operators remain outside Plugin baseline publication.

## Migration and cutover

Existing release rows become Workspace releases without changing their slug,
revision, digests, source keys, or runtime artifacts. Legacy two-field pins are
read once as Workspace pins and rewritten in saved graphs, saved revisions,
collaborative heads, templates, and recoverable submitted execution requests.
The representation migration does not create a logical graph revision.

Before removing host discovery, an operator command publishes and verifies one
immutable System baseline per enabled family. A maintenance-window backfill
uses the exact verified operator-to-release map to pin known Plugin nodes.
Module boundary nodes are excluded and unknown nodes remain inert. Ambiguous or
missing mappings fail without rewriting data.

Pre-cutover host executions did not record loaded bytes, so migration does not
invent exact historical provenance. Old provenance is marked
`legacy_unpinned`, and reusable materializations and invocation-cache entries
for backfilled nodes are invalidated. Database, release objects, artifact
storage, and the migration manifest form one backup and rollback unit.

## Consequences

### Positive

- A graph names the same exact Plugin identity regardless of its current
  runtime adapter.
- Global first-party availability and Workspace-local agent authoring no longer
  require separate Plugin taxonomies.
- Removing a current host implementation does not remove retained historical
  execution when its OCI policy remains supported.
- Distribution, ownership, lifecycle, and execution policy become inspectable
  independent facts.
- Module publication keeps its graph-specific semantics instead of pretending
  to be a code package.

### Negative

- System release promotion becomes a deployment workflow involving source,
  OCI, a host-binding manifest, and explicit selection rather than a Python
  import alone.
- Every first-party artifact and capability needed by historical OCI execution
  needs a portable contract and adapter.
- The cutover needs a maintenance window, coordinated backups, cache
  invalidation, and a verified baseline map.
- Exact revocation and lifecycle selection add mutable policy records beside
  otherwise append-only release data.

## Alternatives considered

### Keep built-ins unpinned and pin only Workspace Plugins

Rejected because an operator id and version do not identify the loaded host
bytes. Old graphs would continue to depend on mutable application releases.

### Treat built-in, external, Workspace, and Module as four Plugin scopes

Rejected because built-in and external describe installation mechanisms, while
Module is a graph publication kind. Combining these axes would make visibility
and runtime selection implicit again.

### Run every System release in-process

Rejected because historical versions cannot safely coexist as ambient imports,
and SQL or other untrusted execution must remain outside the API process.

### Run every Plugin in a container

Rejected as the only policy because a verified exact current first-party build
can use a simpler and faster in-process adapter. The retained OCI artifact is
still mandatory so that optimization never becomes the sole copy of a release.

### Use a hidden global Workspace for built-ins

Rejected because a sentinel tenant would mix product authorization with
platform ownership, complicate foreign keys and catalog visibility, and make a
global release look Workspace-owned when it is not.
