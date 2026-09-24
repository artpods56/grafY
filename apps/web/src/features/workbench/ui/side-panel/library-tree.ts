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
  depth: number;
  icon: LibraryFileIcon;
  item: PlacedLibraryItem;
  /** True when the active filter matches this artifact. */
  matched: boolean;
};

export type LibraryFolderNode = {
  kind: "folder";
  key: string;
  id: string;
  depth: number;
  name: string;
  parentId: string | null;
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

function artifactTypeId(item: PlacedLibraryItem): string {
  return (
    item.artifact.artifact_type.split("@")[0] ?? item.artifact.artifact_type
  );
}

/**
 * The row icon. A `file.*` id names a container, so the icon follows what the
 * bytes look like; every other id names an interpreted payload.
 */
export function libraryFileIcon(item: PlacedLibraryItem): LibraryFileIcon {
  if (isItemImage(item)) return "image";
  const byType: Record<string, LibraryFileIcon> = {
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
  const mapped = byType[artifactTypeId(item)];
  if (mapped) return mapped;
  const contentType = (item.artifact.content_type ?? "").toLowerCase();
  if (contentType.startsWith("image/")) return "image";
  if (
    contentType.startsWith("text/csv") ||
    contentType.includes("tab-separated")
  ) {
    return "table";
  }
  if (
    contentType.startsWith("text/") ||
    contentType === "application/json" ||
    contentType.endsWith("+json")
  ) {
    return "text";
  }
  return "other";
}

export function isItemImage(item: PlacedLibraryItem): boolean {
  return (item.artifact.content_type ?? "").toLowerCase().startsWith("image/");
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

function folderMatches(folder: LibraryFolder, needle: string): boolean {
  return folder.name.toLowerCase().includes(needle);
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

export function buildLibraryTree(input: {
  folders: readonly LibraryFolder[];
  items: readonly PlacedLibraryItem[];
  query?: string;
  sort?: LibrarySort;
}): LibraryTreeNode[] {
  const needle = (input.query ?? "").trim().toLowerCase();
  const sort = input.sort ?? "name";

  const childFolders = new Map<string | null, LibraryFolder[]>();
  for (const folder of input.folders) {
    const siblings = childFolders.get(folder.parent_id) ?? [];
    siblings.push(folder);
    childFolders.set(folder.parent_id, siblings);
  }
  const knownFolders = new Set(input.folders.map((folder) => folder.folder_id));
  const childItems = new Map<string | null, PlacedLibraryItem[]>();
  for (const item of input.items) {
    // An artifact filed somewhere that is no longer in the tree sits at the root.
    const folderId =
      item.folder_id !== null && knownFolders.has(item.folder_id)
        ? item.folder_id
        : null;
    const siblings = childItems.get(folderId) ?? [];
    siblings.push(item);
    childItems.set(folderId, siblings);
  }

  type Built = { node: LibraryFolderNode; selfMatches: boolean };

  /**
   * Builds one folder under `revealedByAncestor`. A folder whose name matches
   * is revealed whole — that is the folder the user asked for — while a folder
   * that only holds matches is kept as a path to them.
   */
  function build(
    folder: LibraryFolder,
    depth: number,
    revealedByAncestor: boolean,
  ): Built {
    const selfMatches = needle === "" || folderMatches(folder, needle);
    const revealed = revealedByAncestor || selfMatches;
    const foldersHere = [...(childFolders.get(folder.folder_id) ?? [])].sort(
      byName,
    );
    const itemsHere = [...(childItems.get(folder.folder_id) ?? [])].sort(
      sort === "recent" ? byRecent : byName,
    );

    const nodes: LibraryTreeNode[] = [];
    let total = itemsHere.length;
    let matched = 0;

    for (const child of foldersHere) {
      const built = build(child, depth + 1, revealed);
      total += built.node.total;
      matched += built.node.matched;
      if (revealed || built.node.matched > 0 || built.selfMatches) {
        nodes.push(built.node);
      }
    }
    for (const item of itemsHere) {
      const itemMatches = revealed || matchesQuery(item, needle);
      if (!itemMatches) continue;
      matched += 1;
      nodes.push({
        kind: "file",
        key: libraryFileKey(item.artifact.artifact_id),
        depth: depth + 1,
        icon: libraryFileIcon(item),
        item,
        matched: itemMatches,
      });
    }

    return {
      selfMatches,
      node: {
        kind: "folder",
        key: libraryFolderKey(folder.folder_id),
        id: folder.folder_id,
        depth,
        name: folder.name,
        parentId: folder.parent_id,
        nodes,
        total,
        matched,
      },
    };
  }

  const roots = [...(childFolders.get(null) ?? [])]
    .sort(byName)
    .map((folder) => build(folder, 0, false))
    .filter(
      ({ node, selfMatches }) =>
        needle === "" || selfMatches || node.matched > 0,
    )
    .map(({ node }) => node);

  const rootItems = [...(childItems.get(null) ?? [])]
    .sort(sort === "recent" ? byRecent : byName)
    .filter((item) => matchesQuery(item, needle))
    .map((item) => ({
      kind: "file" as const,
      key: libraryFileKey(item.artifact.artifact_id),
      depth: 0,
      icon: libraryFileIcon(item),
      item,
      matched: true,
    }));

  return [...roots, ...rootItems];
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

/** Every artifact in the tree, however deeply filed. */
export function countLibraryArtifacts(
  roots: readonly LibraryTreeNode[],
): number {
  return roots.reduce(
    (total, node) => total + (node.kind === "folder" ? node.total : 1),
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

/** Where a row sits in the tree, outermost first — the path under the name. */
export function libraryFolderPath(
  folders: readonly LibraryFolder[],
  folderId: string | null,
): string[] {
  const path: string[] = [];
  let current = folders.find((folder) => folder.folder_id === folderId);
  while (current) {
    path.unshift(current.name);
    const parentId = current.parent_id;
    current = folders.find((folder) => folder.folder_id === parentId);
  }
  return path;
}
