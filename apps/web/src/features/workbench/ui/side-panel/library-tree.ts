import type { LibraryItem } from "@/lib/api";

/**
 * The projection from the flat Workspace Library list to the folder tree the
 * side panel renders. The server owns the list; the folders are a view of it.
 *
 * `libraryFolderFor` is the only place that knows how a Library artifact is
 * filed today. When #25 lands a Library folder table, that table replaces this
 * function and the tree, the panel, and the drag contract stay as they are.
 */

export type LibraryFolderId = "images" | "tables" | "text" | "models" | "other";

export type LibraryFolderSpec = { id: LibraryFolderId; label: string };

/** The standing folders. They render even when the Library is empty. */
export const LIBRARY_FOLDERS: readonly LibraryFolderSpec[] = [
  { id: "images", label: "images" },
  { id: "tables", label: "tables" },
  { id: "text", label: "text" },
  { id: "models", label: "models" },
  { id: "other", label: "other" },
];

/**
 * Artifact type id to folder. A `file.*` id names a container, so the folder
 * says what the bytes look like; every other id names an interpreted payload.
 * Anything unmapped lands in `other`, which is also where a `file.blob@1`
 * artifact waits until its format is recognised.
 */
const FOLDER_BY_TYPE: Record<string, LibraryFolderId> = {
  "image.raster": "images",
  "image.pixmap": "images",
  "geo.raster_scan": "images",
  "file.png": "images",
  "file.jpeg": "images",
  "file.webp": "images",
  "file.gif": "images",
  "file.bmp": "images",
  "file.tiff": "images",
  "file.heic": "images",
  "file.svg": "images",

  "table.data": "tables",
  "table.csv": "tables",
  "geo.feature_collection": "tables",
  "file.csv": "tables",
  "file.tsv": "tables",
  "file.xlsx": "tables",
  "file.parquet": "tables",
  "file.arrow": "tables",

  "text.txt": "text",
  "scalar.text": "text",
  "document.page": "text",
  "file.txt": "text",
  "file.md": "text",
  "file.json": "text",
  "file.ndjson": "text",
  "file.yaml": "text",
  "file.xml": "text",
  "file.html": "text",
  "file.pdf": "text",

  "model.artifact": "models",
  "model.weights": "models",
  "model.embedding": "models",
  "module.reference": "models",
  "graph.reference": "models",
  "file.onnx": "models",
  "file.pkl": "models",
  "file.joblib": "models",
};

export type LibrarySort = "name" | "recent";

export type LibraryFileNode = {
  kind: "file";
  key: string;
  folder: LibraryFolderId;
  item: LibraryItem;
};

export type LibraryFolderNode = {
  kind: "folder";
  key: string;
  id: LibraryFolderId;
  label: string;
  /** Files that match the active filter, in display order. */
  files: LibraryFileNode[];
  /** Every file filed here, matched or not. */
  total: number;
};

function artifactTypeId(item: LibraryItem): string {
  return item.artifact.artifact_type.split("@")[0] ?? item.artifact.artifact_type;
}

export function libraryFolderFor(item: LibraryItem): LibraryFolderId {
  return FOLDER_BY_TYPE[artifactTypeId(item)] ?? "other";
}

export function isItemImage(item: LibraryItem): boolean {
  return (item.artifact.content_type ?? "").toLowerCase().startsWith("image/");
}

function searchHaystack(item: LibraryItem): string {
  return [
    item.name,
    item.provenance.original_filename ?? "",
    item.artifact.artifact_type,
    libraryFolderFor(item),
  ]
    .join(" ")
    .toLowerCase();
}

function matchesQuery(item: LibraryItem, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (needle === "") return true;
  const haystack = searchHaystack(item);
  return needle
    .split(/\s+/)
    .every((term) => haystack.includes(term));
}

function byName(a: LibraryItem, b: LibraryItem): number {
  return a.name.localeCompare(b.name, undefined, {
    numeric: true,
    sensitivity: "base",
  });
}

function byRecent(a: LibraryItem, b: LibraryItem): number {
  const saved =
    Date.parse(b.provenance.saved_at) - Date.parse(a.provenance.saved_at);
  return saved !== 0 ? saved : byName(a, b);
}

export function buildLibraryFolders(
  items: readonly LibraryItem[],
  options: { query?: string; sort?: LibrarySort } = {},
): LibraryFolderNode[] {
  const sort = options.sort ?? "name";
  const filed = LIBRARY_FOLDERS.map((folder) => ({
    folder,
    all: [] as LibraryItem[],
  }));
  const indexOf = new Map(filed.map((entry, index) => [entry.folder.id, index]));

  for (const item of items) {
    const entry = filed[indexOf.get(libraryFolderFor(item))!];
    entry!.all.push(item);
  }

  return filed.map(({ folder, all }) => {
    const matching = all.filter((item) => matchesQuery(item, options.query ?? ""));
    const ordered = [...matching].sort(sort === "recent" ? byRecent : byName);
    return {
      kind: "folder" as const,
      key: `folder:${folder.id}`,
      id: folder.id,
      label: folder.label,
      total: all.length,
      files: ordered.map((item) => ({
        kind: "file" as const,
        key: `file:${item.artifact.artifact_id}`,
        folder: folder.id,
        item,
      })),
    };
  });
}

/** Folders that hold at least one match, so a filter can hide empty ones. */
export function visibleLibraryFolders(
  folders: readonly LibraryFolderNode[],
  query: string,
): LibraryFolderNode[] {
  if (query.trim() === "") return [...folders];
  return folders.filter((folder) => folder.files.length > 0);
}

export function libraryFileCount(
  folders: readonly LibraryFolderNode[],
): number {
  return folders.reduce((total, folder) => total + folder.total, 0);
}

/** The birth record line the Library keeps under an artifact name. */
export function libraryProvenanceLine(item: LibraryItem): string {
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
export function libraryFileDisplayName(item: LibraryItem): string {
  const original = item.provenance.original_filename;
  if (item.provenance.source === "upload" && original) return original;
  return item.name;
}

/** The secondary line under a file name: size, then where it came from. */
export function libraryFileSubtitle(item: LibraryItem): string {
  const size = formatLibraryByteSize(item.artifact.byte_size);
  const origin =
    item.provenance.source === "upload" ? "uploaded" : "from a run";
  return size ? `${size} · ${origin}` : origin;
}
