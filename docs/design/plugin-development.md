# Node family development

A family under `plugins/` is application code loaded into the API process under
[ADR 0017](../adr/0017-plugins-are-application-code-in-process.md) and
[ADR 0025](../adr/0025-packs-and-ocr-provider-architecture.md). It shares the
workspace `grafy-core` dependency and deployment build identity with families in
`libs/workbench`. There is no separate runtime publication step.

## Three plugin kinds and directory conventions

`plugins/` is strictly a backend packaging and dependency boundary — users browse
**Packs**, never raw Python plugin slugs. Every package under `plugins/` falls
into one of three kinds:

1. **Vendor / gateway provider plugins** (`plugins/mistral`, `plugins/reducto`,
   `plugins/litellm_ocr`, `plugins/llm`, future `plugins/tesseract`): grouped by
   vendor or shared model gateway so SDKs, egress contracts, credential verifiers,
   and clients live in one place. Each Provider node implements one
   `@service_contract` from `grafy_core.contracts` in v1.
2. **Heavy native-dependency domain plugins** (`plugins/gis`, `plugins/image`,
   `plugins/table`): broadly reusable domains whose native or third-party
   dependencies stay out of `grafy-workbench`.
3. **Experimental / project-specific vertical plugins** (such as
   `plugins/map_toponyms`): specialized research pipelines whose nodes work
   primarily together or target project-specific endpoints (such as Visual Jev
   or Label Studio). Keeping them in their own plugin package and opt-in Pack
   avoids polluting `grafy-workbench` builtins or forcing premature generic
   abstractions.

Standard internal layout for a vendor/provider plugin:

```text
plugins/<name>/
├── pyproject.toml              # depends on grafy-core (+ grafy-workbench if needed) + vendor/native deps
├── README.md                   # contracts implemented, credentials, egress hosts
├── src/grafy_plugin_<name>/
│   ├── __init__.py             # re-exports the Plugin instance
│   ├── plugin.py               # Plugin(slug=..., title=...) + registrations
│   ├── auth.py                 # NodeSecretInput(s) + credential verifier(s)
│   ├── client.py               # SDK/HTTP transport + egress guard wrapper
│   ├── providers/              # Provider nodes implementing grafy_core contracts
│   └── nodes/                  # (optional) non-provider operators
└── tests/
```

`libs/workbench` holds only broadly reusable, dependency-light, vendor-neutral
builtins and consumer nodes. Shared pooled HTTP helpers (`provider_http.py`) live
in `grafy_core` so both `grafy_api` shutdown hooks and multiple plugins can share
them without cross-plugin imports.

## Dependency and registration boundaries

The family exports one `Plugin` containing node declarations, artifact contracts,
and the `Artifact` declarations that load and store those types. The API
composition owns the finite registration tuple (`apps/api/src/grafy_api/services/families.py`).
An absent family has no catalog entry or execution route. Python execution and
its presets are retired, and there is no SQL family.

Registration rules enforced in `Plugin.node`:
- Every node class must define its own non-empty `__doc__`
  (`node_class.__dict__.get("__doc__")`), so `ABC.__doc__` can never leak into
  the catalog.
- A node with a service output has zero input ports, exactly one service output
  port, and implements one service contract in v1.
- Optional consumer outputs that depend on a provider capability declare
  `RequiresServiceFeature(input_port, feature)`; the runner validates agreement
  generically using the provider's registration title.
- Contracts whose consumers use `ProviderCache` expose an instance method
  `cache_identity() -> ServiceCacheIdentity(deployment, revision, options)`;
  a `None` revision bypasses caching.

Families import core contracts and ports. They never import `grafy_api`, HTTP
routers, sibling plugins, or concrete storage implementations. Factories receive
the active Workspace storage and unit of work through `PluginRuntimeContext`.
Secrets come from declared `NodeSecretInput` slots, never from config fields or
environment variables containing provider credentials.

Adding a new plugin family touches four places:
1. Root `pyproject.toml` (dependencies, uv workspace members/sources, pyright paths) + `uv lock`.
2. `apps/api/src/grafy_api/services/families.py` (`APPLICATION_FAMILIES`).
3. `tests/unit/architecture/test_import_boundaries.py` (`PUBLISHED_PLUGIN_FAMILIES`).
4. Pack assignment (either automatic via `include_providers_for` on an existing
   Pack, or an explicit Pack entry in `apps/api/src/grafy_api/catalog_packs.py`).

An artifact type has one owner. Consumers declare an exact dependency on its
contract rather than defining a second type id for the same payload. Differing
artifact contracts fail registry validation. Upload extensions belong to
file-format contracts. Interpretation stays a visible decode or import node.

## In-process safety constraints

Every URL named in graph configuration must dial through `grafy_core.egress`.
The guard resolves and validates the destination, and the connection must use
that validated address. Only deployment configuration can grant access to a
private destination. Graph authors and Workspaces cannot widen that grant.

Native parsers and converters run through bounded subprocess helpers. They must
have concurrency, wall-time, CPU and address-space limits, and a scrubbed
environment. Cancellation must finish native work before its temporary directory
is removed.

Deterministic nodes may declare `NodeCachePolicy.EXACT`. The runtime combines
config, input references, artifact bindings, opaque secret revisions and the
implementation build digest in the cache key. Mutable remote reads use
`NodeCachePolicy.NEVER`. A deployment invalidates earlier node implementations,
including expensive GIS and provider work.

Every artifact an execution writes records that digest in its metadata, including
each item of a sequence port, because that record is how a later read tells
whether the current build produced an output. A development process has no image
to bake a digest into, so it derives one from its working tree: HEAD plus the
content of every path that differs from it. Restarting an unchanged tree therefore
keeps materialized outputs and cached invocations, and any edit to source moves
the digest. Outside a readable repository it falls back to a per-process digest,
which matches nothing.

## Stored-data compatibility

Family slugs such as `external.gis` remain stable because saved documents and
secret bindings already contain them. Keep artifact readers compatible
with historical artifact metadata even when the producing operator is unavailable.

Nothing here publishes, freezes, or isolates a family: ADR 0017 removed publication, the
Docker sandbox, the guest protocol, the egress broker, and the archived notes SDK wheel
with its `just sdk-wheel` recipe and pinned digest. A family reaches a deployment only
through the workspace dependency that installs its package and the static registration in
`apps/api/src/grafy_api/services/families.py`.
