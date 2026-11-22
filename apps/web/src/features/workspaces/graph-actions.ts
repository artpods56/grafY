import {
  deleteProject,
  getCollaborativeHead,
  submitProjectCommand,
  type ProjectSummary,
} from "@/lib/api";

/** Rename a Project through the same durable command journal as the room. */
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
}

/** Delete the Project at the live head observed after confirmation. */
export async function deleteProjectRemote(
  workspaceId: string,
  project: ProjectSummary,
): Promise<boolean> {
  if (!window.confirm(`Delete “${project.name}”? This cannot be undone.`)) {
    return false;
  }
  const head = await getCollaborativeHead(workspaceId, project.id);
  await deleteProject(workspaceId, project.id, {
    expectedRoomEpoch: head.room_epoch,
    expectedSequence: head.collaboration_sequence,
  });
  return true;
}
