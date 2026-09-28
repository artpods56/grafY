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
- **The server holds the tree and one seam reaches it.** `libraryFoldersApi` is
  the only module that names the routes: `GET` and `POST
  /v1/workspaces/{workspace_id}/library/folders`, `PATCH` and `DELETE
  .../folders/{folder_id}`, `PUT .../folders/{folder_id}/parent`, and `PUT
  /v1/workspaces/{workspace_id}/library/placements`. `GET /library/artifacts`
  stamps every item with the `folder_id` it sits in. The rules arrive as failure
  codes in the envelope every failure in this API already returns —
  `library.folder_name_conflict`, `library.folder_not_empty`,
  `library.folder_cycle` — and the seam turns each one into the error class
  above.

Consequences:

- Nothing about the tree is browser-local: a folder made in one browser is in the
  workspace, not in that browser. The `localStorage` mock and its
  `NEXT_PUBLIC_LIBRARY_FOLDERS_API` flag are deleted — the HTTP implementation
  was already written against these routes, so growing the routes was the whole
  migration.
- The envelope is `{detail, code, error_id}` and carries no counts, so
  `LibraryFolderNotEmptyError` carries the `folder_id` and the panel counts the
  tree it already holds. Putting counts on the envelope would have widened every
  failure in this API to phrase one message.
- Reading the tree costs two requests — every folder at once, then the artifact
  list with placements stamped on it — however deep it gets, because the client
  assembles the shape (`library-tree.ts`) and the server keeps the rows.
- The rules are held in two places on purpose: `vitest` drives the code-to-error
  mapping and the panel's phrasing of it, and `e2e/library-folders-stub.ts`
  answers these routes inside Node with the same three refusals, so a refusal
  reaches the panel in a browser test the way it reaches the panel in the app.
