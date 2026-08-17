# Human Plugin authoring (no coding agent)

- **Status:** Direction — not implemented
- **Date:** 2026-08-17
- **Parent:** [workspace-plugins](README.md)
- **Related:** [plugin unification](plugin-unification.md),
  [catalog releases](catalog-releases.md),
  [`examples/plugin-notes`](../../../examples/plugin-notes)

## Summary

The coding agent is an optional author, not a different kind of Plugin. A
human-written Plugin is the same uv project, the same freeze, the same
Workspace catalog.

## Do this

1. Create a uv project (`pyproject.toml`, `uv.lock`, `src/`, `tests/`) with a
   Plugin slug and `function_node`s — the GIS small-node surface, not
   `PluginRuntimeContext` factories that assume the API process.
2. Speak other plugins through **artifact types** (`table.data@1`,
   `geo.map_layer@1`). Do not depend on `grafy-plugin-gis`. Do not add a
   `grafy.plugins` entry point.
3. If you invent a type the host cannot already persist (Pillow `Image`, …),
   ship a writer and resolver **in that project**. They run in the isolated
   runtime, not in FastAPI.
4. Pin a **named profile** (`python-uv`, later `python-uv-gdal`). Wheels go in
   the lockfile; GDAL does not.
5. Publish through Grafy: lock-check, freeze, review, Workspace release. The
   human path is a CLI that points at the directory (`grafy plugin publish
   ./clipper`). Generate is the same pipeline with an agent in front.

Open that directory in git or Cursor whenever you want. Grafy does not own
the working copy; it stores the freeze.

## Do not do this for new Plugins

- Add `plugins/foo` to this monorepo and register
  `[project.entry-points."grafy.plugins"]`.
- `uv add` the Plugin into the API image so FastAPI can `import` it.
- Assume GIS’s in-process GDAL and writers are available inside the node
  process.

That entry-point path is only how **already-bundled host plugins** (GIS, SQL,
OCR, LLM) stay alive until each is moved onto a freeze.

## Until publish-from-directory exists

You cannot complete step 5 in product yet. Still **author as a freezeable uv
Plugin**. Wiring a new Team Plugin through `grafy.plugins` now is work you
will delete, and it puts teammate Python in the API process.

The only exception is a first-party operator that must ship *this week* on
the current host adapter (in-process, API restart, GDAL on the API image).
Treat that as debt on the GIS-shaped backlog, not as the template for “a
plugin outside the agent.”

[`examples/plugin-notes`](../../../examples/plugin-notes) is that template:
no entry point, core artifact contracts, a plugin-owned JSON type with
writer and resolver, profile `python-uv`.
