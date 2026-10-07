import type { ArtifactRef, PlacedLibraryItem } from "@/lib/api";
import {
  ARTIFACT_DROP_DATA_TYPE,
  artifactDropPayload,
  readArtifactDrop,
  writeArtifactDropFolder,
  writeArtifactDropGroups,
  type ArtifactDropValue,
} from "../../model/artifact-drop";
import { artifactCardValue } from "../../canvas/artifact-card";
import { artifactTypeKey } from "../../canvas/artifact-type-key";
import type { LibraryFolderNode } from "./library-tree";

/**
 * What the Library tree can be handed by a drag: files from the desktop, one or
 * more of its own artifacts, or one of its own folders. The canvas reads artifact
 * drags too; it ignores the folder type.
 */

export const LIBRARY_FOLDER_DATA_TYPE = "application/x-grafy-library-folder";

/**
 * The artifacts a Library drag moves between folders.
 *
 * The canvas payload describes what the artifacts ARE; a move needs the ids of
 * every row the drag picked up, including the ones grouped into a card the
 * canvas never sees as separate rows. So it rides along as its own type instead
 * of being squeezed into the canvas payload.
 */
export const LIBRARY_MOVE_DATA_TYPE = "application/x-grafy-library-move";

export type LibraryDragKind = "upload" | "artifact" | "folder";

export type LibraryDrop =
  | { kind: "upload"; files: File[] }
  | { kind: "artifact"; artifactIds: string[] }
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
  if (
    types.includes(ARTIFACT_DROP_DATA_TYPE) ||
    types.includes(LIBRARY_MOVE_DATA_TYPE)
  ) {
    return "artifact";
  }
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
      const moved = readLibraryMoveIds(dataTransfer);
      if (moved.length > 0) return { kind: "artifact", artifactIds: moved };
      // A drag of many artifacts comes from the canvas, never from a Library
      // row, so only a single artifact reference is a row this Library can file.
      const value = readArtifactDrop(dataTransfer)?.value;
      return value && "artifact_id" in value
        ? { kind: "artifact", artifactIds: [value.artifact_id] }
        : null;
    }
    default:
      return null;
  }
}

function readLibraryMoveIds(dataTransfer: DataTransfer): string[] {
  const raw = dataTransfer.getData(LIBRARY_MOVE_DATA_TYPE);
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((id): id is string => typeof id === "string");
  } catch {
    return [];
  }
}

/**
 * The canvas values one set of Library artifacts turns into.
 *
 * Artifacts of the same type and schema version go on one card — a lone one as
 * a single reference, several as a sequence — because that is the only thing a
 * card can honestly present. Different types never share a card, so a selection
 * spanning three types becomes three cards, in the order the rows appear in the
 * tree: the caller passes them in that order and grouping keeps it, dating each
 * group from the first row of it the user can see.
 */
export function artifactDropGroups(
  items: readonly PlacedLibraryItem[],
): ArtifactDropValue[] {
  const groups = new Map<string, ArtifactRef[]>();
  for (const item of items) {
    const ref: ArtifactRef = {
      artifact_id: item.artifact.artifact_id,
      artifact_type: item.artifact.artifact_type,
      schema_version: item.artifact.schema_version,
      content_hash: item.artifact.sha256 ?? null,
    };
    const key = artifactTypeKey({
      id: ref.artifact_type,
      schema_version: ref.schema_version,
    });
    const group = groups.get(key);
    if (group) group.push(ref);
    else groups.set(key, [ref]);
  }
  return [...groups.values()]
    .map((refs) => artifactCardValue(refs))
    .filter((value): value is ArtifactDropValue => value !== null);
}

/**
 * Write a Library artifact drag: the canvas payloads, and the id list a folder
 * drop needs to move every picked-up row.
 *
 * `items` is in tree order. One artifact writes what it always wrote; a group
 * adds the grouped type on top, so an older canvas still lands the first group.
 */
export function writeLibraryArtifactDrag(
  dataTransfer: DataTransfer,
  items: readonly PlacedLibraryItem[],
): void {
  const groups = artifactDropGroups(items);
  if (groups.length === 0) return;
  writeArtifactDropGroups(dataTransfer, groups.map(artifactDropPayload));
  dataTransfer.setData(
    LIBRARY_MOVE_DATA_TYPE,
    JSON.stringify(items.map((item) => item.artifact.artifact_id)),
  );
  // Copy onto the canvas, move between folders.
  dataTransfer.effectAllowed = "copyMove";
}

/**
 * Every artifact a folder shows, at any depth, in the order its rows appear:
 * subfolders first, then the folder's own artifacts. A filter that hides rows
 * hides them from the drag too, so the drag carries what the user can see.
 */
export function folderArtifactItems(
  folder: LibraryFolderNode,
): PlacedLibraryItem[] {
  return folder.nodes.flatMap((node) =>
    node.kind === "folder" ? folderArtifactItems(node) : [node.item],
  );
}

/**
 * Write a Library folder drag.
 *
 * Inside the Library it moves the folder. Onto the canvas it carries the
 * folder's artifacts as one group per type, marked as a folder so the drop can
 * ask which groups to place when the folder holds more than one type. An empty
 * folder carries nothing the canvas could use, so it stays a Library-only drag.
 */
export function writeLibraryFolderDrag(
  dataTransfer: DataTransfer,
  folder: LibraryFolderNode,
): void {
  dataTransfer.setData(LIBRARY_FOLDER_DATA_TYPE, folder.id);
  const groups = artifactDropGroups(folderArtifactItems(folder));
  if (groups.length === 0) {
    dataTransfer.effectAllowed = "move";
    return;
  }
  writeArtifactDropGroups(dataTransfer, groups.map(artifactDropPayload));
  writeArtifactDropFolder(dataTransfer, folder.name);
  // Copy onto the canvas, move between folders.
  dataTransfer.effectAllowed = "copyMove";
}

export function dropEffectFor(kind: LibraryDragKind): "copy" | "move" {
  return kind === "upload" ? "copy" : "move";
}
