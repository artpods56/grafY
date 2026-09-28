import {
  LibraryFolderCycleError,
  LibraryFolderNameTakenError,
  LibraryFolderNotEmptyError,
} from "@/lib/api";

export function operationErrorMessage(error: unknown): string {
  if (error instanceof LibraryFolderNotEmptyError) {
    const parts = [
      error.artifactCount > 0
        ? `${error.artifactCount} artifact${error.artifactCount === 1 ? "" : "s"}`
        : null,
      error.childCount > 0
        ? `${error.childCount} folder${error.childCount === 1 ? "" : "s"}`
        : null,
    ].filter((part): part is string => part !== null);
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
