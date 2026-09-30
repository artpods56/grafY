import type { PlacedLibraryItem } from "@/lib/api";
import {
  ARTIFACT_DROP_DATA_TYPE,
  readArtifactDrop,
  writeArtifactDrop,
} from "../../model/artifact-drop";

/**
 * What the Library tree can be handed by a drag: files from the desktop, one of
 * its own artifacts, or one of its own folders. The canvas reads artifact drags
 * too; it ignores the folder type.
 */

export const LIBRARY_FOLDER_DATA_TYPE = "application/x-grafy-library-folder";

export type LibraryDragKind = "upload" | "artifact" | "folder";

export type LibraryDrop =
  | { kind: "upload"; files: File[] }
  | { kind: "artifact"; artifactId: string }
  | { kind: "folder"; folderId: string };

/** Where a drag would land if it dropped now: a folder, or the root (null). */
export type LibraryDropTarget = {
  folderId: string | null;
  kind: LibraryDragKind;
};

/**
 * What a drag carries, from its types alone. A drag's data is unreadable until
 * the drop, so this is all `dragover` has to decide whether to accept it.
 */
export function libraryDragKind(
  dataTransfer: DataTransfer,
): LibraryDragKind | null {
  const types = Array.from(dataTransfer.types ?? []);
  if (types.includes("Files")) return "upload";
  if (types.includes(LIBRARY_FOLDER_DATA_TYPE)) return "folder";
  if (types.includes(ARTIFACT_DROP_DATA_TYPE)) return "artifact";
  return null;
}

/** Reads a drop, or null when it carries nothing the Library can file. */
export function readLibraryDrop(
  dataTransfer: DataTransfer,
): LibraryDrop | null {
  switch (libraryDragKind(dataTransfer)) {
    case "upload": {
      const files = Array.from(dataTransfer.files ?? []);
      return files.length > 0 ? { kind: "upload", files } : null;
    }
    case "folder": {
      const folderId = dataTransfer.getData(LIBRARY_FOLDER_DATA_TYPE);
      return folderId ? { kind: "folder", folderId } : null;
    }
    case "artifact": {
      // A drag of many artifacts comes from the canvas, never from a Library row.
      const value = readArtifactDrop(dataTransfer)?.value;
      return value && "artifact_id" in value
        ? { kind: "artifact", artifactId: value.artifact_id }
        : null;
    }
    default:
      return null;
  }
}

export function writeLibraryArtifactDrag(
  dataTransfer: DataTransfer,
  item: PlacedLibraryItem,
): void {
  writeArtifactDrop(dataTransfer, {
    artifact_id: item.artifact.artifact_id,
    artifact_type: item.artifact.artifact_type,
    schema_version: item.artifact.schema_version,
    content_hash: item.artifact.sha256 ?? null,
  });
  // Copy onto the canvas, move between folders.
  dataTransfer.effectAllowed = "copyMove";
}

export function writeLibraryFolderDrag(
  dataTransfer: DataTransfer,
  folderId: string,
): void {
  dataTransfer.setData(LIBRARY_FOLDER_DATA_TYPE, folderId);
  dataTransfer.effectAllowed = "move";
}

export function dropEffectFor(kind: LibraryDragKind): "copy" | "move" {
  return kind === "upload" ? "copy" : "move";
}
