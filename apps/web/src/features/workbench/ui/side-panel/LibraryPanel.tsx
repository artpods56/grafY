"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Menu } from "@base-ui/react/menu";
import { ScrollArea } from "@base-ui/react/scroll-area";
import useSWR from "swr";
import {
  ArrowDownUp,
  ArrowUpRight,
  Boxes,
  ChevronRight,
  Clock,
  Download,
  File as FileIcon,
  FileText,
  Folder,
  FolderPlus,
  Image as ImageIcon,
  Link2,
  LoaderCircle,
  MoreHorizontal,
  Pencil,
  Search,
  Table,
  Trash2,
  Upload,
  X,
  type LucideIcon,
} from "lucide-react";

import {
  artifactContentUrl,
  libraryFoldersApi,
  LibraryFolderCycleError,
  LibraryFolderNameTakenError,
  LibraryFolderNotEmptyError,
  saveUploadedArtifactToLibrary,
  uploadFile,
  type LibraryFolder,
  type PlacedLibraryItem,
} from "@/lib/api";
import {
  ARTIFACT_DROP_DATA_TYPE,
  readArtifactDrop,
  writeArtifactDrop,
} from "../../model/artifact-drop";
import { BLOB_ARTIFACT_NOTICE, isBlobArtifact } from "../../model/blob-notice";
import { panelStyles as s } from "./panel-styles";
import {
  buildLibraryTree,
  countLibraryArtifacts,
  isItemImage,
  libraryFileDisplayName,
  libraryFileSubtitle,
  libraryFolderPath,
  libraryFolderKey,
  libraryProvenanceLine,
  type LibraryFileIcon,
  type LibraryFileNode,
  type LibraryFolderNode,
  type LibrarySort,
  type LibraryTreeNode,
} from "./library-tree";
import { useCollapsedFolderKeys } from "./workbench-side-panel-state";

/** A Library folder being dragged. The canvas ignores this type. */
const MIME_LIBRARY_FOLDER_ID = "application/x-grafy-library-folder";

const FILE_ICONS: Record<LibraryFileIcon, LucideIcon> = {
  image: ImageIcon,
  table: Table,
  text: FileText,
  model: Boxes,
  other: FileIcon,
};

/** How much of a text artifact the preview reads before it stops. */
const PREVIEW_TEXT_LIMIT = 20_000;

type DragKind = "upload" | "artifact" | "folder" | null;

function dragKind(types: readonly string[]): DragKind {
  if (types.includes("Files")) return "upload";
  if (types.includes(MIME_LIBRARY_FOLDER_ID)) return "folder";
  if (types.includes(ARTIFACT_DROP_DATA_TYPE)) return "artifact";
  return null;
}

/** The artifact one drag carries, when it carries exactly one. */
function droppedArtifactId(dataTransfer: DataTransfer): string | null {
  const dropped = readArtifactDrop(dataTransfer);
  if (dropped === null) return null;
  return "artifact_id" in dropped.value ? dropped.value.artifact_id : null;
}

/**
 * Whether a click belongs to a control inside the row rather than to the row.
 * The row action menu is rendered inside its row, so a click on the ⋯ or on one
 * of its items would otherwise fold the folder or select the artifact too.
 */
const ROW_CONTROL_SELECTOR = 'button, [role="button"], [role="menu"], [role="menuitem"]';

function isRowAction(event: React.MouseEvent): boolean {
  const target = event.target;
  return (
    target instanceof Element && target.closest(ROW_CONTROL_SELECTOR) !== null
  );
}

function isFileDrag(event: React.DragEvent): boolean {
  return Array.from(event.dataTransfer.types).includes("Files");
}

function operationErrorMessage(error: unknown): string {
  if (error instanceof LibraryFolderNotEmptyError) {
    const parts = [
      error.artifactCount > 0
        ? `${error.artifactCount} artifact${error.artifactCount === 1 ? "" : "s"}`
        : null,
      error.childCount > 0
        ? `${error.childCount} folder${error.childCount === 1 ? "" : "s"}`
        : null,
    ].filter((part): part is string => part !== null);
    return `Move them out first — this folder still holds ${parts.join(" and ")}.`;
  }
  if (error instanceof LibraryFolderCycleError) {
    return "A folder cannot be moved inside itself.";
  }
  if (error instanceof LibraryFolderNameTakenError) {
    return `There is already a folder called ${error.folderName} here.`;
  }
  if (error instanceof Error && error.message) return error.message;
  return "That could not be done.";
}

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
  const [renamingFolderId, setRenamingFolderId] = React.useState<string | null>(null);
  const [dragOverFolderId, setDragOverFolderId] = React.useState<string | null>(null);
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
      setMessage(operationErrorMessage(operationError));
    }
  }

  async function createFolder(parentId: string | null): Promise<void> {
    await runOperation(async () => {
      const folder = await libraryFoldersApi.createFolder({
        workspaceId,
        name: uniqueFolderName(parentId),
        parentId,
      });
      if (parentId !== null) setCollapsedFolder(libraryFolderKey(parentId), false);
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

  async function ingestFiles(files: File[], folderId: string | null): Promise<void> {
    if (files.length === 0 || uploading) return;
    setUploading(true);
    setMessage(null);
    try {
      for (const file of files) {
        const uploaded = await uploadFile(workspaceId, file);
        if (uploaded.artifact_id == null) {
          throw new Error(`Upload of ${file.name} completed without an artifact.`);
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
      setMessage(operationErrorMessage(uploadCause));
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
      active.closest<HTMLElement>("[data-tree-key]")?.dataset.treeKey ?? focusKey
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
        const parent = folders.find((folder) => folder.folder_id === folderId)
          ?.parent_id;
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
    if ((event.key === "Enter" || event.key === " ") && key.startsWith("folder:")) {
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
        (candidate?.dataset.treeLabel ?? "")
          .toLowerCase()
          .startsWith(needle)
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
            sort === "name" ? "Sort artifacts by newest" : "Sort artifacts by name"
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
                  <LoaderCircle size={12} {...stylex.props(s.spinner)} /> Loading
                  the Library…
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
                    onCreateSubfolder={(parentId) => void createFolder(parentId)}
                    onDelete={(folderId) =>
                      runOperation(() =>
                        libraryFoldersApi.deleteFolder({ workspaceId, folderId }),
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

/** One row, plus the rows it contains when it is an open folder. */
function LibraryRow({
  node,
  workspaceId,
  collapsedFolders,
  filtering,
  tabbableKey,
  selectedId,
  renamingFolderId,
  dragOverFolderId,
  renameInputRef,
  onToggle,
  onFocusRow,
  onSelect,
  onStartRename,
  onEndRename,
  onRename,
  onCreateSubfolder,
  onDelete,
  onDragOverFolder,
  onMoveFolder,
  onMoveItems,
  onUploadFiles,
}: {
  node: LibraryTreeNode;
  workspaceId: string;
  collapsedFolders: ReadonlySet<string>;
  filtering: boolean;
  tabbableKey: string | null;
  selectedId: string | null;
  renamingFolderId: string | null;
  dragOverFolderId: string | null;
  renameInputRef: React.RefObject<HTMLInputElement | null>;
  onToggle: (key: string) => void;
  onFocusRow: (key: string) => void;
  onSelect: (artifactId: string) => void;
  onStartRename: (folderId: string) => void;
  onEndRename: () => void;
  onRename: (folderId: string, name: string) => Promise<void>;
  onCreateSubfolder: (parentId: string) => void;
  onDelete: (folderId: string) => Promise<void>;
  onDragOverFolder: (folderId: string | null) => void;
  onMoveFolder: (folderId: string, parentId: string | null) => Promise<void>;
  onMoveItems: (artifactIds: readonly string[], folderId: string | null) => Promise<void>;
  onUploadFiles: (files: File[], folderId: string | null) => void;
}) {
  if (node.kind === "file") {
    return (
      <LibraryFileRow
        file={node}
        workspaceId={workspaceId}
        selected={node.item.artifact.artifact_id === selectedId}
        tabbable={tabbableKey === node.key}
        onFocusRow={() => onFocusRow(node.key)}
        onSelect={() => onSelect(node.item.artifact.artifact_id)}
      />
    );
  }

  const collapsed = collapsedFolders.has(node.key);
  const open = !collapsed;

  return (
    <>
      <LibraryFolderRow
        folder={node}
        open={open}
        renaming={renamingFolderId === node.id}
        dropTarget={dragOverFolderId === node.id}
        filtering={filtering}
        tabbable={tabbableKey === node.key}
        renameInputRef={renameInputRef}
        onFocusRow={() => onFocusRow(node.key)}
        onToggle={() => onToggle(node.key)}
        onStartRename={() => onStartRename(node.id)}
        onEndRename={onEndRename}
        onRename={(name) => onRename(node.id, name)}
        onCreateSubfolder={() => onCreateSubfolder(node.id)}
        onDelete={() => onDelete(node.id)}
        onDragOver={(kind) => {
          if (kind === null) return;
          onDragOverFolder(node.id);
        }}
        onDragLeave={() => onDragOverFolder(null)}
        onDrop={(event) => {
          const kind = dragKind(Array.from(event.dataTransfer.types));
          onDragOverFolder(null);
          if (kind === "upload") {
            event.preventDefault();
            event.stopPropagation();
            onUploadFiles(Array.from(event.dataTransfer.files), node.id);
            return;
          }
          if (kind === "artifact") {
            event.preventDefault();
            event.stopPropagation();
            const artifactId = droppedArtifactId(event.dataTransfer);
            if (artifactId) void onMoveItems([artifactId], node.id);
            return;
          }
          if (kind === "folder") {
            event.preventDefault();
            event.stopPropagation();
            const folderId = event.dataTransfer.getData(MIME_LIBRARY_FOLDER_ID);
            if (folderId && folderId !== node.id) {
              void onMoveFolder(folderId, node.id);
            }
          }
        }}
      />
      {open ? (
        <div
          role="group"
          aria-label={`${node.name} contents`}
          {...stylex.props(s.files)}
        >
          {node.nodes.map((child) => (
            <LibraryRow
              key={child.key}
              node={child}
              workspaceId={workspaceId}
              collapsedFolders={collapsedFolders}
              filtering={filtering}
              tabbableKey={tabbableKey}
              selectedId={selectedId}
              renamingFolderId={renamingFolderId}
              dragOverFolderId={dragOverFolderId}
              renameInputRef={renameInputRef}
              onToggle={onToggle}
              onFocusRow={onFocusRow}
              onSelect={onSelect}
              onStartRename={onStartRename}
              onEndRename={onEndRename}
              onRename={onRename}
              onCreateSubfolder={onCreateSubfolder}
              onDelete={onDelete}
              onDragOverFolder={onDragOverFolder}
              onMoveFolder={onMoveFolder}
              onMoveItems={onMoveItems}
              onUploadFiles={onUploadFiles}
            />
          ))}
        </div>
      ) : null}
    </>
  );
}

function LibraryFolderRow({
  folder,
  open,
  renaming,
  dropTarget,
  filtering,
  tabbable,
  renameInputRef,
  onFocusRow,
  onToggle,
  onStartRename,
  onEndRename,
  onRename,
  onCreateSubfolder,
  onDelete,
  onDragOver,
  onDragLeave,
  onDrop,
}: {
  folder: LibraryFolderNode;
  open: boolean;
  renaming: boolean;
  dropTarget: boolean;
  filtering: boolean;
  tabbable: boolean;
  renameInputRef: React.RefObject<HTMLInputElement | null>;
  onFocusRow: () => void;
  onToggle: () => void;
  onStartRename: () => void;
  onEndRename: () => void;
  onRename: (name: string) => Promise<void>;
  onCreateSubfolder: () => void;
  onDelete: () => Promise<void>;
  onDragOver: (kind: DragKind) => void;
  onDragLeave: () => void;
  onDrop: (event: React.DragEvent<HTMLDivElement>) => void;
}) {
  const canDelete = folder.total === 0;

  return (
    <div
      role="treeitem"
      aria-expanded={open}
      aria-selected={false}
      aria-level={folder.depth + 1}
      data-tree-key={folder.key}
      data-tree-label={folder.name}
      data-folder-drop={dropTarget ? "true" : undefined}
      tabIndex={tabbable ? 0 : -1}
      title={folder.name}
      onFocus={onFocusRow}
      onClick={(event) => {
        if (isRowAction(event)) return;
        onToggle();
      }}
      onKeyDown={(event) => {
        if (event.key === "F2") {
          event.preventDefault();
          onStartRename();
        }
      }}
      onDragStart={(event) => {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData(MIME_LIBRARY_FOLDER_ID, folder.id);
      }}
      onDragOver={(event) => {
        const kind = dragKind(Array.from(event.dataTransfer.types));
        if (kind === null) return;
        event.preventDefault();
        event.stopPropagation();
        event.dataTransfer.dropEffect = kind === "upload" ? "copy" : "move";
        onDragOver(kind);
      }}
      onDragLeave={(event) => {
        if (event.currentTarget.contains(event.relatedTarget as Node)) return;
        onDragLeave();
      }}
      onDrop={onDrop}
      {...stylex.props(s.folderRow, dropTarget ? s.rowDropTarget : null)}
      draggable={!renaming}
    >
      <ChevronRight
        size={12}
        aria-hidden="true"
        {...stylex.props(s.chevron, open ? s.chevronOpen : null)}
      />
      <Folder size={13} aria-hidden="true" />
      {renaming ? (
        <LibraryFolderRenameInput
          initialName={folder.name}
          inputRef={renameInputRef}
          onCommit={(name) => void onRename(name).then(onEndRename)}
          onCancel={onEndRename}
        />
      ) : (
        <span {...stylex.props(s.folderName)}>{folder.name}</span>
      )}
      <span {...stylex.props(s.count)}>
        {filtering ? folder.matched : folder.total}
      </span>
      {!renaming ? (
        <Menu.Root>
          <Menu.Trigger
            aria-label={`Actions for ${folder.name}`}
            {...stylex.props(s.rowActions)}
          >
            <MoreHorizontal size={13} />
          </Menu.Trigger>
          <Menu.Portal>
            <Menu.Positioner
              side="bottom"
              align="end"
              sideOffset={4}
              {...stylex.props(s.menuPositioner)}
            >
              <Menu.Popup {...stylex.props(s.menu)}>
                <MenuItem icon={FolderPlus} label="New subfolder" onSelect={onCreateSubfolder} />
                <MenuItem icon={Pencil} label="Rename" onSelect={onStartRename} />
                <MenuItem
                  icon={Trash2}
                  label={
                    canDelete
                      ? "Delete folder"
                      : "Delete folder — empty it first"
                  }
                  disabled={!canDelete}
                  onSelect={() => void onDelete()}
                />
              </Menu.Popup>
            </Menu.Positioner>
          </Menu.Portal>
        </Menu.Root>
      ) : null}
    </div>
  );
}

/**
 * An uncontrolled rename box that commits exactly once, whether it closes on
 * Enter, a click away, or Escape. It mounts only while its folder is renaming.
 */
function LibraryFolderRenameInput({
  initialName,
  inputRef,
  onCommit,
  onCancel,
}: {
  initialName: string;
  inputRef: React.RefObject<HTMLInputElement | null>;
  onCommit: (name: string) => void;
  onCancel: () => void;
}) {
  const settled = React.useRef(false);

  function commit(value: string): void {
    if (settled.current) return;
    settled.current = true;
    onCommit(value);
  }

  return (
    <input
      ref={inputRef}
      aria-label="Folder name"
      defaultValue={initialName}
      onClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => {
        event.stopPropagation();
        if (event.key === "Enter") {
          event.preventDefault();
          commit(event.currentTarget.value);
        }
        if (event.key === "Escape") {
          event.preventDefault();
          settled.current = true;
          onCancel();
        }
      }}
      onBlur={(event) => commit(event.currentTarget.value)}
      {...stylex.props(s.renameInput)}
    />
  );
}

function LibraryFileRow({
  file,
  workspaceId,
  selected,
  tabbable,
  onFocusRow,
  onSelect,
}: {
  file: LibraryFileNode;
  workspaceId: string;
  selected: boolean;
  tabbable: boolean;
  onFocusRow: () => void;
  onSelect: () => void;
}) {
  const { item } = file;
  const displayName = libraryFileDisplayName(item);
  const contentUrl = artifactContentUrl(workspaceId, item.artifact.content_url);
  const TypeIcon = FILE_ICONS[file.icon];
  const [thumbnailFailed, setThumbnailFailed] = React.useState(false);

  return (
    <div
      role="treeitem"
      aria-level={file.depth + 1}
      aria-selected={selected}
      draggable
      data-tree-key={file.key}
      data-tree-label={displayName}
      data-artifact-id={item.artifact.artifact_id}
      tabIndex={tabbable ? 0 : -1}
      title={`${displayName} — drag onto an input or a folder, or double-click to open`}
      onFocus={onFocusRow}
      onClick={(event) => {
        if (isRowAction(event)) return;
        onSelect();
      }}
      onDoubleClick={() => {
        if (contentUrl) window.open(contentUrl, "_blank", "noopener");
      }}
      onKeyDown={(event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        onSelect();
      }}
      onDragStart={(event) => {
        writeArtifactDrop(event.dataTransfer, {
          artifact_id: item.artifact.artifact_id,
          artifact_type: item.artifact.artifact_type,
          schema_version: item.artifact.schema_version,
          content_hash: item.artifact.sha256 ?? null,
        });
        event.dataTransfer.effectAllowed = "copyMove";
        onSelect();
      }}
      {...stylex.props(s.fileRow, selected ? s.fileRowSelected : null)}
    >
      <span {...stylex.props(s.fileThumb)}>
        {isItemImage(item) && contentUrl !== null && !thumbnailFailed ? (
          /* eslint-disable-next-line @next/next/no-img-element -- artifact bytes have no predictable size for the image optimizer */
          <img
            src={contentUrl}
            alt=""
            loading="lazy"
            decoding="async"
            onError={() => setThumbnailFailed(true)}
            {...stylex.props(s.fileThumbImage)}
          />
        ) : (
          <TypeIcon size={11} aria-hidden="true" />
        )}
      </span>
      <span {...stylex.props(s.fileCopy)}>
        <span {...stylex.props(s.fileName)}>{displayName}</span>
        <span {...stylex.props(s.fileMeta)}>{libraryFileSubtitle(item)}</span>
        {isBlobArtifact(item.artifact) ? (
          <span role="status" {...stylex.props(s.fileMeta)}>
            {BLOB_ARTIFACT_NOTICE}
          </span>
        ) : null}
      </span>
      <Menu.Root>
        <Menu.Trigger
          aria-label={`Actions for ${displayName}`}
          {...stylex.props(s.rowActions)}
        >
          <MoreHorizontal size={13} />
        </Menu.Trigger>
        <Menu.Portal>
          <Menu.Positioner
            side="bottom"
            align="end"
            sideOffset={4}
            {...stylex.props(s.menuPositioner)}
          >
            <Menu.Popup {...stylex.props(s.menu)}>
              <MenuItem
                icon={Download}
                label="Open original"
                disabled={contentUrl === null}
                onSelect={() => {
                  if (contentUrl) window.open(contentUrl, "_blank", "noopener");
                }}
              />
              <MenuItem
                icon={Link2}
                label="Copy link"
                disabled={contentUrl === null}
                onSelect={() => {
                  if (contentUrl) void navigator.clipboard?.writeText(contentUrl);
                }}
              />
            </Menu.Popup>
          </Menu.Positioner>
        </Menu.Portal>
      </Menu.Root>
    </div>
  );
}

function MenuItem({
  icon: Icon,
  label,
  disabled,
  onSelect,
}: {
  icon: LucideIcon;
  label: string;
  disabled?: boolean;
  onSelect: () => void;
}) {
  return (
    <Menu.Item
      disabled={disabled}
      onClick={onSelect}
      {...stylex.props(s.menuItem)}
    >
      <Icon size={12} aria-hidden="true" />
      {label}
    </Menu.Item>
  );
}

/**
 * The reserved tile under the browser. It shows the selected artifact itself —
 * an image or the head of a text file — plus where it came from.
 */
function LibraryArtifactTile({
  workspaceId,
  item,
  folders,
  onOpenRun,
}: {
  workspaceId: string;
  item: PlacedLibraryItem;
  folders: readonly LibraryFolder[];
  onOpenRun: (graphId: string, executionId: string) => void;
}) {
  const contentUrl = artifactContentUrl(workspaceId, item.artifact.content_url);
  const run = item.run;
  const path = libraryFolderPath(folders, item.folder_id);
  const [imageFailed, setImageFailed] = React.useState(false);
  const preview = useTextPreview(contentUrl, item);

  return (
    <aside aria-label="Selected artifact" {...stylex.props(s.inspector)}>
      <span {...stylex.props(s.inspectorTitle)}>
        {libraryFileDisplayName(item)}
      </span>
      <span {...stylex.props(s.inspectorMono)}>
        {path.length > 0 ? `/${path.join("/")}` : "/"}
        {" · "}
        {item.artifact.artifact_type}@{item.artifact.schema_version}
      </span>

      {isItemImage(item) && contentUrl !== null && !imageFailed ? (
        /* eslint-disable-next-line @next/next/no-img-element -- artifact bytes have no predictable size for the image optimizer */
        <img
          key={item.artifact.artifact_id}
          src={contentUrl}
          alt={`Preview of ${libraryFileDisplayName(item)}`}
          decoding="async"
          onError={() => setImageFailed(true)}
          {...stylex.props(s.previewImage)}
        />
      ) : null}
      {preview.text !== null ? (
        <pre {...stylex.props(s.previewText)}>{preview.text}</pre>
      ) : null}
      {preview.loading ? (
        <span role="status" {...stylex.props(s.inspectorText)}>
          Reading preview…
        </span>
      ) : null}

      <span {...stylex.props(s.inspectorLabel)}>Provenance</span>
      <span {...stylex.props(s.inspectorText)}>
        {libraryProvenanceLine(item)}
      </span>
      {run ? (
        <span {...stylex.props(s.inspectorText)}>
          {run.finished_at
            ? `finished ${new Date(run.finished_at).toLocaleString()}`
            : "run still in history"}
        </span>
      ) : null}
      <span {...stylex.props(s.inspectorActions)}>
        {contentUrl ? (
          <a href={contentUrl} target="_blank" rel="noreferrer" {...stylex.props(s.action)}>
            <Download size={11} aria-hidden="true" />
            Open original
          </a>
        ) : null}
        {run ? (
          <button
            type="button"
            {...stylex.props(s.action)}
            onClick={() => onOpenRun(run.graph_id, run.execution_id)}
          >
            <ArrowUpRight size={11} aria-hidden="true" />
            Execution history
          </button>
        ) : null}
      </span>
    </aside>
  );
}

function isPreviewableText(item: PlacedLibraryItem): boolean {
  const contentType = (item.artifact.content_type ?? "").toLowerCase();
  return (
    contentType.startsWith("text/") ||
    contentType === "application/json" ||
    contentType.endsWith("+json") ||
    contentType === "application/csv" ||
    contentType === "application/x-ndjson"
  );
}

/** The head of a text artifact, read lazily for the preview tile. */
type TextPreview = { artifactId: string; text: string };

function useTextPreview(
  contentUrl: string | null,
  item: PlacedLibraryItem,
): { text: string | null; loading: boolean } {
  const artifactId = item.artifact.artifact_id;
  const previewable = isPreviewableText(item);
  const [read, setRead] = React.useState<TextPreview | null>(null);

  React.useEffect(() => {
    if (!previewable || contentUrl === null) return;
    const controller = new AbortController();
    fetch(contentUrl, { signal: controller.signal })
      .then((response) => response.text())
      .then((body) => {
        setRead({
          artifactId,
          text:
            body.length > PREVIEW_TEXT_LIMIT
              ? `${body.slice(0, PREVIEW_TEXT_LIMIT)}\n…`
              : body,
        });
      })
      .catch(() => {
        // A preview that will not load shows the artifact's facts instead.
        setRead({ artifactId, text: "" });
      });
    return () => controller.abort();
  }, [artifactId, contentUrl, previewable]);

  const current = read?.artifactId === artifactId ? read : null;
  return {
    text: current?.text ? current.text : null,
    loading: previewable && current === null,
  };
}
