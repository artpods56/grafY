import type { LibraryFolder, PlacedLibraryItem } from "@/lib/api";

/**
 * The projection from the Workspace Library list to the folder tree the side
 * panel renders.
 *
 * The folders are the user's: they nest to any depth, they are created,
 * renamed, moved and deleted from the panel, and an artifact either sits in one
 * or sits at the root. Nothing here is derived from the artifact type — the
 * type only picks the row's icon.
 */

export type LibrarySort = "name" | "recent";

export type LibraryFileIcon = "image" | "table" | "text" | "model" | "other";

export type LibraryFileNode = {
  kind: "file";
  key: string;
  /** The folder this artifact sits in, or null at the root. */
  parentId: string | null;
  depth: number;
  icon: LibraryFileIcon;
  item: PlacedLibraryItem;
};

export type LibraryFolderNode = {
  kind: "folder";
  key: string;
  parentId: string | null;
  id: string;
  depth: number;
  name: string;
  /** Child folders and artifacts, folders first, in display order. */
  nodes: LibraryTreeNode[];
  /** Artifacts under this folder at any depth. */
  total: number;
  /** Of those, the ones the active filter matches. */
  matched: number;
};

export type LibraryTreeNode = LibraryFolderNode | LibraryFileNode;

export function libraryFolderKey(folderId: string): string {
  return `folder:${folderId}`;
}

export function libraryFileKey(artifactId: string): string {
  return `file:${artifactId}`;
}

const ICON_BY_ARTIFACT_TYPE: Readonly<Record<string, LibraryFileIcon>> = {
  "image.raster": "image",
  "image.pixmap": "image",
  "geo.raster_scan": "image",

  "table.data": "table",
  "table.csv": "table",
  "geo.feature_collection": "table",

  "text.txt": "text",
  "scalar.text": "text",
  "document.page": "text",

  "model.artifact": "model",
  "model.weights": "model",
  "model.embedding": "model",
  "module.reference": "model",
  "graph.reference": "model",
};

function artifactTypeId(item: PlacedLibraryItem): string {
  return (
    item.artifact.artifact_type.split("@")[0] ?? item.artifact.artifact_type
  );
}

function contentTypeOf(item: PlacedLibraryItem): string {
  return (item.artifact.content_type ?? "").toLowerCase();
}

/**
 * The row icon. A `file.*` id names a container, so the icon follows what the
 * bytes look like; every other id names an interpreted payload.
 */
export function libraryFileIcon(item: PlacedLibraryItem): LibraryFileIcon {
  if (isItemImage(item)) return "image";
  const mapped = ICON_BY_ARTIFACT_TYPE[artifactTypeId(item)];
  if (mapped) return mapped;
  const contentType = contentTypeOf(item);
  if (
    contentType.startsWith("text/csv") ||
    contentType.includes("tab-separated")
  ) {
    return "table";
  }
  if (isItemText(item)) return "text";
  return "other";
}

export function isItemImage(item: PlacedLibraryItem): boolean {
  return contentTypeOf(item).startsWith("image/");
}

/** Bytes a browser can show as text: the preview reads the head of these. */
export function isItemText(item: PlacedLibraryItem): boolean {
  const contentType = contentTypeOf(item);
  return (
    contentType.startsWith("text/") ||
    contentType === "application/json" ||
    contentType.endsWith("+json") ||
    contentType === "application/csv" ||
    contentType === "application/x-ndjson"
  );
}

function matchesQuery(item: PlacedLibraryItem, needle: string): boolean {
  if (needle === "") return true;
  const haystack = [
    item.name,
    item.provenance.original_filename ?? "",
    item.artifact.artifact_type,
  ]
    .join(" ")
    .toLowerCase();
  return needle.split(/\s+/).every((term) => haystack.includes(term));
}

function byName(a: { name: string }, b: { name: string }): number {
  return a.name.localeCompare(b.name, undefined, {
    numeric: true,
    sensitivity: "base",
  });
}

function byRecent(a: PlacedLibraryItem, b: PlacedLibraryItem): number {
  const saved =
    Date.parse(b.provenance.saved_at) - Date.parse(a.provenance.saved_at);
  return saved !== 0 ? saved : byName(a, b);
}

function groupBy<T>(
  values: readonly T[],
  keyOf: (value: T) => string | null,
): Map<string | null, T[]> {
  const groups = new Map<string | null, T[]>();
  for (const value of values) {
    const key = keyOf(value);
    const group = groups.get(key);
    if (group) group.push(value);
    else groups.set(key, [value]);
  }
  return groups;
}

export function buildLibraryTree(input: {
  folders: readonly LibraryFolder[];
  items: readonly PlacedLibraryItem[];
  query?: string;
  sort?: LibrarySort;
}): LibraryTreeNode[] {
  const needle = (input.query ?? "").trim().toLowerCase();
  const itemOrder = input.sort === "recent" ? byRecent : byName;

  const knownFolders = new Set(input.folders.map((folder) => folder.folder_id));
  const childFolders = groupBy(input.folders, (folder) => folder.parent_id);
  // An artifact filed somewhere that is no longer in the tree sits at the root.
  const childItems = groupBy(input.items, (item) =>
    item.folder_id !== null && knownFolders.has(item.folder_id)
      ? item.folder_id
      : null,
  );

  function fileNodes(
    folderId: string | null,
    depth: number,
    revealed: boolean,
  ): LibraryFileNode[] {
    return [...(childItems.get(folderId) ?? [])]
      .sort(itemOrder)
      .filter((item) => revealed || matchesQuery(item, needle))
      .map((item) => ({
        kind: "file",
        key: libraryFileKey(item.artifact.artifact_id),
        parentId: folderId,
        depth,
        icon: libraryFileIcon(item),
        item,
      }));
  }

  /**
   * Builds one folder, or nothing when the filter leaves it empty. A folder
   * whose name matches is revealed whole — that is the folder the user asked
   * for — while a folder that only holds matches is kept as a path to them.
   */
  function folderNode(
    folder: LibraryFolder,
    depth: number,
    revealedByAncestor: boolean,
  ): { node: LibraryFolderNode; shown: boolean } {
    const selfMatches =
      needle === "" || folder.name.toLowerCase().includes(needle);
    const revealed = revealedByAncestor || selfMatches;
    const key = libraryFolderKey(folder.folder_id);

    const nodes: LibraryTreeNode[] = [];
    let total = childItems.get(folder.folder_id)?.length ?? 0;
    let matched = 0;
    for (const child of [...(childFolders.get(folder.folder_id) ?? [])].sort(
      byName,
    )) {
      const built = folderNode(child, depth + 1, revealed);
      total += built.node.total;
      matched += built.node.matched;
      if (built.shown) nodes.push(built.node);
    }
    const files = fileNodes(folder.folder_id, depth + 1, revealed);
    matched += files.length;
    nodes.push(...files);

    return {
      shown: revealed || matched > 0,
      node: {
        kind: "folder",
        key,
        parentId: folder.parent_id,
        id: folder.folder_id,
        depth,
        name: folder.name,
        nodes,
        total,
        matched,
      },
    };
  }

  const rootFolders = [...(childFolders.get(null) ?? [])]
    .sort(byName)
    .map((folder) => folderNode(folder, 0, false))
    .filter(({ shown }) => shown)
    .map(({ node }) => node);

  return [...rootFolders, ...fileNodes(null, 0, false)];
}

/**
 * Rows in the order the panel renders them, honouring collapsed folders.
 * Keyboard navigation walks this same order, so the two never disagree.
 */
export function flattenLibraryRows(
  roots: readonly LibraryTreeNode[],
  options: { collapsed: ReadonlySet<string> } = { collapsed: new Set() },
): LibraryTreeNode[] {
  const rows: LibraryTreeNode[] = [];
  for (const node of roots) {
    rows.push(node);
    if (node.kind === "folder" && !options.collapsed.has(node.key)) {
      rows.push(...flattenLibraryRows(node.nodes, options));
    }
  }
  return rows;
}

/** The artifacts the tree shows, however deeply filed. */
export function countLibraryArtifacts(
  roots: readonly LibraryTreeNode[],
): number {
  return roots.reduce(
    (count, node) => count + (node.kind === "folder" ? node.matched : 1),
    0,
  );
}

/** The birth record line the Library keeps under an artifact name. */
export function libraryProvenanceLine(item: PlacedLibraryItem): string {
  const { provenance } = item;
  if (provenance.source === "upload") {
    return provenance.original_filename
      ? `uploaded · ${provenance.original_filename}`
      : "uploaded";
  }
  const parts = [
    provenance.graph_title,
    provenance.node_title,
    provenance.graph_revision == null
      ? null
      : `revision ${provenance.graph_revision}`,
    "from a run",
  ].filter((part): part is string => Boolean(part));
  return parts.join(" · ");
}

export function formatLibraryByteSize(
  byteSize: number | null | undefined,
): string | null {
  if (byteSize == null || !Number.isFinite(byteSize)) return null;
  if (byteSize < 1024) return `${byteSize} B`;
  const units = ["KB", "MB", "GB", "TB"] as const;
  let value = byteSize / 1024;
  let unit: string = units[0]!;
  for (const next of units.slice(1)) {
    if (value < 1024) break;
    value /= 1024;
    unit = next;
  }
  return `${value >= 10 ? Math.round(value) : value.toFixed(1)} ${unit}`;
}

/**
 * A file row is named the way a file is named. An upload keeps the filename it
 * arrived with; a Run artifact keeps the name its node gave it.
 */
export function libraryFileDisplayName(item: PlacedLibraryItem): string {
  const original = item.provenance.original_filename;
  if (item.provenance.source === "upload" && original) return original;
  return item.name;
}

/** The secondary line under a file name: size, then where it came from. */
export function libraryFileSubtitle(item: PlacedLibraryItem): string {
  const size = formatLibraryByteSize(item.artifact.byte_size);
  const origin =
    item.provenance.source === "upload" ? "uploaded" : "from a run";
  return size ? `${size} · ${origin}` : origin;
}

/** "New folder", or the first "New folder N" no sibling already uses. */
export function uniqueLibraryFolderName(
  folders: readonly LibraryFolder[],
  parentId: string | null,
): string {
  // Sibling names are unique without regard to case, as the server keeps them.
  const taken = new Set(
    folders
      .filter((folder) => folder.parent_id === parentId)
      .map((folder) => folder.name.toLowerCase()),
  );
  let name = "New folder";
  for (let suffix = 2; taken.has(name.toLowerCase()); suffix += 1) {
    name = `New folder ${suffix}`;
  }
  return name;
}

/** Where a row sits in the tree, outermost first — the path under the name. */
export function libraryFolderPath(
  folders: readonly LibraryFolder[],
  folderId: string | null,
): string[] {
  const byId = new Map(folders.map((folder) => [folder.folder_id, folder]));
  const path: string[] = [];
  // The visited set only guards a corrupt listing; the server forbids cycles.
  const visited = new Set<string>();
  let current = folderId === null ? undefined : byId.get(folderId);
  while (current && !visited.has(current.folder_id)) {
    visited.add(current.folder_id);
    path.unshift(current.name);
    current =
      current.parent_id === null ? undefined : byId.get(current.parent_id);
  }
  return path;
}
