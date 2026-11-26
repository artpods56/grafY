# Selection links

A selection link shows the rows or features selected in one artifact card in
another card: click a volost in a table and the map zooms to its centre. The
vocabulary entry is in `CONTEXT.md` (Selection link). This note records the
decisions that the code does not make obvious.

## What is stored and what is not

The link is a presentation binding in the graph document
(`GraphPresentationBinding`): source card, target card, up to eight field pairs
and its effects. It travels with the rest of the presentation through
`replace_presentation`, so collaborators, checkpoints and agents see the same
links, and the server already refuses a link whose card is missing.

The selection, and the fields each card publishes, are runtime state. They live
in one pure reducer (`artifacts/selection-links/selection-links-reducer.ts`)
next to the link editor's phases, and are never saved. Saving or removing a link
is an effect the adapter hook carries out with `commitArtifactViewers`, the same
commit path as every other card edit, so a read-only session cannot change
links but can still use them.

## Which previews take part

`selectionLinkCapability(previewKind)` is the one place that says so. A preview
takes part by implementing `ArtifactViewerInteractionContext`: it publishes its
fields, reports a selection as field values, and applies the effects it lists.
Tables (filter, highlight) and maps (focus, filter, highlight) do today. A new
preview, such as a scan with clickable rows, joins by implementing the context
and adding a case there; nothing else changes.

## Matching is exact

A target matches when every paired field equals the selected value
(`targetRowsForBinding`, then `/table/query` or `/geo/query`). There is no fuzzy
matching here: values that only nearly agree are made equal in the graph first,
for example by carrying the reference columns through a match step. The editor
suggests one pair, preferring a field whose id or title matches on both sides
and two text fields over others, because a numbering column shared by both
sides is often blank in OCR output.

## Feedback loops

Previews republish their fields whenever their interaction context changes, and
the context changes whenever any selection does. The reducer therefore returns
the identical state for equal fields or an equal selection, so the adapter does
not re-render and the loop stops after one round.
