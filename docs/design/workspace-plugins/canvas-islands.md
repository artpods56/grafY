# Several graphs on one canvas

- **Status:** Direction — not implemented
- **Date:** 2026-08-17
- **Parent:** [workspace-plugins](README.md)
- **Related:** [modules conceptual model](../modules-conceptual-model.md),
  [collaboration ADR](../../adr/0002-server-authoritative-workbench-collaboration.md)

## Summary

Do not put multiple publishable subgraphs inside one Saved graph. If variants
need to sit next to each other, **load multiple Saved graphs onto one
canvas** as islands. Each island remains one document, one collaboration
room, at most one Module.

## Why not subgraphs-in-one-document

Today **one Saved graph is the source of at most one Module**, and that
Module’s body is the **whole document**. That is explicit:

- Conceptual model: a Saved graph “may be the source graph of zero or one
  Module”; a subgraph is “authoring structure inside a Saved graph, not a
  durable object.”
- Unique key `(workspace_id, source_graph_id)`.
- Callable identity `graph.module.{graph_id}@{revision}` — no subgraph id.
- Publish walks **every** Module Input/Output on the canvas as **one**
  contract. Nested execution runs the full document.

Two disconnected recipes on one canvas would not become two Modules. They
would become one lumpy contract whose body is still the entire graph.

Shared-core “slightly different” variants are worse: the body is not a clip.
Publishing two Modules from that either duplicates the shared nodes or
invents subgraph-includes-subgraph.

Existing tools for variants that share a core:

- One Module with two outputs
- Disabled edges (variants in **revisions**, not side by side)
- Two graphs, or one graph that **calls** two Modules

## The better split: canvas islands

Keep **one Saved graph = one document = at most one Module**. Let the
**canvas** show more than one of those documents.

Then variants are two graphs (two heads, two publish identities), just
visible at the same time.

Today the Workbench is one session: one `(workspace_id, graph_id)` room, one
collaborative head, one React Flow document, one run overlay. ADR 0002 says
collaboration does not introduce independently hydrated canvas islands.
Loading a second graph is a **view** change, not a Module change.

### Fine if islands stay separate

- Graph A and Graph B keep their own rooms, revisions, secrets, execution.
- Canvas places them as two islands (offset, or a frame per graph).
- Renderer namespaces node ids by `graph_id` so they do not collide.
- Publish / Module / Generate target **whichever island is focused**.
- **No edge from A to B.**

That is Workbench composition: N graph sessions plus layout. The domain
model stays still.

### Hard if islands can be wired together

An edge across two Saved graphs is a new object (whose revision, whose
execution). That is worse than subgraphs in one file. Not in the first cut.

### Cheaper cousins already nearby

- Open the variant in another tab.
- A folder of variant graphs in the Workspace library.
- A parent graph that calls two Modules.

## First implementation slice

Multi-session Workbench: two (or N) graph rooms, camera shared, focus
selects the active document. No cross-graph edges. No change to Module
identity.
