# Workspace plugins and multi-graph canvas

- **Status:** Direction — not implemented
- **Date:** 2026-08-17
- **Audience:** Engineers changing Plugins, Generate, catalog, Modules, or
  Workbench canvas sessions
- **Document type:** Explanation — index of intended architecture from the
  2026-08-17 design thread
- **Related:** [agent-authored nodes](../agent-authored-nodes.md) (current
  Generate prototype), [plugin development](../plugin-development.md) (current
  in-process host adapter), [modules conceptual model](../modules-conceptual-model.md),
  [collaboration ADR](../../adr/0002-server-authoritative-workbench-collaboration.md)

This folder is the home for the intended **Plugin** product (uv project,
isolated freeze, Workspace catalog) and the related canvas decision (several
Saved graphs on one canvas, not several subgraphs in one document).

## Start here

| If you need | Read |
| --- | --- |
| What a Plugin is, typing, deps, Docker, profiles | [plugin-unification.md](plugin-unification.md) |
| How a human writes one without the coding agent | [human-authoring.md](human-authoring.md) |
| How it appears in Add node with a revision | [catalog-releases.md](catalog-releases.md) |
| Variants / several graphs on one canvas | [canvas-islands.md](canvas-islands.md) |
| Copy-paste shape | [`examples/plugin-notes`](../../../examples/plugin-notes) |

## Decisions (short)

- A **Plugin** is a uv-managed project. Generate always lands in one, even for
  a single node. FastAPI never imports Plugin Python.
- In-process `grafy.plugins` is a **host adapter to migrate off**, not a second
  create-a-plugin workflow.
- **Module** stays a published subgraph of **one** Saved graph. It is not a
  Plugin and not a second subgraph inside the same document.
- “I want two variants nearby” is **load two graphs onto one canvas** (islands),
  not multiple subgraphs in one document, and not cross-graph edges.
- Catalog share is the home **Workspace** first; copy-by-value into another
  Workspace later.

Nothing in this folder is the running prototype. Generate still uses
`generated.node.<uuid>`. Host GIS/SQL/OCR still load from entry points.
