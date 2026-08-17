# Plugin unification (isolated, agent-authored)

- **Status:** Direction — not implemented. Records decisions from the
  generated-node prototype, not the current runtime.
- **Date:** 2026-08-17
- **Audience:** Engineers changing plugin discovery, generated-node authoring,
  catalog identity, or isolated execution
- **Document type:** Explanation — intended architecture and boundaries
- **Related:** [agent-authored nodes](agent-authored-nodes.md) (current
  prototype), [plugin development](plugin-development.md) (current in-process
  host adapter), [modules conceptual model](modules-conceptual-model.md),
  [backend architecture](backend-architecture.md)

## Summary

A **Plugin** is a uv-managed project: `pyproject.toml`, `uv.lock`, typed node
modules, tests, and any artifact types that project owns. Canvas Generate
always lands in a Plugin, even when that Plugin contains a single node. The
coding agent authors that project; humans review a freeze; graph execution
runs the freeze in isolation. FastAPI never imports Plugin Python.

That is the same object as today’s `plugins/gis` *shape* (family of nodes and
types under one slug) and today’s generated-node *trust model* (lockfile,
review, isolated Docker runtime). It replaces two accidental products:

- one-off `generated.node.<uuid>` projects that are not Plugins
- in-process `grafy.plugins` entry points as the long-term way Team-authored
  code reaches the catalog

Host plugins already in the monorepo (GIS, SQL, OCR, LLM) keep working through
the current in-process adapter until each is moved onto the same isolated
path. **Module** stays a published subgraph. It is not a Plugin.

## What “package” means

In this note, **package** means the Plugin’s project tree — the directory a
developer can open in Cursor:

```text
<plugin>/
    pyproject.toml
    uv.lock
    src/...
    tests/...
```

It is not a wheel installed into the API process, not the content-addressed
`tar.gz` alone, and not a subgraph. Grafy stores an immutable **freeze** of
that tree (source archive + locked `.venv` in a runtime image). The tree is
what you edit; the freeze is what a graph run trusts.

Those are two views of the same Plugin, not two products. A checkout from
Grafy and a git clone of the same project are both valid working copies.
Publication always creates a new freeze from exact bytes, then human review.

## Why unify

Canvas Generate today creates a uv project per node with identity
`generated.node.<uuid>`. Host plugins today are Python distributions loaded
into FastAPI from entry points. The jobs people actually describe — “a family
of nodes that share a contract, typed like GIS, editable outside Grafy, usable
across graphs, eventually across Workspaces” — are one Plugin job. Keeping
both identities makes Generate a special case and makes “write a plugin”
sound like `apt` on the API host.

One uv project is simpler than a generated node *and* a plugin wrapper.

## Catalog and identity

- Plugin slug is stable inside a Workspace (`clipper`, not a random UUID).
- Each node is `operator_id@version`, namespaced by that slug, the same way
  `gis.features.to_table@1` works today.
- The catalog origin for Team-authored Plugins is the Workspace, not
  process-global `external`.
- `PluginOrigin.AGENT` is how a revision was authored, not who may use it
  after publish.
- Graphs pin exact node revisions. Publishing a later revision does not
  silently retarget other graphs.

The first Generate in a thread either creates a Plugin (one node) or adds a
node to an existing Plugin in that thread. There is no Generate path that
produces a node outside a Plugin.

## Typing

Nodes look like today’s `function_node` surface: Pydantic config, input, and
output models with `InPort` / `OutPort` bound to artifact types. The canvas
sees the same **NodeSpec** as host plugins (JSON Schema, ports, origin).

Dependencies on Table, GIS, or core are **artifact contracts** (`table.data@1`,
`geo.map_layer@1`), not `from grafy_plugin_gis import ...` and not a
`grafy-plugin-gis` wheel in the Plugin’s `pyproject.toml`.

Python libraries (`shapely`, `httpx`, `pillow`) are ordinary uv dependencies
in that same lockfile. Native tools (GDAL, Tesseract) are not: see profiles.

## New artifact types

A Plugin may declare new artifact types. A type is not a Pydantic field type.

If a node model holds a value the host cannot already persist — a Pillow
`Image`, a raw numpy array, a custom dataclass — the Plugin **must** register
a writer and a resolver for that artifact type. No writer means the type is
not a catalog type; the node should use an existing type (`image.raster@1`)
or declare one whose payload is inline JSON that the host’s generic
inline writer already understands (as GIS map-layer JSON does today).

Writer and resolver **code from a Team Plugin does not run in FastAPI**. They
execute in the isolated runtime that already has the freeze. The API process
stores `ArtifactRef`s and bytes; it does not `import` teammate persistence.
Until that materialization path exists, Generate may only publish types the
host can already round-trip (current prototype: JSON scalars; next: existing
catalog types; then plugin-owned types with isolated writers).

## Execution

Prefect (or the inline engine) stays the **graph scheduler inside the API
process**. That is where GIS `GdalCli` runs today, because GIS is still an
in-process host plugin. It is not where Team Plugin `src/` runs.

| Code | Where it runs |
| --- | --- |
| Host plugin node (`plugins/gis`, …) | API process (Prefect task or inline) |
| Team / agent-authored Plugin node | Fresh container from that revision’s frozen image |
| Coding agent | Reusable authoring container for the environment |

Authoring Docker and runtime Docker are different lifecycles: dirty long-lived
environment versus throwaway `--network none` container from the freeze.
Graph run does not call `uv`, does not install, and does not start a per-node
HTTP server. Inputs and outputs are bounded JSON (later: refs materialized
inside the sandbox).

## Dependencies

Three layers, never mixed:

1. **Contracts** — catalog artifact types. No extra install.
2. **Wheels** — the Plugin’s `uv.lock`. Installed only at freeze. Graph run
   is offline.
3. **Native / image** — named **profiles**, not `apt` in the sandbox.

Profiles are an ops allowlist of pinned image *digests* (`python-uv`,
`python-uv-gdal`), pulled onto the worker like the API image, never chosen as
a Dockerfile by the agent or a user. Authoring and freeze use the same
profile. Changing GDAL is a new profile; old releases keep the old digest.

Network policy that profiles must not weaken:

- Graph run: `--network none`
- Authoring code and tests: `--network none`
- `uv add` / `lock` / `sync`: argv-allowlisted helper to **one** package
  index the deployment names (internal mirror). Not Docker `bridge` to the
  public internet in production.
- Image supply: the worker host, on an ops cadence — not the node.

Outbound HTTP, secrets, and object-store prefixes remain **capabilities** on
the freeze, fail-closed until an egress proxy exists. A gdal profile does not
grant WMS.

## Review, checkout, publish

The authoring environment is never trusted. The existing clean-room path
stays: export reviewed files, lock-check, locked sync, tests in a disposable
workspace, second workspace freeze, human review of source and capability
digest, then an append-only release.

Capability approval is still explicit. Publication is still explicit.

Humans edit the project tree outside Grafy the same way they edit
`plugins/ocr`. Grafy’s object store holds the freeze, not the canonical
working copy.

## Workspaces

v1 catalog share is the Plugin’s home **Workspace** (every Graph in that
Team). Cross-Workspace reuse is later and should copy a freeze **by value**,
like Module **Import into workspace**: no live link, no process-global
install, destination Workspace reviews or re-approves capabilities as its
own release.

## What this is not

- A Module / subgraph. Recipes stay graphs; operators stay Plugins.
- Importing Team Python into FastAPI, including “just the writers.”
- A public marketplace.
- User-defined base images, arbitrary indexes, or `apt-get` in the sandbox.
- Treating today’s `docker-trusted-development` opt-in as a production
  isolation boundary. Named profiles do not replace gVisor/Kata later.

## Migration

```text
now:    host Plugin (entry point, in-process)
        + generated.node uv project (isolated, not a Plugin)

target: Plugin = uv project, isolated freeze, Workspace catalog
        host entry points = temporary adapter for monorepo plugins
```

Move GIS/SQL/OCR onto isolated execution when a profile can satisfy their
native tools and their writers can run outside the API process. Until then,
the two adapters share NodeSpec and artifact type ids so a Team Plugin can
*consume* `geo.map_layer@1` without *being* `grafy-plugin-gis`.

The implemented Generate prototype remains the execution and review engine
to extend. Its identity and “one node is not a Plugin” rule are what this
note retracts.
