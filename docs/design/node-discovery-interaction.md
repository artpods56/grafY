# Node discovery interaction

- **Status:** Accepted for implementation
- **Date:** 2026-08-12
- **Audience:** Designers and engineers implementing Add node and canvas
  connect-to-empty discovery
- **Document type:** Explanation — interaction decisions for browse and connect
## Summary

Node discovery has two surfaces that share one frontend filtering model:

2. **Continue from {port}** — compact popup when an output drag ends on empty
   canvas, listing only compatible downstream nodes.

Artifact types and collection shapes are the browse source of truth. Existing
port compatibility (`connectionRoutesFor` and collection-mode rules) remains
authoritative for connections. No backend discovery tags or plugin API changes.

## Add node filters

Replace goal categories (`Suggested`, `Add data`, `Transform`, `Analyze`,
`Present`) with:

| Filter | Match rule |
| --- | --- |
| All | Every catalog-visible node (excluding the graph being edited) |
| Text | Any input or output using `scalar.text` or a `text.*` artifact |
| Images | Any input or output using an `image.*` artifact |
| Tables | Any input or output using a `table.*` artifact |
| Spatial | Any input or output using a `geo.*` artifact |
| Prompts | Any input or output using a `prompt.*` artifact |
| Sequences | Declared output shape `many`, or accepted input shapes include `many` |

These families are a frontend projection over exact registered artifact
contracts, not backend discovery tags. A node may appear in several families;
unrecognized plugin artifact namespaces remain discoverable through **All** and
search until the family model is deliberately extended.

Default filter is **All nodes**, sorted by title then stable operator identity.
Search intersects the active filter and scans titles, descriptions, plugins,
ports, configuration fields, artifact titles, and artifact IDs. Clearing search
preserves the filter.

## Result and detail density

Result rows show purpose only: title and a two-line description. Selecting a
row inspects without mutation. Insertion happens from the inspector action, or
from Enter on the focused result.

The inspector renders a canvas-faithful preview of the selected node: the same
chrome, port rail, and configuration fields the operator will have on the
graph. Input ports sit to the left and output ports to the right. Port color
comes from the registered artifact type; sequence shape is marked on the tab
and handle. Nodes with no inputs or outputs explicitly read **Start** or
**End**. This makes the catalog visual without requiring plugin authors to
supply bespoke icons or discovery tags.

Default inspector (operators): the node preview, purpose, required inputs,
produced outputs, and configuration requirements. **Works with** sits under
that summary and is scoped to one port at a time — the first input by default,
or a port chosen from the preview or the Works with menu. Suggested nodes are a
single list; choosing one inspects that node in the catalog. Artifact IDs,
schema versions, operator identity, cardinality rules, conversions, and full
port/config schema live behind **Technical details**.

## Continue from {port}

When a connection starts from a supported output handle and ends on the empty
pane:

1. Capture source node, encoded source handle/feed, client anchor, and
   flow-space drop position.
2. Materialize a canvas-faithful ghost of the first compatible node at the
   insertion point, with a dashed wire from the source port to the receiving
   input. Hovering or focusing another row replaces that ghost in place.
3. Open a compact picker titled **Continue from {port title}**, placed beside
   the ghost so it does not cover the preview. Search is focused. Rows use the
   same purpose-only treatment as Add node: title and a two-line description.
   The picker shell uses the same hairline border as canvas nodes. The
   previewed row is a quiet wash with no ink box — the canvas ghost carries
   “this one.”
4. List each compatible downstream node once.
5. One route → selecting the node creates and connects immediately.
6. Several routes → a second step lists exact input/route choices; the ghost
   stays and highlights the chosen input. No mutation until confirmed.

Placement: ghost top-left at drop x, vertically centered on drop y using shared
default node dimensions. The picker sits to the right of the ghost, or to the
left when the right edge of the viewport is too tight. Generic artifact
bindings go into the initial node document. `add_node` and `add_edge` submit
together through the semantic authoring path.

Cancel without mutation on Escape, outside click, Back, graph change, or
permission loss. Input-origin producer discovery remains deferred.
