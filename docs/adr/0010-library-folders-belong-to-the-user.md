# ADR 0010: Library folders are the user's, filed through one API seam

- **Status:** Accepted (supersedes the folder-model paragraph of ADR 0009)
- **Related:** #79 (Artifacts drawer), #25 (nested Library folders), `docs/design/workbench-side-panel.md`

The Artifact Library is a tree the user owns. Folders are created, renamed, moved
and deleted in the side panel, nest to any depth, and an artifact that is not
filed sits at the root. Nothing about the tree is derived from the artifact's
type: type picks the row icon and nothing else.

ADR 0009 had the tree as a client projection of the flat Library list, filed by a
`images / tables / text / models / other` rule. That rule is withdrawn. Five
folders the user never made are an artifact-format leak into the interface, and
they cannot hold the structure a workspace actually has (a survey's photos do not
live beside its salinity tables because both are "data").

Decides:

- **One contract, `libraryFoldersApi`.** `listTree`, `createFolder`,
  `renameFolder`, `deleteFolder`, `moveFolder`, `moveItems`. A placed artifact is
  `LibraryItem & { folder_id: string | null }`. The rules that a signature cannot
  carry are errors: `LibraryFolderNotEmptyError`, `LibraryFolderCycleError`,
  `LibraryFolderNameTakenError`.
- **A folder deletes only when empty.** Deleting a subtree that holds work is not
  a click's worth of consequence. The menu states "empty it first" and the API
  refuses.
- **A folder never moves inside itself.** `moveFolder` rejects the folder itself
  and any of its descendants, so depth stays finite without a depth limit.
- **The backend is mocked at the API seam, not in the components.** Until the
  routes exist, `libraryFoldersApi` resolves to a browser-local implementation
  that keeps the folder tree and placements in `localStorage` per workspace while
  reading the artifacts themselves from the real Library endpoint. Setting
  `NEXT_PUBLIC_LIBRARY_FOLDERS_API=real` switches to the HTTP implementation,
  which is written against the routes the server will expose. Flipping the flag
  is the migration; deleting `library-folders.mock.ts` is the cleanup.

Consequences:

- The mock is demo-able and testable today, and it is the app's only knowingly
  temporary module. It is confined to `src/lib/api`; no component, style, or test
  reaches past `libraryFoldersApi` to get at it.
- Folders a user makes in the browser are local to that browser until the routes
  land. The mock seeds a starting tree once per workspace so the shape of the
  feature is visible on first open; deleting a seeded folder stays deleted.
- When the server grows folder storage it inherits these rules — infinite depth,
  no cycles, delete-empty-only, sibling name uniqueness — and the mock's tests
  describe what the routes must do.
