import {
  checkpointProject,
  deleteProject,
  getCollaborativeHead,
  submitProjectCommand,
  type ProjectSummary,
} from "@/lib/api";

/**
 * Rename a Project that is not open in the Workbench.
 *
 * A Project's name lives in its document, so a rename is a command batch like
 * any other edit: read the head, submit against the sequence the caller saw,
 * then checkpoint so the new name survives on its own.
 */
export async function renameProjectRemote(
  workspaceId: string,
  project: ProjectSummary,
  name: string,
): Promise<void> {
  const head = await getCollaborativeHead(workspaceId, project.id);
  await submitProjectCommand(workspaceId, project.id, {
    command_id: crypto.randomUUID(),
    room_epoch: head.room_epoch,
    observed_sequence: head.collaboration_sequence,
    commands: [
      {
        kind: "rename_project",
        name,
        expected_name: head.name,
      },
    ],
  });
  await checkpointProject(workspaceId, project.id, {
    expected_room_epoch: head.room_epoch,
    expected_sequence: head.collaboration_sequence,
  });
}

/** Delete a Project when the Workbench lifecycle is not mounted. */
export async function deleteProjectRemote(
  workspaceId: string,
  project: ProjectSummary,
): Promise<boolean> {
  if (!window.confirm(`Delete “${project.name}”? This cannot be undone.`)) {
    return false;
  }
  await deleteProject(workspaceId, project.id);
  return true;
}

/** @deprecated use `renameProjectRemote`. */
export const renameSavedGraphRemote = renameProjectRemote;
/** @deprecated use `deleteProjectRemote`. */
export const deleteSavedGraphRemote = deleteProjectRemote;
