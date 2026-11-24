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

export type LibraryArtifactCategory = "image" | "table" | "doc" | "other";

export type LibraryFileBadgeKind =
  "image" | "map" | "table" | "code" | "text" | "model" | "other";

export interface LibraryFileBadge {
  readonly kind: LibraryFileBadgeKind;
  readonly ext: string | null;
  readonly typeLabel: string;
}

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

const BROWSER_IMAGE_TYPES = new Set([
  "image/png",
  "image/jpeg",
  "image/jpg",
  "image/webp",
  "image/gif",
  "image/avif",
  "image/svg+xml",
  "image/bmp",
  "image/x-icon",
]);

/**
 * Image formats browsers decode directly in an `<img>`. Archival TIFFs and
 * JPEG 2000 scans render as file-type badges in the tree instead of blank boxes.
 */
export function isBrowserRenderableImage(item: PlacedLibraryItem): boolean {
  const mime = contentTypeOf(item).split(";")[0]?.trim() ?? "";
  return BROWSER_IMAGE_TYPES.has(mime);
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

const BADGE_FROM_CONTENT_TYPE: Readonly<
  Record<string, { ext: string; typeLabel: string }>
> = {
  "image/tiff": { ext: "TIF", typeLabel: "TIFF" },
  "image/x-tiff": { ext: "TIF", typeLabel: "TIFF" },
  "image/jpeg": { ext: "JPG", typeLabel: "JPEG" },
  "image/jpg": { ext: "JPG", typeLabel: "JPEG" },
  "image/png": { ext: "PNG", typeLabel: "PNG" },
  "image/webp": { ext: "WEBP", typeLabel: "WebP" },
  "image/gif": { ext: "GIF", typeLabel: "GIF" },
  "image/svg+xml": { ext: "SVG", typeLabel: "SVG" },
  "image/avif": { ext: "AVIF", typeLabel: "AVIF" },
  "image/jp2": { ext: "JP2", typeLabel: "JP2" },
  "application/pdf": { ext: "PDF", typeLabel: "PDF" },
  "text/csv": { ext: "CSV", typeLabel: "CSV" },
  "application/csv": { ext: "CSV", typeLabel: "CSV" },
  "text/tab-separated-values": { ext: "TSV", typeLabel: "TSV" },
  "application/geo+json": { ext: "GEO", typeLabel: "GeoJSON" },
  "application/json": { ext: "JSON", typeLabel: "JSON" },
  "application/x-ndjson": { ext: "NDJ", typeLabel: "NDJSON" },
  "text/markdown": { ext: "MD", typeLabel: "Markdown" },
  "text/plain": { ext: "TXT", typeLabel: "Text" },
  "text/html": { ext: "HTML", typeLabel: "HTML" },
  "application/xml": { ext: "XML", typeLabel: "XML" },
  "text/xml": { ext: "XML", typeLabel: "XML" },
};

const EXT_NORMALIZE: Readonly<
  Record<string, { ext: string; typeLabel: string }>
> = {
  tif: { ext: "TIF", typeLabel: "TIFF" },
  tiff: { ext: "TIF", typeLabel: "TIFF" },
  jpeg: { ext: "JPG", typeLabel: "JPEG" },
  jpg: { ext: "JPG", typeLabel: "JPEG" },
  png: { ext: "PNG", typeLabel: "PNG" },
  webp: { ext: "WEBP", typeLabel: "WebP" },
  gif: { ext: "GIF", typeLabel: "GIF" },
  svg: { ext: "SVG", typeLabel: "SVG" },
  jp2: { ext: "JP2", typeLabel: "JP2" },
  pdf: { ext: "PDF", typeLabel: "PDF" },
  csv: { ext: "CSV", typeLabel: "CSV" },
  tsv: { ext: "TSV", typeLabel: "TSV" },
  parquet: { ext: "PRQ", typeLabel: "Parquet" },
  xlsx: { ext: "XLSX", typeLabel: "Excel" },
  json: { ext: "JSON", typeLabel: "JSON" },
  geojson: { ext: "GEO", typeLabel: "GeoJSON" },
  shp: { ext: "SHP", typeLabel: "Shapefile" },
  gpkg: { ext: "GPKG", typeLabel: "GeoPackage" },
  kml: { ext: "KML", typeLabel: "KML" },
  md: { ext: "MD", typeLabel: "Markdown" },
  txt: { ext: "TXT", typeLabel: "Text" },
  xml: { ext: "XML", typeLabel: "XML" },
  yaml: { ext: "YAML", typeLabel: "YAML" },
  yml: { ext: "YML", typeLabel: "YAML" },
};

const GEO_EXTS = new Set(["GEO", "SHP", "GPKG", "KML"]);
const CODE_EXTS = new Set(["JSON", "NDJ", "XML", "YAML", "YML", "HTML"]);
const DOC_EXTS = new Set(["PDF", "TXT", "MD", "DOC", "DOCX", "RTF"]);
const IMAGE_EXTS = new Set([
  "TIF",
  "JPG",
  "PNG",
  "WEBP",
  "GIF",
  "SVG",
  "JP2",
  "AVIF",
  "BMP",
]);
const TABLE_EXTS = new Set(["CSV", "TSV", "TBL", "PRQ", "XLSX"]);

function rawExtensionOf(item: PlacedLibraryItem): string | null {
  const filename = item.provenance.original_filename ?? item.name;
  const dot = filename.lastIndexOf(".");
  if (dot <= 0 || dot === filename.length - 1) return null;
  const ext = filename.slice(dot + 1).toLowerCase();
  if (!/^[a-z0-9]{1,8}$/.test(ext)) return null;
  return ext;
}

/**
 * File-type badge metadata for the 32x32 thumbnail slot and compact row meta.
 */
export function libraryFileBadge(item: PlacedLibraryItem): LibraryFileBadge {
  const mime = contentTypeOf(item).split(";")[0]?.trim() ?? "";
  const typeId = artifactTypeId(item);
  const rawExt = rawExtensionOf(item);
  const fromExt = rawExt ? EXT_NORMALIZE[rawExt] : undefined;
  const fromMime =
    BADGE_FROM_CONTENT_TYPE[mime] ??
    (mime.endsWith("+json") ? { ext: "JSON", typeLabel: "JSON" } : undefined);

  let ext: string | null = fromExt?.ext ?? fromMime?.ext ?? null;
  let typeLabel: string = fromExt?.typeLabel ?? fromMime?.typeLabel ?? "";

  if (!typeLabel) {
    if (typeId === "geo.feature_collection") {
      ext = ext ?? "GEO";
      typeLabel = "GeoJSON";
    } else if (typeId === "table.data" || typeId === "table.csv") {
      ext = ext ?? "TBL";
      typeLabel = "Table";
    } else if (typeId === "document.page") {
      ext = ext ?? "DOC";
      typeLabel = "Document";
    } else if (typeId === "scalar.text" || typeId === "text.txt") {
      ext = ext ?? "TXT";
      typeLabel = "Text";
    } else if (typeId === "image.raster" || typeId === "image.pixmap") {
      ext = ext ?? "IMG";
      typeLabel = "Image";
    } else if (
      typeId.startsWith("model.") ||
      typeId === "module.reference" ||
      typeId === "graph.reference"
    ) {
      ext = ext ?? "MDL";
      typeLabel = "Model";
    } else if (typeId === "file.blob") {
      ext = ext ?? (rawExt ? rawExt.toUpperCase().slice(0, 4) : "FILE");
      typeLabel = rawExt ? rawExt.toUpperCase() : "Blob";
    } else if (typeId.startsWith("file.")) {
      const suffix = typeId.slice("file.".length);
      ext = ext ?? suffix.toUpperCase().slice(0, 4);
      typeLabel = suffix.toUpperCase();
    } else if (rawExt) {
      ext = rawExt.toUpperCase().slice(0, 4);
      typeLabel = rawExt.toUpperCase();
    } else {
      typeLabel = item.provenance.source === "upload" ? "File" : "Node output";
    }
  }

  let kind: LibraryFileBadgeKind;
  if (
    typeId === "geo.feature_collection" ||
    mime === "application/geo+json" ||
    (ext !== null && GEO_EXTS.has(ext))
  ) {
    kind = "map";
  } else if (isItemImage(item) || (ext !== null && IMAGE_EXTS.has(ext))) {
    kind = "image";
  } else if (
    typeId.startsWith("table.") ||
    (ext !== null && TABLE_EXTS.has(ext))
  ) {
    kind = "table";
  } else if (ext !== null && CODE_EXTS.has(ext)) {
    kind = "code";
  } else if (
    typeId === "document.page" ||
    typeId === "scalar.text" ||
    typeId === "text.txt" ||
    isItemText(item) ||
    (ext !== null && DOC_EXTS.has(ext))
  ) {
    kind = "text";
  } else if (
    typeId.startsWith("model.") ||
    typeId === "module.reference" ||
    typeId === "graph.reference"
  ) {
    kind = "model";
  } else {
    kind = "other";
  }

  return { kind, ext, typeLabel };
}

/** High-level category for quick type filter pills in the Library toolbar. */
export function libraryArtifactCategory(
  item: PlacedLibraryItem,
): LibraryArtifactCategory {
  const { kind } = libraryFileBadge(item);
  if (kind === "image" || kind === "map") return "image";
  if (kind === "table") return "table";
  if (kind === "text" || kind === "code") return "doc";
  return "other";
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
  category?: LibraryArtifactCategory | "all";
}): LibraryTreeNode[] {
  const needle = (input.query ?? "").trim().toLowerCase();
  const category = input.category ?? "all";
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
      .filter(
        (item) =>
          (category === "all" || libraryArtifactCategory(item) === category) &&
          (revealed || matchesQuery(item, needle)),
      )
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
      shown: category === "all" ? revealed || matched > 0 : matched > 0,
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
  // The item names the node it came from. It does not name a Run: the Run was
  // the demand that made that result fresh and is retired, while the result and
  // the node that produced it both outlive it.
  const parts = [
    provenance.project_title,
    provenance.graph_title,
    provenance.node_title,
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
    item.provenance.source === "upload" ? "uploaded" : "saved from a node";
  return size ? `${size} · ${origin}` : origin;
}

/** Compact 2-line row metadata for the subsidebar: size and format (e.g. `791 KB · JPEG`). */
export function libraryFileRowMeta(item: PlacedLibraryItem): string {
  const size = formatLibraryByteSize(item.artifact.byte_size);
  const { typeLabel } = libraryFileBadge(item);
  return size ? `${size} · ${typeLabel}` : typeLabel;
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
