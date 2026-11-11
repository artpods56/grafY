# Project Graphs on the canvas

- **Status:** Accepted; implemented (issue #197, epic #193)
- **Audience:** Engineers changing the Graph switcher, boundary or call nodes, or
  how the canvas opens a Graph of a Project
- **Related:** [ADR 0020](../adr/0020-projects-hold-graphs-and-results-belong-to-nodes.md),
  [Workbench realtime collaboration](workbench-realtime-collaboration.md),
  [Node discovery interaction](node-discovery-interaction.md),
  [CONTEXT.md](../../CONTEXT.md) (Project, Graph, Call node, Node instance)

This note holds what the code does not say on its own. The rules a Project
enforces (acyclic calls, refused delete, typed interface) live in
`libs/core/src/grafy_core/kernel/project.py`; the canvas mirrors them in
`apps/web/src/features/workbench/model/project-graphs.ts` so it can offer only
what the server will accept and say why when it cannot.

## The canvas shows one Graph, read from the head

A Project room holds one head with every Graph in it. The canvas draws one of
them, and that choice is a projection of the head, never a second copy:
`useSavedGraphLifecycle` remembers which Graph is open (`openGraphId`) and
`openGraphInProject(head, graphId)` re-projects the head onto the canvas. Switching
fetches nothing and does not change the address.

- Switching is refused while a Run is active or the canvas holds edits the room
  has not taken yet; the person is told why instead of losing the edit.
- A Graph another writer removes falls back to the Project's first Graph on the
  next sync.
- The Graph switcher (`ui/GraphSwitcher.tsx`) is a controlled component. The
  Workbench stays the only writer: add, rename and delete are Project commands
  (`add_graph`, `rename_graph`, `remove_graph`) submitted as one batch and
  checkpointed, so a refusal reaches the person in the room's own words.
- Graph names are unique in a Project, case-insensitively. A new Graph is named
  "Graph N" for the next free N.

## Boundary and call nodes are not registered operators

`graph.input`, `graph.output` and the call nodes of sibling Graphs run no family
code, so the API's node registry does not list them. The web extends the registry
it hydrates against (`registryWithProjectGraphs`) with:

- two boundary specs, with a `public_name` (unique per direction in a Graph; a
  new boundary node takes the next free `input`, `input_2`, … from
  `nextBoundaryName`), `required` on inputs, and `description`. The artifact type
  comes from the node's `T` binding, the same generic-port machinery other nodes
  use;
- one call spec per other Graph, whose ports are that Graph's interface in
  document order. A port the Graph left untyped takes any artifact, and each such
  port is its own type variable (named after the port), because a port with
  neither a type nor a variable cannot be encoded as a handle and crashes the
  canvas.

A call node is saved as `kind: "call"`, `operator_id` = the callee Graph's id,
`operator_version` 1. The picker places it with an ordinary `add_node`;
`newNodeKind(spec)` is what sets the kind. The server rejects a cycle when the
Graph is replaced. Specs for Graphs that would close a cycle are kept in the
registry but hidden from the catalog (`catalog_visible: false`), so a call node
already in the document still finds its ports.

The extended registry is held in state keyed by what the catalog depends on (each
Graph's name and interface, which Graphs the open one may call), not recomputed
per accepted command; otherwise every collaborator's keystroke would rehydrate
the canvas.

## An interface change is an issue at the call site, not a refusal

Editing a Graph's boundary nodes is always accepted. A call node whose saved
connections name a port its callee no longer declares hydrates as an **invalid**
node that keeps its edges and lists each missing port. The kernel reports the
same cases as `call_site_issues`. A required input left unconnected is the
existing run-time requirement, not a hydration error.

## Deleting a Graph

A Graph that still has callers cannot be deleted. The switcher refuses before
sending anything and names the calling Graphs; the server refuses again
(`graph_has_callers`) for a caller added in the meantime. The way back from an
accepted delete is checkpoint restore.

## Opening a call

Selecting exactly one call node enables **Open call**: the callee opens and the
canvas keeps a trail of the Graphs it was reached through. **Back** pops it.
While a trail exists, each node's state is read from its instance under that call
path (`call_path` = the call-node ids entered from the root Graph), so the callee
shows its own freshness for that particular call. Opening a Graph from the
switcher clears the trail and shows the Graph's own instances (`call_path` empty).

A Run started from a callee view runs that Graph directly. Calling the same Graph
twice with the same inputs computes once; that single-flight guarantee is proven in
the kernel and run-service tests (`test_two_calls_of_one_graph_with_one_value_compute_once`)
and does not depend on the canvas.

## Traps

- Boundary names must be unique per direction, or the whole command is rejected.
- Floating chrome on a phone sits under the app's mobile header; the switcher
  offsets itself by `--grafy-mobile-overlay-top`.
