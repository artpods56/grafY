"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { ScrollArea } from "@base-ui/react/scroll-area";
import useSWR from "swr";
import {
  ArrowDownUp,
  Clock,
  FolderPlus,
  LoaderCircle,
  Search,
  Upload,
  X,
} from "lucide-react";

import {
  libraryFoldersApi,
  saveUploadedArtifactToLibrary,
  uploadFile,
} from "@/lib/api";
import { panelStyles as s } from "./panel-styles";
import {
  buildLibraryTree,
  countLibraryArtifacts,
  libraryFolderKey,
  type LibrarySort,
} from "./library-tree";
import { useCollapsedFolderKeys } from "./workbench-side-panel-state";
import {
  dragKind,
  droppedArtifactId,
  isFileDrag,
  MIME_LIBRARY_FOLDER_ID,
} from "./library/drag-payload";
import { operationErrorMessage } from "./library/operation-error";
import { LibraryArtifactTile } from "./library/LibraryArtifactTile";
import { LibraryRow } from "./library/LibraryRow";

export function LibraryPanel({
  workspaceId,
  onOpenRun,
}: {
  workspaceId: string;
  onOpenRun: (graphId: string, executionId: string) => void;
}) {
  const { data, isLoading, error, mutate } = useSWR(
    ["library-tree", workspaceId],
    () => libraryFoldersApi.listTree(workspaceId),
  );
  const [collapsedFolders, setCollapsedFolder] = useCollapsedFolderKeys();
  const [query, setQuery] = React.useState("");
  const [sort, setSort] = React.useState<LibrarySort>("name");
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [focusKey, setFocusKey] = React.useState<string | null>(null);
  const [renamingFolderId, setRenamingFolderId] = React.useState<string | null>(
    null,
  );
  const [dragOverFolderId, setDragOverFolderId] = React.useState<string | null>(
    null,
  );
  const [fileDragOver, setFileDragOver] = React.useState(false);
  const [uploading, setUploading] = React.useState(false);
  const [message, setMessage] = React.useState<string | null>(null);
  const treeRef = React.useRef<HTMLDivElement>(null);
  const fileInputRef = React.useRef<HTMLInputElement>(null);
  const renameInputRef = React.useRef<HTMLInputElement>(null);

  const folders = React.useMemo(() => data?.folders ?? [], [data]);
  const items = React.useMemo(() => data?.items ?? [], [data]);
  const tree = React.useMemo(
    () => buildLibraryTree({ folders, items, query, sort }),
    [folders, items, query, sort],
  );
  const filtering = query.trim() !== "";
  const totalArtifacts = countLibraryArtifacts(tree);
  const selected = items.find(
    (item) => item.artifact.artifact_id === selectedId,
  );
  /** Roving tabindex: one row in the tree is reachable by Tab. */
  const tabbableKey = focusKey ?? tree[0]?.key ?? null;

  React.useEffect(() => {
    if (renamingFolderId === null) return;
    renameInputRef.current?.focus();
    renameInputRef.current?.select();
  }, [renamingFolderId]);

  async function runOperation(action: () => Promise<unknown>): Promise<void> {
    try {
      await action();
      setMessage(null);
      await mutate();
    } catch (operationError) {
      setMessage(operationErrorMessage(operationError, folders, items));
    }
  }

  async function createFolder(parentId: string | null): Promise<void> {
    await runOperation(async () => {
      const folder = await libraryFoldersApi.createFolder({
        workspaceId,
        name: uniqueFolderName(parentId),
        parentId,
      });
      if (parentId !== null)
        setCollapsedFolder(libraryFolderKey(parentId), false);
      setRenamingFolderId(folder.folder_id);
      setFocusKey(libraryFolderKey(folder.folder_id));
    });
  }

  function uniqueFolderName(parentId: string | null): string {
    const siblings = new Set(
      folders
        .filter((folder) => folder.parent_id === parentId)
        .map((folder) => folder.name.toLowerCase()),
    );
    if (!siblings.has("new folder")) return "New folder";
    for (let suffix = 2; ; suffix += 1) {
      const candidate = `New folder ${suffix}`;
      if (!siblings.has(candidate.toLowerCase())) return candidate;
    }
  }

  async function ingestFiles(
    files: File[],
    folderId: string | null,
  ): Promise<void> {
    if (files.length === 0 || uploading) return;
    setUploading(true);
    setMessage(null);
    try {
      for (const file of files) {
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
      }
      await mutate();
    } catch (uploadCause) {
      setMessage(operationErrorMessage(uploadCause, folders, items));
    } finally {
      setUploading(false);
      setFileDragOver(false);
      setDragOverFolderId(null);
    }
  }

  function rows(): HTMLElement[] {
    const treeElement = treeRef.current;
    if (!treeElement) return [];
    return [...treeElement.querySelectorAll<HTMLElement>("[data-tree-key]")];
  }

  function focusRow(element: HTMLElement | null | undefined): void {
    if (!element) return;
    setFocusKey(element.dataset.treeKey ?? null);
    element.focus();
  }

  /**
   * The row the keyboard is on. Read from the live element rather than the
   * roving-tabindex state, which is one render behind a fast key sequence.
   */
  function activeKey(): string | null {
    const active = document.activeElement;
    if (!(active instanceof HTMLElement)) return focusKey;
    return (
      active.closest<HTMLElement>("[data-tree-key]")?.dataset.treeKey ??
      focusKey
    );
  }

  function focusByStep(step: number): void {
    const list = rows();
    if (list.length === 0) return;
    const key = activeKey();
    const current = list.findIndex((row) => row.dataset.treeKey === key);
    focusRow(list[Math.min(list.length - 1, Math.max(0, current + step))]);
  }

  function focusByOffset(offset: number): void {
    const list = rows();
    if (list.length === 0) return;
    focusRow(list[offset < 0 ? list.length + offset : offset]);
  }

  function focusRowByKey(key: string | null): void {
    if (key === null) return;
    focusRow(
      treeRef.current?.querySelector<HTMLElement>(`[data-tree-key="${key}"]`),
    );
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLDivElement>): void {
    if (
      event.target instanceof HTMLElement &&
      event.target.tagName === "INPUT"
    ) {
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      focusByStep(1);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      focusByStep(-1);
      return;
    }
    if (event.key === "Home") {
      event.preventDefault();
      focusByOffset(0);
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      focusByOffset(-1);
      return;
    }
    const key = activeKey();
    if (key === null) return;
    if (event.key === "ArrowRight" && key.startsWith("folder:")) {
      if (collapsedFolders.has(key)) {
        event.preventDefault();
        setCollapsedFolder(key, false);
      } else {
        focusByStep(1);
      }
      return;
    }
    if (event.key === "ArrowLeft") {
      if (key.startsWith("folder:")) {
        const folderId = key.slice("folder:".length);
        const parent = folders.find(
          (folder) => folder.folder_id === folderId,
        )?.parent_id;
        if (!collapsedFolders.has(key)) {
          event.preventDefault();
          setCollapsedFolder(key, true);
        } else if (parent) {
          event.preventDefault();
          focusRowByKey(libraryFolderKey(parent));
        }
        return;
      }
      const artifactId = key.slice("file:".length);
      const fileFolder = items.find(
        (item) => item.artifact.artifact_id === artifactId,
      )?.folder_id;
      if (fileFolder) {
        event.preventDefault();
        focusRowByKey(libraryFolderKey(fileFolder));
      }
      return;
    }
    if (
      (event.key === "Enter" || event.key === " ") &&
      key.startsWith("folder:")
    ) {
      event.preventDefault();
      setCollapsedFolder(key, !collapsedFolders.has(key));
      return;
    }
    focusByTyping(event);
  }

  /** Filesystem type-ahead: a letter jumps to the next row that starts with it. */
  function focusByTyping(event: React.KeyboardEvent<HTMLDivElement>): void {
    if (
      event.metaKey ||
      event.ctrlKey ||
      event.altKey ||
      event.key.length !== 1 ||
      !/\S/.test(event.key)
    ) {
      return;
    }
    const list = rows();
    if (list.length === 0) return;
    const current = list.findIndex(
      (row) => row.dataset.treeKey === activeKey(),
    );
    const needle = event.key.toLowerCase();
    for (let offset = 1; offset <= list.length; offset += 1) {
      const candidate = list[(current + offset) % list.length];
      if (
        (candidate?.dataset.treeLabel ?? "").toLowerCase().startsWith(needle)
      ) {
        event.preventDefault();
        focusRow(candidate);
        return;
      }
    }
  }

  const emptyLibrary = !isLoading && tree.length === 0 && items.length === 0;

  return (
    <div {...stylex.props(s.view)}>
      <div {...stylex.props(s.toolbar)}>
        <button
          type="button"
          aria-label="New folder"
          title="New folder"
          {...stylex.props(s.iconButton)}
          onClick={() => void createFolder(null)}
        >
          <FolderPlus size={13} />
        </button>
        <label {...stylex.props(s.search)}>
          <Search size={12} aria-hidden="true" />
          <input
            type="search"
            value={query}
            placeholder="Filter the Library"
            aria-label="Filter the Library"
            onChange={(event) => setQuery(event.target.value)}
            {...stylex.props(s.searchInput)}
          />
          {query ? (
            <button
              type="button"
              aria-label="Clear Library filter"
              {...stylex.props(s.iconButton)}
              onClick={() => setQuery("")}
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
          {...stylex.props(s.iconButton)}
          onClick={() => setSort(sort === "name" ? "recent" : "name")}
        >
          {sort === "name" ? <ArrowDownUp size={13} /> : <Clock size={13} />}
        </button>
        <button
          type="button"
          aria-label="Upload files to the Library"
          title="Upload files to the Library"
          disabled={uploading}
          {...stylex.props(s.iconButton)}
          onClick={() => fileInputRef.current?.click()}
        >
          {uploading ? (
            <LoaderCircle size={13} {...stylex.props(s.spinner)} />
          ) : (
            <Upload size={13} />
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
            void ingestFiles(picked, null);
          }}
        />
      </div>

      <div
        role="region"
        aria-label="Workspace Library files"
        {...stylex.props(s.dropRegion, fileDragOver ? s.dropActive : null)}
        onDragEnter={(event) => {
          if (!isFileDrag(event)) return;
          event.preventDefault();
          setFileDragOver(true);
        }}
        onDragOver={(event) => {
          // The background is the root of the tree: it takes uploads, artifacts
          // and folders, and only a drop it accepts will ever be reported.
          const kind = dragKind(Array.from(event.dataTransfer.types));
          if (kind === null) return;
          event.preventDefault();
          event.dataTransfer.dropEffect = kind === "upload" ? "copy" : "move";
          setFileDragOver(kind === "upload");
        }}
        onDragLeave={(event) => {
          if (event.currentTarget.contains(event.relatedTarget as Node)) return;
          setFileDragOver(false);
        }}
        onDrop={(event) => {
          const kind = dragKind(Array.from(event.dataTransfer.types));
          if (kind === "upload") {
            event.preventDefault();
            void ingestFiles(Array.from(event.dataTransfer.files), null);
            return;
          }
          if (kind === "artifact") {
            event.preventDefault();
            const artifactId = droppedArtifactId(event.dataTransfer);
            if (artifactId) {
              void runOperation(() =>
                libraryFoldersApi.moveItems({
                  workspaceId,
                  artifactIds: [artifactId],
                  folderId: null,
                }),
              );
            }
            return;
          }
          if (kind === "folder") {
            event.preventDefault();
            const folderId = event.dataTransfer.getData(MIME_LIBRARY_FOLDER_ID);
            if (folderId) {
              void runOperation(() =>
                libraryFoldersApi.moveFolder({
                  workspaceId,
                  folderId,
                  parentId: null,
                }),
              );
            }
          }
        }}
      >
        <ScrollArea.Root {...stylex.props(s.list)}>
          <ScrollArea.Viewport {...stylex.props(s.listViewport)}>
            <ScrollArea.Content {...stylex.props(s.listContent)}>
              {isLoading ? (
                <span role="status" {...stylex.props(s.notice)}>
                  <LoaderCircle size={12} {...stylex.props(s.spinner)} />{" "}
                  Loading the Library…
                </span>
              ) : null}
              {error && !isLoading ? (
                <p role="alert" {...stylex.props(s.error)}>
                  The Library could not be loaded.
                </p>
              ) : null}
              {message ? (
                <p role="alert" {...stylex.props(s.error)}>
                  {message}
                </p>
              ) : null}
              {emptyLibrary ? (
                <p {...stylex.props(s.notice)}>
                  The Library is empty. Drop a file anywhere in this panel, use
                  Upload, or make a folder to file things in.
                </p>
              ) : null}
              <div
                ref={treeRef}
                role="tree"
                aria-label="Workspace Library"
                onKeyDown={onKeyDown}
                {...stylex.props(s.listContent)}
              >
                {tree.map((node) => (
                  <LibraryRow
                    key={node.key}
                    node={node}
                    workspaceId={workspaceId}
                    collapsedFolders={collapsedFolders}
                    filtering={filtering}
                    tabbableKey={tabbableKey}
                    selectedId={selectedId}
                    renamingFolderId={renamingFolderId}
                    dragOverFolderId={dragOverFolderId}
                    renameInputRef={renameInputRef}
                    onToggle={(key) =>
                      setCollapsedFolder(key, !collapsedFolders.has(key))
                    }
                    onFocusRow={setFocusKey}
                    onSelect={setSelectedId}
                    onStartRename={setRenamingFolderId}
                    onEndRename={() => setRenamingFolderId(null)}
                    onRename={(folderId, name) =>
                      runOperation(() =>
                        libraryFoldersApi.renameFolder({
                          workspaceId,
                          folderId,
                          name,
                        }),
                      )
                    }
                    onCreateSubfolder={(parentId) =>
                      void createFolder(parentId)
                    }
                    onDelete={(folderId) =>
                      runOperation(() =>
                        libraryFoldersApi.deleteFolder({
                          workspaceId,
                          folderId,
                        }),
                      )
                    }
                    onDragOverFolder={setDragOverFolderId}
                    onMoveFolder={(folderId, parentId) =>
                      runOperation(() =>
                        libraryFoldersApi.moveFolder({
                          workspaceId,
                          folderId,
                          parentId,
                        }),
                      )
                    }
                    onMoveItems={(artifactIds, folderId) =>
                      runOperation(() =>
                        libraryFoldersApi.moveItems({
                          workspaceId,
                          artifactIds,
                          folderId,
                        }),
                      )
                    }
                    onUploadFiles={(files, folderId) =>
                      void ingestFiles(files, folderId)
                    }
                  />
                ))}
              </div>
            </ScrollArea.Content>
          </ScrollArea.Viewport>
          <ScrollArea.Scrollbar {...stylex.props(s.scrollbar)}>
            <ScrollArea.Thumb {...stylex.props(s.thumb)} />
          </ScrollArea.Scrollbar>
        </ScrollArea.Root>
        {fileDragOver ? (
          <span {...stylex.props(s.dropHint)}>
            Drop to add to the Workspace Library
          </span>
        ) : null}
      </div>

      {selected ? (
        <LibraryArtifactTile
          workspaceId={workspaceId}
          item={selected}
          folders={folders}
          onOpenRun={onOpenRun}
        />
      ) : null}

      <footer role="status" {...stylex.props(s.statusBar)}>
        {uploading
          ? "Uploading…"
          : `${totalArtifacts} artifact${totalArtifacts === 1 ? "" : "s"} · ${folders.length} folder${folders.length === 1 ? "" : "s"}`}
      </footer>
    </div>
  );
}
