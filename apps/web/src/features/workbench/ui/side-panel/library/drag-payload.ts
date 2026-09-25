import * as React from "react";

import {
  ARTIFACT_DROP_DATA_TYPE,
  readArtifactDrop,
} from "../../../model/artifact-drop";

/** A Library folder being dragged. The canvas ignores this type. */
export const MIME_LIBRARY_FOLDER_ID = "application/x-grafy-library-folder";

export type DragKind = "upload" | "artifact" | "folder" | null;

export function dragKind(types: readonly string[]): DragKind {
  if (types.includes("Files")) return "upload";
  if (types.includes(MIME_LIBRARY_FOLDER_ID)) return "folder";
  if (types.includes(ARTIFACT_DROP_DATA_TYPE)) return "artifact";
  return null;
}

/** The artifact one drag carries, when it carries exactly one. */
export function droppedArtifactId(dataTransfer: DataTransfer): string | null {
  const dropped = readArtifactDrop(dataTransfer);
  if (dropped === null) return null;
  return "artifact_id" in dropped.value ? dropped.value.artifact_id : null;
}

export function isFileDrag(event: React.DragEvent): boolean {
  return Array.from(event.dataTransfer.types).includes("Files");
}
