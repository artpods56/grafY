import {
  LibraryFolderCycleError,
  LibraryFolderNameTakenError,
  LibraryFolderNotEmptyError,
  type LibraryFolder,
  type PlacedLibraryItem,
} from "@/lib/api";

/**
 * The sentence the panel shows under the toolbar when the server refused.
 *
 * A refusal carries a code, never counts, so the contents come from the rows the
 * panel already renders. A folder whose badge reads 0 while it holds an empty
 * subfolder still offers Delete and is still refused — that count comes from
 * here, not from the error body.
 */
export function operationErrorMessage(
  error: unknown,
  folders: readonly LibraryFolder[],
  items: readonly PlacedLibraryItem[],
): string {
  if (error instanceof LibraryFolderNotEmptyError) {
    const artifactCount = items.filter(
      (item) => item.folder_id === error.folderId,
    ).length;
    const childCount = folders.filter(
      (folder) => folder.parent_id === error.folderId,
    ).length;
    const parts = [
      artifactCount > 0
        ? `${artifactCount} artifact${artifactCount === 1 ? "" : "s"}`
        : null,
      childCount > 0
        ? `${childCount} folder${childCount === 1 ? "" : "s"}`
        : null,
    ].filter((part): part is string => part !== null);
    if (parts.length === 0) {
      // The server counted something this listing never received — another
      // browser filed it. The refusal stands; only the number is unknown.
      return "Move them out first — this folder is not empty.";
    }
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
