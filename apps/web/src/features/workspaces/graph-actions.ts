import {
  checkpointProject,
  deleteProject,
  getCollaborativeHead,
  submitProjectCommand,
  type CollaborativeHead,
  type ProjectSummary,
} from "@/lib/api";

/**
 * Checkpoint at the head the server just confirmed.
 *
 * A checkpoint asserts the sequence it was taken against, and a write moves that
 * sequence. So the number to send is the one that came back **from** the write,
 * never the one read before it — a rename that checkpoints at the sequence it read
 * first is refused by construction, because its own rename already advanced it.
 */
async function checkpointAt(
  workspaceId: string,
  projectId: string,
  head: Pick<CollaborativeHead, "room_epoch" | "collaboration_sequence">,
): Promise<void> {
  await checkpointProject(workspaceId, projectId, {
    expected_room_epoch: head.room_epoch,
    expected_sequence: head.collaboration_sequence,
  });
}

/**
 * Rename a Project that is not open in the Workbench.
 *
 * A Project's name lives in its document, so a rename is a command batch like any
 * other edit: read the head, submit against the sequence the caller saw, then
 * checkpoint at the sequence the submit returned so the new name survives on its
 * own.
 */
export async function renameProjectRemote(
  workspaceId: string,
  project: ProjectSummary,
  name: string,
): Promise<void> {
  const head = await getCollaborativeHead(workspaceId, project.id);
  const accepted = await submitProjectCommand(workspaceId, project.id, {
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
  await checkpointAt(workspaceId, project.id, accepted.head);
}

/**
 * Delete a Project when the Workbench lifecycle is not mounted.
 *
 * The server refuses to delete a head carrying edits that were never checkpointed,
 * and this is the rail, where nobody is looking at a canvas: the dialog has just
 * told the user that unsaved changes are discarded, and an accepted batch sitting
 * in a room would otherwise turn that promise into a 409. Checkpointing first is
 * not a save the user asked for — the Project is gone a moment later — it is the
 * way out of a state only the room was holding.
 */
export async function deleteProjectRemote(
  workspaceId: string,
  project: ProjectSummary,
): Promise<boolean> {
  if (!window.confirm(`Delete “${project.name}”? This cannot be undone.`)) {
    return false;
  }
  const head = await getCollaborativeHead(workspaceId, project.id);
  if (head.collaboration_sequence > head.checkpoint_sequence) {
    await checkpointAt(workspaceId, project.id, head);
    const settled = await getCollaborativeHead(workspaceId, project.id);
    await deleteProject(workspaceId, project.id, {
      expectedRoomEpoch: settled.room_epoch,
      expectedSequence: settled.collaboration_sequence,
    });
    return true;
  }
  await deleteProject(workspaceId, project.id);
  return true;
}
