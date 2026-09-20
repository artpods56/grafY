# Workbench side panel: the double sidebar

Status: implementation handoff for #79 and the drawer area that follows it.
Audience: whoever builds the next panel view.

## 1. The problem

The Workspace rail (`grafy-workspace-rail`) is a real column: fixed, flush to the
window edge, full height, `#FFF`/`#111` surface, 1px divider, 8×10px rows at 13px
type, uppercase 11px section labels.

The first Artifacts drawer was a Base UI `Drawer` popup portalled on top of the
canvas. It had its own surface, its own shadow, its own header height, a rounded
card edge, and it covered part of the canvas instead of taking space from it.
Next to the rail it looked like furniture from another house — the same widget
twice, agreeing about nothing.

Two things were missing at once:

1. **The pair.** A drawer that behaves like the second pane of one sidebar
   instead of an overlay parked in front of the canvas.
2. **The area.** `#79` asks for one Artifact Library tree today, and the same
   surface will carry Graph templates and whatever comes after. Building a
   one-off drawer per feature reproduces problem 1 forever.

## 2. The shape

```
window ────────────────────────────────────────────────────────────────────
┌──────────────┬───────────────────┬──────────────────────────────────────┐
│ Workspace    │  Workbench        │                                      │
│ rail         │  side panel       │   Canvas (gets the rest)             │
│ (app nav)    │  (work surface)   │                                      │
│              │                   │                                      │
│ fixed 200px  │  fixed 240–420px  │   shell = 100% − rail − panel        │
│ #FFF / #111  │  #FFF / #111      │   #FFF / #111 grid                   │
│ 1px divider  │  1px divider      │                                      │
└──────────────┴───────────────────┴──────────────────────────────────────┘
        └──────────── one continuous sidebar unit ────────────┘
```

The two columns are siblings that share a contract: same surface token, same
hairline divider, same row metrics, same hover and selection treatment, no
shadow. A shadow means "floating above the work"; a docked pane must never have
one.

The panel is **docked, not overlaid**: the canvas is a real neighbour and loses
width when the panel is open. Closed means not rendered, and the canvas takes
the space back.

```
   --grafy-rail-width        --grafy-side-panel-width
   ┌──────────┐              ┌─────────────┐
   │  rail    │              │   panel     │
───┴──────────┴──────────────┴─────────────┴──────────────────────────────
                                       ▲
                          resizer (240…420px, persisted)
```

Position follows the rail through CSS custom properties on `:root`, the same
mechanism the rail already uses, so collapsing the rail slides the panel left
with it:

```
:root                        --grafy-side-panel-width: 0px
@media (min-width: 1100px)   --grafy-side-panel-width: 276px   /* first visit */
:root[data-side-panel=open]  --grafy-side-panel-width: var(--grafy-side-panel-expanded-width)
:root[data-side-panel=closed] --grafy-side-panel-width: 0px
```

Below `1100px` the docked column would starve the canvas, so the panel becomes
a slide-over with a backdrop and the shell stops reserving width.

## 3. Anatomy

```
┌───────────────────────────────┐
│ [▦ Artifacts] [▤ Templates]   │  view switcher · collapse ▸
├───────────────────────────────┤
│ ⌕ filter…              ↕ ⬆    │  filter · sort · upload
├───────────────────────────────┤
│ ▾ 📁 images              3    │  standing folder + count
│    ▣  photo.png               │  image row: thumbnail
│       128 KB · uploaded       │
│    ▣  scan.jpg                │
│ ▸ 📁 tables              0    │  empty standing folder still renders
│ ▸ 📁 text                1    │
│ ▸ 📁 models              0    │
│ ▾ 📁 other               1    │
│    ▣  mystery.bin             │
│       stored as a blob        │
├───────────────────────────────┤
│ PROVENANCE                    │  inspector for the selected row
│ uploaded · scan.jpg           │
│ [Open in execution history]   │
└───────────────────────────────┘
```

## 4. The seam

The panel is one shell plus a fixed set of views:

```ts
type SidePanelView = {
  id: SidePanelViewId;      // "artifacts" | "templates"
  label: string;
  icon: LucideIcon;
  render: (context: SidePanelContext) => ReactNode;
};
```

`SIDE_PANEL_VIEWS` is a module-level array, not a registry. A view is a function
that receives `{ workspace, workspaceId, onOpenGraph, onOpenRun }`. Adding a
third view means adding one entry and one component; nothing else moves. There
is no registration API, no provider, no ordering protocol — see [R41].

The Artifacts view keeps its own data seam one level down. The Library list API
returns a flat list; the folder tree is a **projection**, not stored state:

```
listLibraryArtifacts(workspaceId)        LibraryItem[]  (flat, server truth)
              │
              ▼
  libraryFolderPath(item) ──► "images" | "tables" | "text" | "models" | "other"
              │
              ▼
  buildLibraryFolders(items, {query, sort}) ──► LibraryFolderNode[]
              │
              ▼
  LibraryTree (Base UI Collapsible + role=tree)
```

`libraryFolderPath` is the only place that knows how a Library artifact is filed.
#25 will replace it with a Library folder table; that change touches this
function and the tree's node identity, not the tree component, the panel shell,
or the drag contract.

## 5. Decisions

- **Docked over overlay.** The panel takes layout space. Overlay chrome is for
  transient context (Run history, dialogs); the Library is a standing work
  surface and must be laid out like one.
- **Tabs in the panel header, not a third column.** An activity-bar strip would
  push the canvas past 400px of chrome before the first node. A segmented switcher
  in the header keeps the unit two panes wide, which is what "double sidebar"
  means here.
- **Standing folders are always rendered.** Five folders, including empty ones,
  because a filesystem that hides its empty directories is not teaching the
  structure. `#79` states the same acceptance check; the flat-list iteration that
  hid them was wrong.
- **Folders are derived, not persisted.** Type family is the filing rule until
  #25 ships a folder table. The rule lives in one function.
- **Drag stays the contract.** Rows carry `application/x-grafy-artifact` through
  `writeArtifactDrop`; the drop still resolves the port row under the cursor with
  `document.elementsFromPoint`, skipping portals.
- **Keyboard first-class.** `role=tree` with `treeitem`, `aria-level`,
  `aria-expanded`; Arrow keys move, ArrowRight/Left expand and collapse, Home/End
  jump, Enter selects. A file browser you cannot walk with the keyboard is a demo.
- **Upload by click too.** Drag-and-drop alone excludes keyboard users; the
  header upload button posts the same two calls.
- **Collapse is total.** Closed = unmounted. A 40px sliver that is neither open
  nor closed is the worst of both.

## 6. Verification

- `npm --prefix apps/web test` — tree projection, panel shell, both views.
- `npm --prefix apps/web run typecheck`, `npm --prefix apps/web run lint`.
- `npm --prefix apps/web test:e2e` — the drawer opens docked on the left, toggles,
  and a Library artifact drag still lands on an input port.
- Visual check at 1600px, 1280px, and 720px: the two columns must read as one
  surface at a glance; the canvas must not sit under the panel.
