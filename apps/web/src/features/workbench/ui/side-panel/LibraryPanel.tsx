"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { ScrollArea } from "@base-ui/react/scroll-area";
import useSWR from "swr";
import {
  ArrowDownAZ,
  Clock,
  FolderPlus,
  LoaderCircle,
  RotateCw,
  Search,
  Upload,
  X,
} from "lucide-react";

import {
  deleteLibraryArtifact,
  libraryFoldersApi,
  LibraryArtifactInUseError,
  LibraryFolderCycleError,
  LibraryFolderNameTakenError,
  LibraryFolderNotEmptyError,
  saveUploadedArtifactToLibrary,
  uploadFile,
  type LibraryFolder,
  type PlacedLibraryItem,
} from "@/lib/api";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { tokens } from "@/lib/stylex/tokens.stylex";
import {
  dropEffectFor,
  libraryDragKind,
  readLibraryDrop,
  type LibraryDrop,
  type LibraryDropTarget,
} from "./library-drag";
import {
  buildLibraryTree,
  countLibraryArtifacts,
  flattenLibraryRows,
  libraryFileDisplayName,
  libraryFolderKey,
  uniqueLibraryFolderName,
  type LibrarySort,
} from "./library-tree";
import {
  applyLibrarySelection,
  emptyLibrarySelection,
  libraryBulkDeleteSummary,
  librarySelectionSummary,
  orderedLibrarySelection,
  pruneLibrarySelection,
  removeFromLibrarySelection,
  type LibrarySelection,
} from "./library-selection";
import { LibraryArtifactTile } from "./LibraryArtifactTile";
import { LibraryTree, type LibraryTreeActions } from "./LibraryTree";
import { panelStyles } from "./panel-styles";
import { useCollapsedFolderKeys } from "./workbench-side-panel-state";

const NO_KEYS: ReadonlySet<string> = new Set();

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

/**
 * The sentence the panel shows when the server refused.
 *
 * A refusal carries a code, never counts, so the contents come from the rows the
 * panel already renders. A folder whose badge reads 0 while it holds an empty
 * subfolder still offers Delete and is still refused — that count comes from
 * here, not from the error body.
 */
function operationErrorMessage(
  error: unknown,
  folders: readonly LibraryFolder[],
  items: readonly PlacedLibraryItem[],
): string {
  if (error instanceof LibraryFolderNotEmptyError) {
    const artifactCount = items.filter(
      (item) => item.folder_id === error.folderId,
    ).length;
    const childCount = folders.filter(
      (folder) => folder.parent_id === error.folderId,
    ).length;
    const parts = [
      artifactCount > 0 ? plural(artifactCount, "artifact") : null,
      childCount > 0 ? plural(childCount, "folder") : null,
    ].filter((part): part is string => part !== null);
    if (parts.length === 0) {
      // The server counted something this listing never received — another
      // browser filed it. The refusal stands; only the number is unknown.
      return "Move them out first — this folder is not empty.";
    }
    return `Move them out first — this folder still holds ${parts.join(" and ")}.`;
  }
  if (error instanceof LibraryFolderCycleError) {
    return "A folder cannot be moved inside itself.";
  }
  if (error instanceof LibraryFolderNameTakenError) {
    return `There is already a folder called ${error.folderName} here.`;
  }
  if (error instanceof LibraryArtifactInUseError) {
    // The references live in saved revisions and run history, neither of which
    // this panel holds, so the server's own sentence — the one naming the
    // graphs — is the only true thing that can be said here.
    return error.detail;
  }
  if (error instanceof Error && error.message) return error.message;
  return "That could not be done.";
}

/**
 * The Workspace Library as a folder tree: the Artifacts view of the side panel.
 * `headerEnd` is the shell's own control, placed at the end of the header row.
 */
export function LibraryPanel({
  workspaceId,
  onOpenRun,
  canEdit = true,
  headerEnd,
}: {
  workspaceId: string;
  onOpenRun: (graphId: string, executionId: string) => void;
  /** The capability behind every Library change. Read-only members are told, not refused later. */
  canEdit?: boolean;
  headerEnd?: React.ReactNode;
}) {
  // The canvas reads the same key, so a change here reaches its cards too.
  const { data, error, mutate } = useSWR(["library-tree", workspaceId], () =>
    libraryFoldersApi.listTree(workspaceId),
  );
  const folders = React.useMemo(() => data?.folders ?? [], [data]);
  const items = React.useMemo(() => data?.items ?? [], [data]);

  const [query, setQuery] = React.useState("");
  const [sort, setSort] = React.useState<LibrarySort>("name");
  // Several artifacts are selected at once, with the row a shift range measures
  // from kept beside them. What the Library holds changes under it, so the
  // selection is pruned where it is read rather than corrected after a render.
  const [picked, setPicked] = React.useState<LibrarySelection>(
    emptyLibrarySelection,
  );
  const [renamingFolderId, setRenamingFolderId] = React.useState<string | null>(
    null,
  );
  const [dropTarget, setDropTargetState] =
    React.useState<LibraryDropTarget | null>(null);
  const [upload, setUpload] = React.useState<{
    done: number;
    total: number;
  } | null>(null);
  const [message, setMessage] = React.useState<string | null>(null);
  // The artifacts a delete is waiting to be confirmed. Several at once when the
  // user asked for a selection; the name is held for the one case, where the
  // confirmation can say what is about to go away.
  const [deleteTarget, setDeleteTarget] = React.useState<{
    artifactIds: string[];
    name: string | null;
  } | null>(null);
  const [deleting, setDeleting] = React.useState(false);
  const uploadingRef = React.useRef(false);
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  // Folds are remembered. A filter opens every folder instead, and the folds
  // made while it is on are forgotten with it.
  const [savedCollapsed, setSavedCollapsed] = useCollapsedFolderKeys();
  const [filterCollapsed, setFilterCollapsed] = React.useState(NO_KEYS);
  const filtering = query.trim() !== "";
  const collapsed = filtering ? filterCollapsed : savedCollapsed;

  const tree = React.useMemo(
    () => buildLibraryTree({ folders, items, query, sort }),
    [folders, items, query, sort],
  );
  /**
   * The rows the tree renders, top to bottom — a filter and the open folders
   * have already been applied to it.
   *
   * A shift range, a bulk delete and a drag of several artifacts all run in this
   * order, because this is the order the user is looking at.
   */
  const visibleArtifacts = React.useMemo(
    () =>
      flattenLibraryRows(tree, { collapsed })
        .filter((row) => row.kind === "file")
        .map((row) => row.item),
    [tree, collapsed],
  );
  const visibleArtifactIds = React.useMemo(
    () => visibleArtifacts.map((item) => item.artifact.artifact_id),
    [visibleArtifacts],
  );
  const itemsById = React.useMemo(
    () =>
      new Map(items.map((item) => [item.artifact.artifact_id, item] as const)),
    [items],
  );

  // A refresh that took an artifact away takes it out of the selection too, so a
  // bulk delete can never aim at a row the Library no longer has.
  const existingIds = React.useMemo(
    () => new Set(items.map((item) => item.artifact.artifact_id)),
    [items],
  );
  const selection = React.useMemo(
    () => pruneLibrarySelection(picked, existingIds),
    [picked, existingIds],
  );

  // The preview tile shows one artifact or none: several selected artifacts have
  // no single preview, and its folder picker would claim to move what it shows.
  const selected =
    selection.ids.length === 1
      ? itemsById.get(selection.ids[0] ?? "")
      : undefined;

  // `dragover` fires every few milliseconds; only a new target re-renders.
  const setDropTarget = React.useCallback(
    (next: LibraryDropTarget | null) =>
      setDropTargetState((current) =>
        current?.folderId === next?.folderId && current?.kind === next?.kind
          ? current
          : next,
      ),
    [],
  );

  function changeQuery(next: string): void {
    setQuery(next);
    setFilterCollapsed(NO_KEYS);
  }

  /** Runs one change, says why if it was refused, and rereads the tree. */
  async function run(action: () => Promise<unknown>): Promise<void> {
    try {
      await action();
      setMessage(null);
    } catch (refusal) {
      setMessage(operationErrorMessage(refusal, folders, items));
    }
    await mutate();
  }

  async function createFolder(parentId: string | null): Promise<void> {
    // The new folder is named in place, so nothing may filter it out of view.
    changeQuery("");
    await run(async () => {
      const folder = await libraryFoldersApi.createFolder({
        workspaceId,
        name: uniqueLibraryFolderName(folders, parentId),
        parentId,
      });
      if (parentId !== null) {
        setSavedCollapsed(libraryFolderKey(parentId), false);
      }
      setRenamingFolderId(folder.folder_id);
    });
  }

  async function uploadFiles(
    files: readonly File[],
    folderId: string | null,
  ): Promise<void> {
    if (files.length === 0 || uploadingRef.current) return;
    uploadingRef.current = true;
    setMessage(null);
    setUpload({ done: 0, total: files.length });
    try {
      for (const [index, file] of files.entries()) {
        const uploaded = await uploadFile(workspaceId, file);
        if (uploaded.artifact_id == null) {
          throw new Error(
            `Upload of ${file.name} completed without an artifact.`,
          );
        }
        await saveUploadedArtifactToLibrary(workspaceId, {
          artifact_id: uploaded.artifact_id,
          original_filename: uploaded.filename || file.name,
        });
        if (folderId !== null) {
          await libraryFoldersApi.moveItems({
            workspaceId,
            artifactIds: [uploaded.artifact_id],
            folderId,
          });
        }
        setUpload({ done: index + 1, total: files.length });
        // Each file shows up as it lands rather than all of them at the end.
        void mutate();
      }
    } catch (refusal) {
      setMessage(operationErrorMessage(refusal, folders, items));
    } finally {
      uploadingRef.current = false;
      setUpload(null);
      await mutate();
    }
  }

  function drop(dropped: LibraryDrop, folderId: string | null): void {
    switch (dropped.kind) {
      case "upload":
        void uploadFiles(dropped.files, folderId);
        return;
      case "artifact":
        void run(() =>
          libraryFoldersApi.moveItems({
            workspaceId,
            artifactIds: dropped.artifactIds,
            folderId,
          }),
        );
        return;
      case "folder":
        void run(() =>
          libraryFoldersApi.moveFolder({
            workspaceId,
            folderId: dropped.folderId,
            parentId: folderId,
          }),
        );
    }
  }

  const actions: LibraryTreeActions = {
    setFolderOpen(key, open) {
      if (!filtering) {
        setSavedCollapsed(key, !open);
        return;
      }
      setFilterCollapsed((current) => {
        const next = new Set(current);
        if (open) next.delete(key);
        else next.add(key);
        return next;
      });
    },
    select: (artifactId, gesture = "plain") => {
      setPicked(
        artifactId === null
          ? emptyLibrarySelection
          : applyLibrarySelection({
              selection,
              artifactId,
              gesture,
              visible: visibleArtifactIds,
            }),
      );
    },
    beginArtifactDrag: (artifactId) => {
      // A row in a multi-selection drags the selection; any other row is picked
      // up on its own and the selection follows it, so what the panel has
      // selected is always what a drag moved.
      const ids =
        selection.ids.length >= 2 && selection.ids.includes(artifactId)
          ? orderedLibrarySelection(selection, visibleArtifactIds)
          : [artifactId];
      const dragged = ids
        .map((id) => itemsById.get(id))
        .filter((item): item is PlacedLibraryItem => item !== undefined);
      setPicked({
        ids: dragged.map((item) => item.artifact.artifact_id),
        anchor: artifactId,
      });
      return dragged;
    },
    startRename: setRenamingFolderId,
    async renameFolder(folderId, name) {
      if (name !== null) {
        await run(() =>
          libraryFoldersApi.renameFolder({ workspaceId, folderId, name }),
        );
      }
      setRenamingFolderId(null);
    },
    createSubfolder: (parentId) => void createFolder(parentId),
    deleteFolder: (folderId) =>
      void run(() => libraryFoldersApi.deleteFolder({ workspaceId, folderId })),
    requestDeleteArtifact: (artifactId) => {
      // A row inside a multi-selection means the whole selection; a row outside
      // it means only itself, even when a dozen other rows are highlighted.
      const artifactIds =
        selection.ids.length >= 2 && selection.ids.includes(artifactId)
          ? orderedLibrarySelection(selection, visibleArtifactIds)
          : [artifactId];
      const only = artifactIds.length === 1 ? itemsById.get(artifactId) : null;
      if (artifactIds.length === 1 && !only) return;
      setDeleteTarget({
        artifactIds,
        name: only ? libraryFileDisplayName(only) : null,
      });
    },
    drop,
    setDropTarget,
  };

  /**
   * Takes the confirmed artifacts out of the Library.
   *
   * Each artifact is asked for on its own, in tree order, and a refusal never
   * stops the ones behind it: the server decides per artifact, and stopping at
   * the first artifact still in use would leave the rest of a deliberate
   * selection behind without saying so. The tree is reread once the batch is
   * answered, and one sentence covers it — the server's own for a single
   * artifact, a count and a list of what refused for several.
   *
   * What refused stays selected, so the user can see what is left and act on it
   * again; what went away leaves the selection with it.
   */
  async function confirmDeleteArtifacts(): Promise<void> {
    if (!deleteTarget) return;
    const { artifactIds } = deleteTarget;
    setDeleting(true);
    const deleted: string[] = [];
    const refused: { artifactId: string; name: string; detail: string }[] = [];
    for (const artifactId of artifactIds) {
      const item = itemsById.get(artifactId);
      try {
        await deleteLibraryArtifact(workspaceId, artifactId);
        deleted.push(artifactId);
      } catch (refusal) {
        refused.push({
          artifactId,
          name: item ? libraryFileDisplayName(item) : "That artifact",
          detail: operationErrorMessage(refusal, folders, items),
        });
      }
    }
    try {
      await mutate();
    } finally {
      setDeleting(false);
      setDeleteTarget(null);
    }
    // The reread above prunes the selection too, for anything the Library lost
    // while the dialog was open. What the server kept stays selected so the user
    // can see what is left and act on it again; what went away leaves the
    // selection with it, and a delete asked for outside a selection leaves that
    // selection alone.
    setPicked((current) => removeFromLibrarySelection(current, deleted));
    if (refused.length === 0) {
      setMessage(null);
      return;
    }
    const [only] = refused;
    // One artifact asked for, one refusal: the server's own sentence is the whole
    // story and needs no count in front of it. Several asked for: one sentence
    // for the batch, naming what refused.
    setMessage(
      artifactIds.length === 1 && only
        ? only.detail
        : (libraryBulkDeleteSummary(deleted.length, refused) ?? null),
    );
  }

  const loading = data === undefined && error === undefined;
  const emptyLibrary =
    data !== undefined && folders.length === 0 && items.length === 0;
  const shownCount = countLibraryArtifacts(tree);
  const rootDrag = dropTarget?.folderId === null ? dropTarget : null;

  return (
    <div {...stylex.props(s.view)}>
      <header {...stylex.props(s.header)}>
        <h2 {...stylex.props(s.title)}>Artifacts</h2>
        <button
          type="button"
          aria-label="New folder"
          title="New folder"
          onClick={() => void createFolder(null)}
          {...stylex.props(panelStyles.iconButton)}
        >
          <FolderPlus size={14} />
        </button>
        <button
          type="button"
          aria-label="Upload files to the Library"
          title="Upload files to the Library"
          disabled={upload !== null}
          onClick={() => fileInputRef.current?.click()}
          {...stylex.props(panelStyles.iconButton)}
        >
          {upload ? (
            <LoaderCircle size={14} {...stylex.props(panelStyles.spinner)} />
          ) : (
            <Upload size={14} />
          )}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          hidden
          tabIndex={-1}
          onChange={(event) => {
            const picked = Array.from(event.target.files ?? []);
            event.target.value = "";
            void uploadFiles(picked, null);
          }}
        />
        {headerEnd ? (
          <>
            <span aria-hidden="true" {...stylex.props(s.headerDivider)} />
            {headerEnd}
          </>
        ) : null}
      </header>

      <div {...stylex.props(s.searchRow)}>
        <label {...stylex.props(s.search)}>
          <Search size={12} aria-hidden="true" />
          <input
            type="search"
            value={query}
            placeholder="Filter the Library"
            aria-label="Filter the Library"
            onChange={(event) => changeQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape" && query !== "") {
                event.preventDefault();
                event.stopPropagation();
                changeQuery("");
              }
            }}
            {...stylex.props(s.searchInput)}
          />
          {query ? (
            <button
              type="button"
              aria-label="Clear Library filter"
              onClick={() => changeQuery("")}
              {...stylex.props(panelStyles.iconButton, s.clearButton)}
            >
              <X size={12} />
            </button>
          ) : null}
        </label>
        <button
          type="button"
          aria-label={
            sort === "name"
              ? "Sort artifacts by newest"
              : "Sort artifacts by name"
          }
          title={sort === "name" ? "Sorted by name" : "Sorted by newest"}
          onClick={() => setSort(sort === "name" ? "recent" : "name")}
          {...stylex.props(panelStyles.iconButton)}
        >
          {sort === "name" ? <ArrowDownAZ size={14} /> : <Clock size={14} />}
        </button>
      </div>

      <div
        role="region"
        aria-label="Workspace Library files"
        // The background is the root of the tree: it takes uploads, artifacts
        // and folders, and a drop over a row never reaches it.
        onDragOver={(event) => {
          const kind = libraryDragKind(event.dataTransfer);
          if (kind === null) return;
          event.preventDefault();
          event.dataTransfer.dropEffect = dropEffectFor(kind);
          setDropTarget({ folderId: null, kind });
        }}
        onDragLeave={(event) => {
          if (event.currentTarget.contains(event.relatedTarget as Node)) return;
          setDropTarget(null);
        }}
        onDrop={(event) => {
          const dropped = readLibraryDrop(event.dataTransfer);
          if (libraryDragKind(event.dataTransfer) === null) return;
          event.preventDefault();
          setDropTarget(null);
          if (dropped) drop(dropped, null);
        }}
        {...stylex.props(s.dropRegion, rootDrag ? s.dropRegionActive : null)}
      >
        <ScrollArea.Root {...stylex.props(s.scrollRoot)}>
          <ScrollArea.Viewport {...stylex.props(s.scrollViewport)}>
            <ScrollArea.Content {...stylex.props(s.scrollContent)}>
              {loading ? (
                <span role="status" {...stylex.props(s.notice, s.loading)}>
                  <LoaderCircle
                    size={12}
                    aria-hidden="true"
                    {...stylex.props(panelStyles.spinner)}
                  />
                  Loading the Library…
                </span>
              ) : null}
              {error && data === undefined ? (
                <p role="alert" {...stylex.props(s.notice, s.error)}>
                  The Library could not be loaded.
                  <button
                    type="button"
                    onClick={() => void mutate()}
                    {...stylex.props(s.inlineAction)}
                  >
                    <RotateCw size={11} aria-hidden="true" />
                    Try again
                  </button>
                </p>
              ) : null}
              {message ? (
                <p role="alert" {...stylex.props(s.notice, s.error)}>
                  <span {...stylex.props(s.messageText)}>{message}</span>
                  <button
                    type="button"
                    aria-label="Dismiss"
                    title="Dismiss"
                    onClick={() => setMessage(null)}
                    {...stylex.props(panelStyles.iconButton, s.dismiss)}
                  >
                    <X size={12} />
                  </button>
                </p>
              ) : null}
              {emptyLibrary ? (
                <p {...stylex.props(s.notice)}>
                  The Library is empty. Drop a file anywhere in this panel, use
                  Upload, or make a folder to file things in.
                </p>
              ) : null}
              {data && filtering && tree.length === 0 && !emptyLibrary ? (
                <p {...stylex.props(s.notice)}>
                  Nothing in the Library matches “{query.trim()}”.
                </p>
              ) : null}
              <LibraryTree
                nodes={tree}
                workspaceId={workspaceId}
                canEdit={canEdit}
                collapsed={collapsed}
                filtering={filtering}
                selection={selection}
                renamingFolderId={renamingFolderId}
                dropTarget={dropTarget}
                actions={actions}
              />
            </ScrollArea.Content>
          </ScrollArea.Viewport>
          <ScrollArea.Scrollbar {...stylex.props(s.scrollbar)}>
            <ScrollArea.Thumb {...stylex.props(s.thumb)} />
          </ScrollArea.Scrollbar>
        </ScrollArea.Root>
        {rootDrag?.kind === "upload" ? (
          <span {...stylex.props(s.dropHint)}>
            Drop to add to the Workspace Library
          </span>
        ) : null}
      </div>

      {selected ? (
        <LibraryArtifactTile
          key={selected.artifact.artifact_id}
          workspaceId={workspaceId}
          item={selected}
          folders={folders}
          onOpenRun={onOpenRun}
          onClose={() => setPicked(emptyLibrarySelection)}
        />
      ) : null}

      <footer role="status" {...stylex.props(s.statusBar)}>
        {[
          librarySelectionSummary(selection),
          upload
            ? `Uploading ${Math.min(upload.done + 1, upload.total)} of ${upload.total}…`
            : filtering
              ? `${shownCount} of ${plural(items.length, "artifact")}`
              : `${plural(items.length, "artifact")} · ${plural(folders.length, "folder")}`,
        ]
          .filter((part): part is string => part !== null)
          .join(" · ")}
      </footer>

      {/* Deleting an artifact is not a click's worth of consequence, so the row
          menu only asks for it and this dialog decides it. */}
      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open && !deleting) setDeleteTarget(null);
        }}
      >
        <DialogContent size="compact">
          <DialogHeader>
            <DialogTitle>
              {deleteTarget?.name
                ? `Delete ${deleteTarget.name}?`
                : `Delete ${deleteTarget?.artifactIds.length ?? 0} artifacts?`}
            </DialogTitle>
            <DialogDescription>This can&apos;t be undone.</DialogDescription>
          </DialogHeader>
          <DialogBody>
            <div {...stylex.props(s.dialogActions)}>
              <button
                type="button"
                className="grafy-workspace-button"
                disabled={deleting}
                onClick={() => setDeleteTarget(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="grafy-workspace-button grafy-workspace-button--primary"
                disabled={deleting}
                onClick={() => void confirmDeleteArtifacts()}
              >
                {deleting ? "Deleting…" : "Delete"}
              </button>
            </div>
          </DialogBody>
        </DialogContent>
      </Dialog>
    </div>
  );
}

const s = stylex.create({
  view: {
    minHeight: 0,
    flex: 1,
    display: "flex",
    flexDirection: "column",
  },
  header: {
    flexShrink: 0,
    height: "52px",
    display: "flex",
    alignItems: "center",
    gap: "2px",
    padding: "0 6px 0 14px",
  },
  title: {
    minWidth: 0,
    flex: 1,
    margin: 0,
    overflow: "hidden",
    color: tokens.colorTextEmphasis,
    fontSize: "13px",
    fontWeight: 620,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  headerDivider: {
    width: "1px",
    height: "16px",
    marginInline: "4px",
    backgroundColor: tokens.colorDivider,
  },
  searchRow: {
    flexShrink: 0,
    display: "flex",
    alignItems: "center",
    gap: "4px",
    padding: "0 6px 6px 8px",
  },
  search: {
    minWidth: 0,
    flex: 1,
    height: "28px",
    display: "flex",
    alignItems: "center",
    gap: "6px",
    paddingInline: "8px 2px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: {
      default: tokens.colorBorder,
      ":focus-within": tokens.colorBorderStrong,
    },
    borderRadius: "6px",
    backgroundColor: {
      default: tokens.colorSurface,
      ":focus-within": tokens.colorBg,
    },
    color: tokens.colorSubtle,
  },
  searchInput: {
    minWidth: 0,
    flex: 1,
    height: "100%",
    borderWidth: 0,
    borderStyle: "none",
    padding: 0,
    backgroundColor: "transparent",
    color: tokens.colorText,
    fontFamily: "inherit",
    fontSize: tokens.fontSizeSm,
    outline: "none",
    // The field has its own clear button; the browser's would be a second one.
    "::-webkit-search-cancel-button": { appearance: "none" },
  },
  clearButton: { width: "22px", height: "22px" },
  /** The drop area: the positioned parent of the drop hint. */
  dropRegion: {
    position: "relative",
    minHeight: 0,
    flex: 1,
    display: "flex",
    flexDirection: "column",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
  },
  dropRegionActive: {
    backgroundColor: tokens.colorAccentSoft,
    boxShadow: `inset 0 0 0 1px ${tokens.colorAccentBorder}`,
  },
  dropHint: {
    position: "absolute",
    inset: "6px",
    display: "grid",
    placeItems: "center",
    pointerEvents: "none",
    borderRadius: "8px",
    borderWidth: 1,
    borderStyle: "dashed",
    borderColor: tokens.colorAccentBorder,
    backgroundColor: tokens.colorAccentSoft,
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeSm,
    fontWeight: 600,
  },
  scrollRoot: {
    minHeight: 0,
    flex: 1,
    display: "flex",
    flexDirection: "column",
  },
  scrollViewport: { height: "100%", overscrollBehavior: "contain" },
  scrollContent: {
    display: "grid",
    alignContent: "start",
    gap: "4px",
    padding: "6px 6px 12px",
  },
  scrollbar: {
    display: "flex",
    justifyContent: "center",
    width: "8px",
    padding: "2px",
  },
  thumb: {
    width: "4px",
    borderRadius: "9999px",
    backgroundColor: tokens.colorBorderStrong,
  },
  notice: {
    margin: 0,
    padding: "6px 8px",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.45,
  },
  loading: { display: "flex", alignItems: "center", gap: "6px" },
  error: {
    display: "flex",
    alignItems: "flex-start",
    flexWrap: "wrap",
    gap: "4px 8px",
    color: tokens.colorDanger,
  },
  messageText: { minWidth: 0, flex: 1 },
  dismiss: {
    width: "20px",
    height: "20px",
    marginBlock: "-1px",
    color: tokens.colorDanger,
  },
  inlineAction: {
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
    padding: 0,
    borderWidth: 0,
    borderStyle: "none",
    backgroundColor: "transparent",
    color: { default: tokens.colorMuted, ":hover": tokens.colorText },
    cursor: "pointer",
    fontFamily: "inherit",
    fontSize: tokens.fontSizeSm,
    fontWeight: 560,
  },
  statusBar: {
    flexShrink: 0,
    padding: "5px 10px",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
    color: tokens.colorSubtle,
    fontSize: "10px",
    letterSpacing: "0.04em",
    fontVariantNumeric: "tabular-nums",
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  dialogActions: {
    display: "flex",
    justifyContent: "flex-end",
    gap: "8px",
  },
});
