"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Menu, MenuContent, MenuItem, MenuTrigger } from "@/components/ui/menu";
import {
  Boxes,
  ChevronRight,
  Download,
  File as FileIcon,
  FileCode,
  FileText,
  Folder,
  FolderOpen,
  FolderPlus,
  GripVertical,
  Image as ImageIcon,
  Link2,
  Map as MapIcon,
  MoreHorizontal,
  Pencil,
  Table2,
  Trash2,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";

import {
  artifactContentUrl,
  artifactDownloadUrl,
  type PlacedLibraryItem,
} from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { triggerArtifactDownload } from "../artifact-download";
import { BLOB_ARTIFACT_NOTICE, isBlobArtifact } from "../blob-notice";
import {
  dropEffectFor,
  libraryDragKind,
  readLibraryDrop,
  writeLibraryArtifactDrag,
  writeLibraryFolderDrag,
  type LibraryDrop,
  type LibraryDropTarget,
} from "./library-drag";
import {
  libraryClickGesture,
  type LibrarySelection,
  type LibrarySelectionGesture,
} from "./library-selection";
import {
  flattenLibraryRows,
  isBrowserRenderableImage,
  libraryFileBadge,
  libraryFileDisplayName,
  libraryFileRowMeta,
  libraryFolderKey,
  type LibraryFileBadgeKind,
  type LibraryFileNode,
  type LibraryFolderNode,
  type LibraryTreeNode,
} from "./library-tree";

const BADGE_ICONS: Record<LibraryFileBadgeKind, LucideIcon> = {
  image: ImageIcon,
  map: MapIcon,
  table: Table2,
  code: FileCode,
  text: FileText,
  model: Boxes,
  other: FileIcon,
};

/** What the tree asks of the panel. Every change goes through the server. */
export interface LibraryTreeActions {
  setFolderOpen: (key: string, open: boolean) => void;
  /**
   * Selects one artifact (`plain`), adds or removes one (`toggle`), takes the
   * range from the anchor (`range`), or clears the selection (null id).
   */
  select: (
    artifactId: string | null,
    gesture?: LibrarySelectionGesture,
  ) => void;
  /**
   * The rows a drag starting on this row carries: the whole selection when the
   * row is part of a multi-selection, otherwise this row alone, which then
   * becomes the selection. Tree order, because that is the order the canvas
   * lays the cards out in.
   */
  beginArtifactDrag: (artifactId: string) => readonly PlacedLibraryItem[];
  startRename: (folderId: string) => void;
  /** Resolves once the server has answered, whatever it answered. */
  renameFolder: (folderId: string, name: string | null) => Promise<void>;
  createSubfolder: (parentId: string) => void;
  deleteFolder: (folderId: string) => void;
  /** Asks the panel to confirm taking this artifact out of the Library. */
  requestDeleteArtifact: (artifactId: string) => void;
  drop: (drop: LibraryDrop, folderId: string | null) => void;
  setDropTarget: (target: LibraryDropTarget | null) => void;
}

interface LibraryTreeContextValue extends LibraryTreeActions {
  workspaceId: string;
  /** Whether this member may change the Library at all. */
  canEdit: boolean;
  collapsed: ReadonlySet<string>;
  filtering: boolean;
  /** Every selected artifact id; a row highlights when it is one of them. */
  selectedIds: ReadonlySet<string>;
  renamingFolderId: string | null;
  dropTarget: LibraryDropTarget | null;
  tabbableKey: string | null;
  registerRow: (key: string) => (element: HTMLElement | null) => void;
  focusRow: (key: string | null) => void;
  onRowFocus: (key: string) => void;
}

const LibraryTreeContext = React.createContext<LibraryTreeContextValue | null>(
  null,
);

function useLibraryTree(): LibraryTreeContextValue {
  const context = React.useContext(LibraryTreeContext);
  if (!context) throw new Error("Library rows render inside a LibraryTree");
  return context;
}

export function LibraryTree({
  nodes,
  workspaceId,
  canEdit,
  collapsed,
  filtering,
  selection,
  renamingFolderId,
  dropTarget,
  actions,
}: {
  nodes: readonly LibraryTreeNode[];
  workspaceId: string;
  /** Read-only members are offered nothing that the server would refuse. */
  canEdit?: boolean;
  collapsed: ReadonlySet<string>;
  filtering: boolean;
  /** What is selected right now: any number of artifacts and a range anchor. */
  selection: LibrarySelection;
  renamingFolderId: string | null;
  dropTarget: LibraryDropTarget | null;
  actions: LibraryTreeActions;
}) {
  const [focusKey, setFocusKey] = React.useState<string | null>(null);
  const rowElements = React.useRef(new Map<string, HTMLElement>());
  const visibleRows = React.useMemo(
    () => flattenLibraryRows(nodes, { collapsed }),
    [nodes, collapsed],
  );
  const selectedIds = React.useMemo(
    () => new Set(selection.ids),
    [selection.ids],
  );

  // Roving tabindex: exactly one row is reachable by Tab. It falls back to the
  // first row when the remembered one has been filtered or folded away.
  const tabbableKey =
    focusKey !== null && visibleRows.some((row) => row.key === focusKey)
      ? focusKey
      : (visibleRows[0]?.key ?? null);

  const registerRow = React.useCallback(
    (key: string) => (element: HTMLElement | null) => {
      if (element) rowElements.current.set(key, element);
      else rowElements.current.delete(key);
    },
    [],
  );

  const focusRow = React.useCallback((key: string | null) => {
    if (key === null) return;
    setFocusKey(key);
    rowElements.current.get(key)?.focus();
  }, []);

  /**
   * The row the keyboard is on. Read from the live element rather than the
   * roving-tabindex state, which is one render behind a fast key sequence.
   */
  function activeIndex(): number {
    const active = document.activeElement;
    const key =
      active instanceof HTMLElement
        ? (active.closest<HTMLElement>("[data-tree-key]")?.dataset.treeKey ??
          focusKey)
        : focusKey;
    return visibleRows.findIndex((row) => row.key === key);
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLDivElement>): void {
    if (event.target instanceof HTMLInputElement) return;
    if (visibleRows.length === 0) return;
    const index = activeIndex();
    const row = visibleRows[index];
    // `⌘`/`Ctrl` and `Shift` turn an arrow into the same gesture as the click of
    // the same name, so a keyboard can build a selection rather than only a mouse.
    // The arrow still moves first; the gesture then names the row it landed on.
    const moveGesture = libraryClickGesture(event);
    const focusAt = (next: number) => {
      event.preventDefault();
      const clamped = Math.min(visibleRows.length - 1, Math.max(0, next));
      const target = visibleRows[clamped];
      if (!target) return;
      focusRow(target.key);
      if (moveGesture === "plain") return;
      if (target.kind === "file") {
        actions.select(target.item.artifact.artifact_id, moveGesture);
      }
    };

    switch (event.key) {
      case "ArrowDown":
        return focusAt(index + 1);
      case "ArrowUp":
        return focusAt(index - 1);
      case "Home":
        return focusAt(0);
      case "End":
        return focusAt(visibleRows.length - 1);
      case "Escape":
        if (selection.ids.length > 0) {
          event.preventDefault();
          actions.select(null);
        }
        return;
    }
    if (!row) return;

    const open = row.kind === "folder" && !collapsed.has(row.key);
    const parentKey =
      row.parentId === null ? null : libraryFolderKey(row.parentId);
    switch (event.key) {
      case "ArrowRight":
        if (row.kind !== "folder") return;
        event.preventDefault();
        if (!open) actions.setFolderOpen(row.key, true);
        else if (row.nodes.length > 0) focusAt(index + 1);
        return;
      case "ArrowLeft":
        // A folder closes before the keyboard walks out of it, as in a file tree.
        if (open) {
          event.preventDefault();
          actions.setFolderOpen(row.key, false);
        } else if (parentKey !== null) {
          event.preventDefault();
          focusRow(parentKey);
        }
        return;
      case "Enter":
      case " ":
        event.preventDefault();
        if (row.kind === "folder") actions.setFolderOpen(row.key, !open);
        else actions.select(row.item.artifact.artifact_id);
        return;
      case "Delete":
      case "Backspace":
        // Deleting a row means deleting the selection when the row is part of one
        // and one row otherwise; the panel owns that choice because it owns the
        // confirmation. A viewer is offered nothing, as the server would refuse.
        if (row.kind !== "file" || !canEdit) return;
        event.preventDefault();
        actions.requestDeleteArtifact(row.item.artifact.artifact_id);
        return;
      case "F2":
        if (row.kind !== "folder") return;
        event.preventDefault();
        actions.startRename(row.id);
        return;
    }
    focusByTyping(event, index);
  }

  /** Filesystem type-ahead: a letter jumps to the next row that starts with it. */
  function focusByTyping(
    event: React.KeyboardEvent<HTMLDivElement>,
    index: number,
  ): void {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    if (event.key.length !== 1 || !/\S/.test(event.key)) return;
    const needle = event.key.toLowerCase();
    for (let offset = 1; offset <= visibleRows.length; offset += 1) {
      const candidate =
        visibleRows[
          (index + offset + visibleRows.length) % visibleRows.length
        ]!;
      if (rowLabel(candidate).toLowerCase().startsWith(needle)) {
        event.preventDefault();
        focusRow(candidate.key);
        return;
      }
    }
  }

  const context: LibraryTreeContextValue = {
    ...actions,
    workspaceId,
    canEdit: canEdit ?? true,
    collapsed,
    filtering,
    selectedIds,
    renamingFolderId,
    dropTarget,
    tabbableKey,
    registerRow,
    focusRow,
    onRowFocus: setFocusKey,
  };

  return (
    <LibraryTreeContext.Provider value={context}>
      <div
        role="tree"
        aria-label="Workspace Library"
        aria-multiselectable
        onKeyDown={onKeyDown}
        {...stylex.props(s.tree)}
      >
        <LibraryRows nodes={nodes} />
      </div>
    </LibraryTreeContext.Provider>
  );
}

function rowLabel(node: LibraryTreeNode): string {
  return node.kind === "folder" ? node.name : libraryFileDisplayName(node.item);
}

function LibraryRows({ nodes }: { nodes: readonly LibraryTreeNode[] }) {
  return nodes.map((node) =>
    node.kind === "folder" ? (
      <FolderRow key={node.key} folder={node} />
    ) : (
      <FileRow key={node.key} file={node} />
    ),
  );
}

/** Accepts drags into one folder, or into the root when `folderId` is null. */
function useDropInto(
  folderId: string | null,
  rejects?: (drop: LibraryDrop) => boolean,
) {
  const tree = useLibraryTree();
  return {
    onDragOver(event: React.DragEvent<HTMLElement>) {
      const kind = libraryDragKind(event.dataTransfer);
      if (kind === null) return;
      event.preventDefault();
      event.stopPropagation();
      event.dataTransfer.dropEffect = dropEffectFor(kind);
      tree.setDropTarget({ folderId, kind });
    },
    onDrop(event: React.DragEvent<HTMLElement>) {
      const drop = readLibraryDrop(event.dataTransfer);
      if (libraryDragKind(event.dataTransfer) === null) return;
      event.preventDefault();
      event.stopPropagation();
      tree.setDropTarget(null);
      if (drop && !rejects?.(drop)) tree.drop(drop, folderId);
    },
  };
}

/** A folder row, plus the rows it holds while it is open. */
function FolderRow({ folder }: { folder: LibraryFolderNode }) {
  const tree = useLibraryTree();
  const open = !tree.collapsed.has(folder.key);
  const renaming = tree.renamingFolderId === folder.id;
  const dropTarget = tree.dropTarget?.folderId === folder.id;
  const canDelete = folder.total === 0;
  // A folder never lands inside itself; the server would refuse it anyway.
  const drop = useDropInto(
    folder.id,
    (dropped) => dropped.kind === "folder" && dropped.folderId === folder.id,
  );

  function finishRename(name: string | null, refocus: boolean): void {
    void tree.renameFolder(folder.id, name).then(() => {
      if (refocus) tree.focusRow(folder.key);
    });
  }

  return (
    <>
      <div
        ref={tree.registerRow(folder.key)}
        role="treeitem"
        aria-expanded={open}
        aria-selected={false}
        aria-level={folder.depth + 1}
        data-tree-key={folder.key}
        data-tree-label={folder.name}
        data-drop-target={dropTarget ? "true" : undefined}
        tabIndex={tree.tabbableKey === folder.key ? 0 : -1}
        title={folder.name}
        draggable={!renaming}
        onFocus={() => tree.onRowFocus(folder.key)}
        onClick={() => tree.setFolderOpen(folder.key, !open)}
        onDragStart={(event) =>
          writeLibraryFolderDrag(event.dataTransfer, folder)
        }
        onDragEnd={() => tree.setDropTarget(null)}
        {...drop}
        {...stylex.props(
          s.row,
          s.folderRow,
          dropTarget ? s.rowDropTarget : null,
          stylex.defaultMarker(),
        )}
      >
        <ChevronRight
          size={12}
          aria-hidden="true"
          {...stylex.props(s.chevron, open ? s.chevronOpen : null)}
        />
        {open ? (
          <FolderOpen
            size={14}
            aria-hidden="true"
            {...stylex.props(s.folderIcon)}
          />
        ) : (
          <Folder
            size={14}
            aria-hidden="true"
            {...stylex.props(s.folderIcon)}
          />
        )}
        {renaming ? (
          <FolderNameInput initialName={folder.name} onDone={finishRename} />
        ) : (
          <span {...stylex.props(s.folderName)}>{folder.name}</span>
        )}
        <span {...stylex.props(s.count)}>
          {tree.filtering ? folder.matched : folder.total}
        </span>
        {renaming ? null : (
          <RowMenu label={`Actions for ${folder.name}`}>
            <RowMenuItem
              icon={FolderPlus}
              label="New subfolder"
              onSelect={() => tree.createSubfolder(folder.id)}
            />
            <RowMenuItem
              icon={Pencil}
              label="Rename"
              onSelect={() => tree.startRename(folder.id)}
            />
            <RowMenuItem
              icon={Trash2}
              label={
                canDelete ? "Delete folder" : "Delete folder — empty it first"
              }
              disabled={!canDelete}
              onSelect={() => tree.deleteFolder(folder.id)}
            />
          </RowMenu>
        )}
      </div>
      {open && folder.nodes.length > 0 ? (
        <div
          role="group"
          aria-label={`${folder.name} contents`}
          {...stylex.props(s.group)}
        >
          <LibraryRows nodes={folder.nodes} />
        </div>
      ) : null}
    </>
  );
}

/**
 * The rename box. It commits exactly once, whether it closes on Enter, a click
 * away, or Escape; an empty or unchanged name is a cancel. Only Enter and
 * Escape hand focus back to the row — a click away has put it somewhere else.
 */
function FolderNameInput({
  initialName,
  onDone,
}: {
  initialName: string;
  onDone: (name: string | null, refocus: boolean) => void;
}) {
  const settled = React.useRef(false);
  const inputRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  function settle(value: string | null, refocus: boolean): void {
    if (settled.current) return;
    settled.current = true;
    const name = value?.trim() ?? "";
    onDone(name === "" || name === initialName ? null : name, refocus);
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
          settle(event.currentTarget.value, true);
        } else if (event.key === "Escape") {
          event.preventDefault();
          settle(null, true);
        }
      }}
      onBlur={(event) => settle(event.currentTarget.value, false)}
      {...stylex.props(s.renameInput)}
    />
  );
}

function FileRow({ file }: { file: LibraryFileNode }) {
  const tree = useLibraryTree();
  const { item } = file;
  const artifactId = item.artifact.artifact_id;
  const formats = new Set(
    item.artifact.download_formats?.map(({ format }) => format),
  );
  const displayName = libraryFileDisplayName(item);
  const contentUrl = artifactContentUrl(
    tree.workspaceId,
    item.artifact.content_url,
  );
  const selected = tree.selectedIds.has(artifactId);
  const blob = isBlobArtifact(item.artifact);
  // A drop on an artifact files into the folder the artifact sits in. At the
  // root the drag falls through to the panel background, which is the root. A
  // row never accepts itself; a drag of several artifacts is a move of that set
  // into this row's folder, which is a thing the user can mean.
  const drop = useDropInto(
    file.parentId,
    (dropped) =>
      dropped.kind === "artifact" &&
      dropped.artifactIds.length === 1 &&
      dropped.artifactIds[0] === artifactId,
  );

  return (
    <div
      ref={tree.registerRow(file.key)}
      role="treeitem"
      aria-level={file.depth + 1}
      aria-selected={selected}
      draggable
      data-tree-key={file.key}
      data-tree-label={displayName}
      data-artifact-id={artifactId}
      tabIndex={tree.tabbableKey === file.key ? 0 : -1}
      title={`${displayName} — drag onto an input or a folder, or double-click to open`}
      onFocus={() => tree.onRowFocus(file.key)}
      onClick={(event) => tree.select(artifactId, libraryClickGesture(event))}
      onDoubleClick={() => openInNewTab(contentUrl)}
      onDragStart={(event) =>
        writeLibraryArtifactDrag(
          event.dataTransfer,
          tree.beginArtifactDrag(artifactId),
        )
      }
      onDragEnd={() => tree.setDropTarget(null)}
      {...(file.parentId === null ? {} : drop)}
      {...stylex.props(
        s.row,
        s.fileRow,
        selected ? s.rowSelected : null,
        stylex.defaultMarker(),
      )}
    >
      <FileThumbnail file={file} contentUrl={contentUrl} />
      <span {...stylex.props(s.fileCopy)}>
        <span
          {...stylex.props(s.fileName, selected ? s.fileNameSelected : null)}
        >
          {displayName}
        </span>
        <span {...stylex.props(s.fileMeta)}>{libraryFileRowMeta(item)}</span>
        {blob ? (
          <span role="status" {...stylex.props(s.fileMeta, s.fileWarning)}>
            <TriangleAlert size={10} aria-hidden="true" />
            {BLOB_ARTIFACT_NOTICE}
          </span>
        ) : null}
      </span>
      <span aria-hidden="true" {...stylex.props(s.dragGrip)}>
        <GripVertical size={12} />
      </span>
      <RowMenu label={`Actions for ${displayName}`} pinned={selected}>
        <RowMenuItem
          icon={Download}
          label="Open original"
          disabled={contentUrl === null}
          onSelect={() => openInNewTab(contentUrl)}
        />
        {Array.from(formats, (format) => (
          <RowMenuItem
            key={format}
            icon={Download}
            label={`Download ${format.toUpperCase()}`}
            onSelect={() =>
              triggerArtifactDownload(
                artifactDownloadUrl(tree.workspaceId, artifactId, format),
              )
            }
          />
        ))}
        <RowMenuItem
          icon={Link2}
          label="Copy link"
          disabled={contentUrl === null}
          onSelect={() => copyLink(contentUrl)}
        />
        <RowMenuItem
          icon={Trash2}
          label={
            !tree.canEdit
              ? "Delete — it needs edit access"
              : selected && tree.selectedIds.size >= 2
                ? // The row is one of several, and this menu would delete them all;
                  // a plain "Delete" would not say so.
                  `Delete ${tree.selectedIds.size} artifacts`
                : "Delete"
          }
          disabled={!tree.canEdit}
          onSelect={() => tree.requestDeleteArtifact(artifactId)}
        />
      </RowMenu>
    </div>
  );
}

function badgeToneStyle(kind: LibraryFileBadgeKind) {
  switch (kind) {
    case "image":
      return s.badgeImage;
    case "map":
      return s.badgeMap;
    case "table":
      return s.badgeTable;
    case "code":
      return s.badgeCode;
    case "text":
      return s.badgeText;
    case "model":
      return s.badgeModel;
    case "other":
      return s.badgeOther;
  }
}

function FileThumbnail({
  file,
  contentUrl,
}: {
  file: LibraryFileNode;
  contentUrl: string | null;
}) {
  const [loaded, setLoaded] = React.useState(false);
  const [failed, setFailed] = React.useState(false);
  const badge = libraryFileBadge(file.item);
  const BadgeIcon = BADGE_ICONS[badge.kind];
  const showImage =
    isBrowserRenderableImage(file.item) && contentUrl !== null && !failed;

  return (
    <span {...stylex.props(s.fileThumb, badgeToneStyle(badge.kind))}>
      <span {...stylex.props(s.fileBadgeInner)}>
        <BadgeIcon
          size={badge.ext ? 13 : 15}
          strokeWidth={1.75}
          aria-hidden="true"
        />
        {badge.ext ? (
          <span {...stylex.props(s.fileBadgeExt)}>{badge.ext}</span>
        ) : null}
      </span>
      {showImage ? (
        /* eslint-disable-next-line @next/next/no-img-element -- artifact bytes have no predictable size for the image optimizer */
        <img
          src={contentUrl}
          alt=""
          loading="lazy"
          decoding="async"
          draggable={false}
          onLoad={() => setLoaded(true)}
          onError={() => setFailed(true)}
          {...stylex.props(
            s.fileThumbImage,
            loaded ? s.fileThumbImageLoaded : null,
          )}
        />
      ) : null}
    </span>
  );
}

export function openInNewTab(url: string | null): void {
  if (url) window.open(url, "_blank", "noopener");
}

/** Content URLs are same-origin paths; a link someone pastes needs the origin. */
function copyLink(url: string | null): void {
  if (!url) return;
  void navigator.clipboard?.writeText(new URL(url, window.location.href).href);
}

/**
 * The trailing ⋯ of a row. The menu renders in a portal but React still bubbles
 * its events through the row, so the wrapper keeps clicks, keys and drags on
 * the menu from also folding the folder, selecting the artifact, or moving the
 * tree's focus.
 */
function RowMenu({
  label,
  pinned = false,
  children,
}: {
  label: string;
  /** Shown even while the row is not hovered. */
  pinned?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  const stop = (event: React.SyntheticEvent) => event.stopPropagation();

  return (
    <span
      onClick={stop}
      onDoubleClick={stop}
      onKeyDown={stop}
      onDragStart={stop}
      {...stylex.props(s.rowMenu)}
    >
      <Menu open={open} onOpenChange={setOpen}>
        <MenuTrigger
          aria-label={label}
          {...stylex.props(
            s.rowMenuTrigger,
            open || pinned ? s.rowMenuTriggerShown : null,
          )}
        >
          <MoreHorizontal size={13} />
        </MenuTrigger>
        <MenuContent
          side="bottom"
          align="end"
          sideOffset={4}
          positionerXstyle={s.menuLayer}
        >
          {children}
        </MenuContent>
      </Menu>
    </span>
  );
}

function RowMenuItem({
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
    <MenuItem
      disabled={disabled}
      onClick={onSelect}
      icon={<Icon size={12} aria-hidden="true" />}
    >
      {label}
    </MenuItem>
  );
}

/**
 * Tier 2 Gray Subsidebar tree rows: 2-line scannable files with 32×32
 * thumbnails/type badges, crisp `colorSubrailActive` selection, and clean
 * folder hierarchy.
 */
const s = stylex.create({
  tree: {
    display: "grid",
    alignContent: "start",
    gap: "2px",
  },
  row: {
    width: "100%",
    minWidth: 0,
    boxSizing: "border-box",
    display: "flex",
    alignItems: "center",
    borderRadius: tokens.radiusSm,
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorSubrailHover,
    },
    textAlign: "left",
    outlineWidth: 0,
    transitionProperty: "background-color, box-shadow",
    transitionDuration: "110ms",
    ":focus-visible": {
      outline: `2px solid ${tokens.colorAccentBorder}`,
      outlineOffset: "-2px",
    },
  },
  folderRow: {
    gap: "6px",
    padding: "5px 6px",
    color: tokens.colorMuted,
    cursor: "pointer",
    fontSize: tokens.fontSizeSm,
    fontWeight: 560,
  },
  fileRow: {
    gap: "9px",
    padding: "5px 6px",
    color: tokens.colorText,
    cursor: "grab",
  },
  rowSelected: {
    backgroundColor: {
      default: tokens.colorSubrailActive,
      ":hover": tokens.colorSubrailActive,
    },
    boxShadow: `inset 0 0 0 1px ${tokens.colorSubrailBorder}, 0 1px 2px light-dark(rgba(15, 23, 42, 0.05), rgba(0, 0, 0, 0.28))`,
  },
  /** A row a drag is over: the folder the drop will file into. */
  rowDropTarget: {
    backgroundColor: {
      default: tokens.colorAccentSoft,
      ":hover": tokens.colorAccentSoft,
    },
    boxShadow: `inset 0 0 0 1px ${tokens.colorAccentBorder}`,
  },
  chevron: {
    flexShrink: 0,
    color: tokens.colorSubtle,
    transition: "transform 140ms ease",
  },
  chevronOpen: { transform: "rotate(90deg)" },
  folderIcon: {
    flexShrink: 0,
    color: tokens.colorMuted,
  },
  folderName: {
    minWidth: 0,
    overflow: "hidden",
    color: tokens.colorTextEmphasis,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  count: {
    marginLeft: "auto",
    flexShrink: 0,
    padding: "1px 6px",
    borderRadius: "9999px",
    backgroundColor: tokens.colorSubrailHover,
    color: tokens.colorMuted,
    fontSize: "10px",
    fontWeight: 600,
    lineHeight: 1.4,
    fontVariantNumeric: "tabular-nums",
  },
  /** A folder's contents, hung from a guide under the folder's chevron. */
  group: {
    display: "grid",
    gap: "2px",
    marginInlineStart: "12px",
    paddingInlineStart: "6px",
    borderInlineStartWidth: 1,
    borderInlineStartStyle: "solid",
    borderInlineStartColor: tokens.colorSubrailBorder,
  },
  fileThumb: {
    position: "relative",
    width: "32px",
    height: "32px",
    display: "grid",
    placeItems: "center",
    flexShrink: 0,
    overflow: "hidden",
    borderRadius: tokens.radiusSm,
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorSubrailBorder,
    backgroundColor: tokens.colorSurface,
    color: tokens.colorMuted,
  },
  badgeImage: {
    backgroundColor: `color-mix(in srgb, ${tokens.colorInfo} 11%, ${tokens.colorSurface})`,
    color: tokens.colorInfo,
  },
  badgeMap: {
    backgroundColor: `color-mix(in srgb, ${tokens.colorSuccess} 11%, ${tokens.colorSurface})`,
    color: tokens.colorSuccess,
  },
  badgeTable: {
    backgroundColor: `color-mix(in srgb, ${tokens.colorSuccess} 11%, ${tokens.colorSurface})`,
    color: tokens.colorSuccess,
  },
  badgeCode: {
    backgroundColor: tokens.colorAccentSoft,
    color: tokens.colorText,
  },
  badgeText: {
    backgroundColor: `color-mix(in srgb, ${tokens.colorWarning} 11%, ${tokens.colorSurface})`,
    color: tokens.colorWarning,
  },
  badgeModel: {
    backgroundColor: tokens.colorSurfaceRaised,
    color: tokens.colorMuted,
  },
  badgeOther: {
    backgroundColor: tokens.colorSurfaceRaised,
    color: tokens.colorMuted,
  },
  fileBadgeInner: {
    display: "grid",
    justifyItems: "center",
    gap: "2px",
    lineHeight: 1,
  },
  fileBadgeExt: {
    fontSize: "7.5px",
    fontWeight: 700,
    letterSpacing: "0.04em",
    lineHeight: 1,
    textTransform: "uppercase",
  },
  fileThumbImage: {
    position: "absolute",
    inset: 0,
    width: "100%",
    height: "100%",
    display: "block",
    objectFit: "cover",
    opacity: 0,
    transitionProperty: "opacity",
    transitionDuration: "120ms",
  },
  fileThumbImageLoaded: {
    opacity: 1,
  },
  fileCopy: {
    minWidth: 0,
    flex: 1,
    display: "grid",
    gap: "2px",
  },
  fileName: {
    overflow: "hidden",
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    fontWeight: 500,
    lineHeight: 1.3,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  fileNameSelected: {
    color: tokens.colorTextEmphasis,
    fontWeight: 600,
  },
  fileMeta: {
    overflow: "hidden",
    color: tokens.colorMuted,
    fontSize: "10.5px",
    lineHeight: 1.25,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  fileWarning: {
    display: "flex",
    alignItems: "center",
    gap: "3px",
    color: tokens.colorWarning,
  },
  dragGrip: {
    flexShrink: 0,
    display: "grid",
    placeItems: "center",
    color: tokens.colorSubtle,
    pointerEvents: "none",
    opacity: {
      default: 0,
      [stylex.when.ancestor(":hover")]: 0.75,
      [stylex.when.ancestor(":focus-visible")]: 0.75,
    },
    transitionProperty: "opacity",
    transitionDuration: "100ms",
  },
  renameInput: {
    minWidth: 0,
    flex: 1,
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorderStrong,
    borderRadius: "4px",
    backgroundColor: tokens.colorSubrailActive,
    color: tokens.colorTextEmphasis,
    font: "inherit",
    fontWeight: 560,
    padding: "1px 4px",
    outline: "none",
  },
  rowMenu: { display: "flex", flexShrink: 0 },
  /**
   * The row's ⋯. With a mouse it stays out of the way until its row is
   * hovered or keyboard-focused; on touch there is no hover, so it stays.
   */
  rowMenuTrigger: {
    width: "22px",
    height: "22px",
    display: "grid",
    placeItems: "center",
    borderWidth: 0,
    borderStyle: "none",
    borderRadius: "5px",
    backgroundColor: {
      default: "transparent",
      ":hover:not(:disabled)": tokens.colorSubrailHover,
    },
    color: {
      default: tokens.colorSubtle,
      ":hover:not(:disabled)": tokens.colorTextEmphasis,
    },
    cursor: "pointer",
    opacity: {
      default: 1,
      "@media (hover: hover) and (pointer: fine)": {
        default: 0,
        ":focus-visible": 1,
        [stylex.when.ancestor(":hover")]: 1,
        [stylex.when.ancestor(":focus-visible")]: 1,
      },
    },
  },
  rowMenuTriggerShown: {
    opacity: 1,
  },
  /** Above the phone drawer (90) and the docked pane, so a row menu is never under them. */
  menuLayer: { zIndex: 100 },
});
