"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Collapsible } from "@base-ui/react/collapsible";
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
  Image as ImageIcon,
  LoaderCircle,
  Search,
  Table,
  Upload,
  X,
  type LucideIcon,
} from "lucide-react";

import {
  artifactContentUrl,
  listLibraryArtifacts,
  saveUploadedArtifactToLibrary,
  uploadFile,
  type LibraryItem,
} from "@/lib/api";
import { writeArtifactDrop } from "../../model/artifact-drop";
import { BLOB_ARTIFACT_NOTICE, isBlobArtifact } from "../../model/blob-notice";
import { panelStyles as s } from "./panel-styles";
import {
  buildLibraryFolders,
  isItemImage,
  libraryFileCount,
  libraryFileDisplayName,
  libraryFileSubtitle,
  libraryProvenanceLine,
  visibleLibraryFolders,
  type LibraryFileNode,
  type LibraryFolderId,
  type LibraryFolderNode,
  type LibrarySort,
} from "./library-tree";
import { useCollapsedFolderKeys } from "./workbench-side-panel-state";

const FOLDER_ICONS: Record<LibraryFolderId, LucideIcon> = {
  images: ImageIcon,
  tables: Table,
  text: FileText,
  models: Boxes,
  other: FileIcon,
};

function isFileDrag(event: React.DragEvent): boolean {
  return Array.from(event.dataTransfer.types).includes("Files");
}

function uploadErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return "The file could not be added to the Library.";
}

export function LibraryPanel({
  workspaceId,
  onOpenRun,
}: {
  workspaceId: string;
  onOpenRun: (graphId: string, executionId: string) => void;
}) {
  const { data, isLoading, error, mutate } = useSWR(
    ["library-artifacts", workspaceId],
    () => listLibraryArtifacts(workspaceId),
  );
  const [collapsedFolders, setCollapsedFolder] = useCollapsedFolderKeys();
  const [query, setQuery] = React.useState("");
  const [sort, setSort] = React.useState<LibrarySort>("name");
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [focusKey, setFocusKey] = React.useState<string | null>(null);
  const [fileDragOver, setFileDragOver] = React.useState(false);
  const [uploading, setUploading] = React.useState(false);
  const [uploadError, setUploadError] = React.useState<string | null>(null);
  const treeRef = React.useRef<HTMLDivElement>(null);
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  const items = React.useMemo(() => data?.items ?? [], [data]);
  const folders = React.useMemo(
    () => buildLibraryFolders(items, { query, sort }),
    [items, query, sort],
  );
  const filtering = query.trim() !== "";
  const shownFolders = visibleLibraryFolders(folders, query);
  const totalFiles = libraryFileCount(folders);
  const selected = items.find(
    (item) => item.artifact.artifact_id === selectedId,
  );
  /** Roving tabindex: one row in the tree is reachable by Tab. */
  const tabbableKey = focusKey ?? shownFolders[0]?.key ?? null;

  async function ingestFiles(files: File[]): Promise<void> {
    if (files.length === 0 || uploading) return;
    setUploading(true);
    setUploadError(null);
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
      }
      await mutate();
    } catch (uploadCause) {
      setUploadError(uploadErrorMessage(uploadCause));
    } finally {
      setUploading(false);
      setFileDragOver(false);
    }
  }

  function rows(): HTMLElement[] {
    const tree = treeRef.current;
    if (!tree) return [];
    return [...tree.querySelectorAll<HTMLElement>("[data-tree-key]")];
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

  /** The row the keyboard is on, when it is a file the tree can walk out of. */
  function focusedFile(): LibraryFileNode | undefined {
    const key = activeKey();
    return shownFolders
      .flatMap((folder) => folder.files)
      .find((file) => file.key === key);
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLDivElement>): void {
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
    if (event.key === "ArrowRight" && key?.startsWith("folder:")) {
      if (collapsedFolders.has(key)) {
        event.preventDefault();
        setCollapsedFolder(key, false);
      } else {
        focusByStep(1);
      }
      return;
    }
    if (event.key === "ArrowLeft") {
      if (key?.startsWith("folder:")) {
        if (!collapsedFolders.has(key)) {
          event.preventDefault();
          setCollapsedFolder(key, true);
        }
        return;
      }
      const file = focusedFile();
      if (file) {
        event.preventDefault();
        focusRow(
          treeRef.current?.querySelector<HTMLElement>(
            `[data-tree-key="folder:${file.folder}"]`,
          ),
        );
      }
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

  return (
    <div {...stylex.props(s.view)}>
      <div {...stylex.props(s.toolbar)}>
        <label {...stylex.props(s.search)}>
          <Search size={12} aria-hidden="true" />
          <input
            type="search"
            value={query}
            placeholder="Filter artifacts"
            aria-label="Filter Library artifacts"
            onChange={(event) => setQuery(event.target.value)}
            {...stylex.props(s.searchInput)}
          />
          {query ? (
            <button
              type="button"
              aria-label="Clear artifact filter"
              {...stylex.props(s.iconButton)}
              onClick={() => setQuery("")}
            >
              <X size={12} />
            </button>
          ) : null}
        </label>
        <button
          type="button"
          aria-label={sort === "name" ? "Sort artifacts by newest" : "Sort artifacts by name"}
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
            void ingestFiles(picked);
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
          if (!isFileDrag(event)) return;
          event.preventDefault();
          event.dataTransfer.dropEffect = "copy";
          setFileDragOver(true);
        }}
        onDragLeave={(event) => {
          if (event.currentTarget.contains(event.relatedTarget as Node)) return;
          setFileDragOver(false);
        }}
        onDrop={(event) => {
          if (!isFileDrag(event)) return;
          event.preventDefault();
          void ingestFiles(Array.from(event.dataTransfer.files));
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
              {uploadError ? (
                <p role="alert" {...stylex.props(s.error)}>
                  {uploadError}
                </p>
              ) : null}
              {!isLoading && totalFiles === 0 ? (
                <p {...stylex.props(s.notice)}>
                  The Library is empty. Drop a file anywhere in this panel, or
                  use Upload, to add it.
                </p>
              ) : null}
              {!isLoading && totalFiles > 0 && shownFolders.length === 0 ? (
                <p {...stylex.props(s.notice)}>
                  No Library artifact matches “{query.trim()}”.
                </p>
              ) : null}
              <div
                ref={treeRef}
                role="tree"
                aria-label="Workspace Library"
                onKeyDown={onKeyDown}
                {...stylex.props(s.listContent)}
              >
                {shownFolders.map((folder) => (
                  <LibraryFolderBranch
                    key={folder.key}
                    folder={folder}
                    workspaceId={workspaceId}
                    collapsed={collapsedFolders.has(folder.key)}
                    filtering={filtering}
                    tabbableKey={tabbableKey}
                    selectedId={selectedId}
                    onOpenChange={(open) => setCollapsedFolder(folder.key, !open)}
                    onFocusRow={setFocusKey}
                    onSelect={setSelectedId}
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
        <LibraryInspector
          workspaceId={workspaceId}
          item={selected}
          onOpenRun={onOpenRun}
        />
      ) : null}

      <footer role="status" {...stylex.props(s.statusBar)}>
        {uploading
          ? "Uploading…"
          : `${totalFiles} artifact${totalFiles === 1 ? "" : "s"}`}
      </footer>
    </div>
  );
}

/**
 * One folder and its files. An empty folder is still a folder the user can see,
 * but it has nothing to disclose, so it keeps the chevron's space without the
 * chevron.
 */
function LibraryFolderBranch({
  folder,
  workspaceId,
  collapsed,
  filtering,
  tabbableKey,
  selectedId,
  onOpenChange,
  onFocusRow,
  onSelect,
}: {
  folder: LibraryFolderNode;
  workspaceId: string;
  collapsed: boolean;
  filtering: boolean;
  tabbableKey: string | null;
  selectedId: string | null;
  onOpenChange: (open: boolean) => void;
  onFocusRow: (key: string) => void;
  onSelect: (artifactId: string) => void;
}) {
  const expandable = folder.files.length > 0;
  const open = !collapsed && expandable;

  return (
    <Collapsible.Root open={open} onOpenChange={onOpenChange}>
      <Collapsible.Trigger
        role="treeitem"
        aria-expanded={expandable ? open : undefined}
        aria-level={1}
        data-tree-key={folder.key}
        data-tree-label={folder.label}
        tabIndex={tabbableKey === folder.key ? 0 : -1}
        onFocus={() => onFocusRow(folder.key)}
        {...stylex.props(s.folderRow)}
      >
        {expandable ? (
          <ChevronRight
            size={12}
            aria-hidden="true"
            {...stylex.props(s.chevron, open ? s.chevronOpen : null)}
          />
        ) : (
          <span aria-hidden="true" {...stylex.props(s.chevronSpacer)} />
        )}
        <Folder size={13} aria-hidden="true" />
        <span {...stylex.props(s.folderName)}>{folder.label}</span>
        <span {...stylex.props(s.count)}>
          {filtering ? folder.files.length : folder.total}
        </span>
      </Collapsible.Trigger>
      <Collapsible.Panel>
        <div
          role="group"
          aria-label={`${folder.label} artifacts`}
          {...stylex.props(s.files)}
        >
          {folder.files.map((file) => (
            <LibraryFileRow
              key={file.key}
              file={file}
              workspaceId={workspaceId}
              selected={file.item.artifact.artifact_id === selectedId}
              tabbable={tabbableKey === file.key}
              onFocusRow={() => onFocusRow(file.key)}
              onSelect={() => onSelect(file.item.artifact.artifact_id)}
            />
          ))}
        </div>
      </Collapsible.Panel>
    </Collapsible.Root>
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
  const TypeIcon = FOLDER_ICONS[file.folder];
  const [thumbnailFailed, setThumbnailFailed] = React.useState(false);

  return (
    <div
      role="treeitem"
      aria-level={2}
      aria-selected={selected}
      draggable
      data-tree-key={file.key}
      data-tree-label={displayName}
      data-artifact-id={item.artifact.artifact_id}
      tabIndex={tabbable ? 0 : -1}
      title={`${displayName} — drag onto an input, or double-click to open`}
      onFocus={onFocusRow}
      onClick={onSelect}
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
    </div>
  );
}

function LibraryInspector({
  workspaceId,
  item,
  onOpenRun,
}: {
  workspaceId: string;
  item: LibraryItem;
  onOpenRun: (graphId: string, executionId: string) => void;
}) {
  const contentUrl = artifactContentUrl(workspaceId, item.artifact.content_url);
  const run = item.run;
  const hash = item.artifact.sha256?.slice(0, 12) ?? null;

  return (
    <aside aria-label="Selected artifact" {...stylex.props(s.inspector)}>
      <span {...stylex.props(s.inspectorTitle)}>
        {libraryFileDisplayName(item)}
      </span>
      <span {...stylex.props(s.inspectorLabel)}>Provenance</span>
      <span {...stylex.props(s.inspectorText)}>
        {libraryProvenanceLine(item)}
      </span>
      <span {...stylex.props(s.inspectorMono)}>
        {item.artifact.artifact_type}@{item.artifact.schema_version}
        {hash ? ` · ${hash}` : ""}
      </span>
      {item.provenance.execution_id ? (
        <span {...stylex.props(s.inspectorMono)}>
          run {item.provenance.execution_id}
        </span>
      ) : null}
      {run ? (
        <span {...stylex.props(s.inspectorText)}>
          {run.finished_at
            ? `finished ${new Date(run.finished_at).toLocaleString()}`
            : "run still in history"}
        </span>
      ) : null}
      <span {...stylex.props(s.inspectorActions)}>
        {contentUrl ? (
          <a
            href={contentUrl}
            target="_blank"
            rel="noreferrer"
            {...stylex.props(s.action)}
          >
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
