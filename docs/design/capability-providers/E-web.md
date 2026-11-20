# Web: provider plugs and provider-dependent output ports

Part of the capability-provider plan. After C and D. Read `apps/web/AGENTS.md` first.

## Connecting

A service input plug accepts a connector only from a service output that produces its contract key. The check is the same kind of key match artifact plugs already do, using the catalog fields C adds. The connection check lives in `apps/web/src/features/workbench/ui/node-selector/node-compatibility.ts` and in the canvas connection path.

The node selector, opened from an OCR node's provider plug, lists Mistral OCR and Reducto.

A provider node's card shows its settings and key state. It has no artifact preview and no result area.

## Outputs the provider does not produce

With a provider connected, an OCR output port the provider does not produce is drawn muted, with the label "Not produced by Reducto". The feature list comes from the catalog. With nothing connected, every port looks normal.

Existing edges from such a port stay. The downstream node shows "Boxes are not produced by Reducto" as its blocking reason, distinct from "no result yet".

Switching the provider back enables the port. The edges work again. Nothing was deleted.

## Proof

- Component tests for the muted port and the downstream message.
- Before and after screenshots of an OCR node with Mistral connected, and with Reducto connected.
- `npm run check:api` clean after C's regeneration. E does not add another API change.

## ASSUMPTIONS

- An optional consumer output is muted when a connected service provider
  declares `features` and the output's name is absent from that list. Required
  outputs (for example OCR transcription) stay available. Feature strings match
  optional consumer output port names, as D's catalog already reports them.
- A provider node is any node whose outputs are all `kind: "service"`. Its card
  shows settings and key state and omits the execution appendix and run/reveal
  controls.
- The downstream blocking copy uses the **target** input port title, matching
  the run binder: `"{title} are not produced by {provider}"`.
