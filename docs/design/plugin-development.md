# Node family development

A family under `plugins/` is application code loaded into the API process under
[ADR 0017](../adr/0017-plugins-are-application-code-in-process.md). It shares the
workspace `grafy-core` dependency and deployment build identity with families in
`libs/workbench`. There is no separate runtime publication step.

## Dependency and registration boundaries

The family exports one `Plugin` containing node declarations, artifact contracts,
and resolver/writer factories. The API composition owns the finite registration
tuple. An absent family has no catalog entry or execution route. SQL remains
absent pending safety review; Python execution and its presets are retired.

Families import core contracts and ports. They never import `grafy_api`, HTTP
routers, or concrete storage implementations. Factories receive the active
Workspace storage and unit of work through `PluginRuntimeContext`. Secrets come
from declared `NodeSecretInput` slots, never from config fields or environment
variables containing provider credentials.

An artifact type has one owner. Consumers declare an exact dependency on its
contract rather than defining a second type id for the same payload. Shared
handlers for an identical type may be deduplicated at composition; differing
artifact contracts must fail registry validation. Upload extensions belong to
file-format contracts. Interpretation stays a visible decode or import node.

## In-process safety constraints

Every URL named in graph configuration must dial through `grafy_core.egress`.
The guard resolves and validates the destination, and the connection must use
that validated address. Only deployment configuration can grant access to a
private destination. Graph authors and Workspaces cannot widen that grant.

Native parsers and converters run through bounded subprocess helpers. They must
have concurrency, wall-time, CPU and address-space limits, and a scrubbed
environment. Cancellation must finish native work before its temporary directory
is removed. SQL stays unavailable until its worker and connection paths have
been reviewed for in-process hosting.

Deterministic nodes may declare `NodeCachePolicy.EXACT`. The runtime combines
config, input references, artifact bindings, opaque secret revisions and the
implementation build digest in the cache key. Mutable remote reads use
`NodeCachePolicy.NEVER`. A deployment invalidates earlier node implementations,
including expensive GIS and provider work.

## Stored-data compatibility

Family slugs such as `external.gis` remain stable because saved documents and
secret bindings already contain them. New graph nodes use `kind: builtin` with
operator id and version, without release pins. Reads normalize old Plugin nodes
without changing immutable checkpoints. Keep artifact readers compatible with
historical artifact metadata even when the producing operator is unavailable.

The retained release and publication modules support historical data during the
first milestone. They do not register executable families. Their tests and the
archived notes SDK wheel are independent of live family dependencies.
