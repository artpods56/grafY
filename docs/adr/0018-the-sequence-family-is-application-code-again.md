# ADR 0018: The Sequence family is application code again

- **Status:** Accepted (restores the four operators ADR 0013 removed from the
  builtin catalog; amends ADR 0013, itself superseded by ADR 0017)
- **Related:** ADR 0007 (builtin families are application code), ADR 0013, ADR 0017,
  `CONTEXT.md` (Sequence, Artifact sequence, Collect),
  `docs/design/backend-architecture.md` (builtin families)

## Context

ADR 0013 existed to move `image.decode` and `table.import` into published Plugins, and it
took the Sequence family down with it: "Collect, Count, Slice, and Pick item are removed
from the builtin catalog." Those four operators are not file operators and never belonged
to that move. The same paragraph recorded the hole it left: the canvas Collect action
groups unconnected artifact cards into a sequence, and "it does not replace a Collect node
fed by live graph edges."

The hole is load-bearing now that ordered Plugin consumers exist. `gis.map.compose@1` declares `layers` as an `ArtifactRefSequence` of `geo.map_layer@1` on a **non-variadic**
input, and its own model validator rejects a sequence with `ordered=False`. That port
therefore accepts exactly one ordered sequence, and after ADR 0013 nothing in the catalog
could produce one from live edges. A graph holding two **Raster map layer** nodes and one
**Compose map** has no legal wiring.

The canvas Collect action did not cover for the missing operator; it quietly became a
different feature. `Workbench` resolves the action's spec with
`registry.nodes.find(isCollectionSpec)`, and with no `sequence.collect` in the catalog
`collectSelectedArtifacts` fell through to `collectArtifactCards`, which bundles cards in
canvas view state and adds no node to the graph. The button kept its label and lost its
meaning: it no longer produced a sequence any operator could consume.

The machinery for that sequence never left. `ArtifactRefSequence` and its `ordered` flag,
reference shapes `one` and `many`, variadic ports, instance plugs, one-level expansion in
plug order, and map fan-out are all live in `grafy_core`. The four operators themselves
survived as `test.sequence.*` fixtures under `tests/support`, exactly as ADR 0013
instructed, and run in the runtime and artifact suites today. `CONTEXT.md` and the backend
architecture reference both still list Sequence among the builtin families: the catalog
was the only place that had been told. ADR 0017 then removed the reason for the cut,
because there is no longer an independently published, release-pinned home these operators
could have moved to.

## Decision

Sequence returns as an application-owned builtin family under
`libs/workbench/src/grafy_workbench/sequence`, listed in `BUILTIN_FAMILIES`, with its
identities and versions unchanged: `sequence.collect@1`, `sequence.count@1`,
`sequence.slice@1`, `sequence.item_at@1`. It owns no artifact type; `integer@1` stays a
declared dependency.

Identities stay unchanged on purpose. A saved graph that ADR 0013 told its owner to rebuild
now compiles and runs, so `scripts/audit_builtin_cleanup.py` drops all four operator ids
along with the `rebuild_with_artifact_cards` action it existed to report. Reporting them
would have sent owners to rebuild working graphs.

Ordered consumers keep the rule ADR 0013 left them with. `layers` and every future
cross-item consumer stays a direct, non-variadic `many` input; Collect is how a graph turns
N producers into one ordered sequence. Making those ports variadic instead would move order
into saved-edge bookkeeping, where the user can neither see nor edit it, and would re-open
the same decision in every consumer that wants a sequence.

The `test.sequence.*` fixtures stay where they are, so runtime tests can still exercise a
sequence producer that is deliberately absent from the production catalog.

The web stops hiding the operator. `catalogNodeSpecs` filtered `sequence.collect` out of the
node catalog because "collections are made from artifacts on the canvas, not picked here",
which described a composite card group and does not describe a node that live edges feed.
Grouping needs the cards to exist first, so that filter left no way to place an empty Collect
and wire producers into it. Both doors now write the same operator.

One correction comes with the port. `sequence.item_at` is registered with
`cache_policy=NodeCachePolicy.EXACT`. In both the deleted production module and the fixture
the argument was the enum class rather than the member, and `execution/node_execution.py`
tests that field with `is`, so Pick item silently never cached. Restoring the family is the
point at which the intent gets written down.

## Consequences

The canvas gains four catalog entries and no new concept: ordering across a Collect comes
from explicit plugs, which the graph already stores and the card already shows. Collect
expands nested sequences one level, refuses a mixed artifact type, and clears `ordered` if
any source was unordered, so an unordered source still cannot reach Compose map.

A sequence can now start either way: placed empty from the palette and wired up, or grown
from selected cards by the canvas action. Ungrouping still returns a collection to cards.

This restores the sequence containers only. ADR 0013's other removals stay removed: the
text presets, Normalize table text and Fuzzy match tables do not come back, and the file
operators stay application-owned per ADR 0017 rather than returning to publication.
