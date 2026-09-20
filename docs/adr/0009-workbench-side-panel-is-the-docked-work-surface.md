# ADR 0009: The workbench side panel is the docked home of work surfaces

- **Status:** Accepted
- **Related:** #79 (Artifacts drawer), #25 (nested Library folders), `docs/design/workbench-side-panel.md`

The workbench keeps one docked left side panel beside the Workspace rail. Library
artifacts and graph templates are views of that panel, selected by its header
switcher; both columns share one surface, divider, row rhythm, and selection
treatment, and the canvas is laid out beside them instead of underneath them.

A work surface that outlives the action that opened it is docked and takes layout
space. A surface that answers one transient question stays a floating overlay.
Run history, dialogs, and node pickers remain overlays; the Artifact Library does
not.

Panel views are a fixed module-level set, not a plugin registry. The Library
folder tree is a client projection of the flat Library list; the filing rule is
one function, which the Library folder table of #25 replaces without touching the
tree, the panel shell, or the artifact drag contract.
