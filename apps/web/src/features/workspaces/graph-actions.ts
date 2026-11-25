import {
  deleteProject,
  exportProject,
  getCollaborativeHead,
  submitProjectCommand,
  type ProjectSummary,
} from "@/lib/api";

/** Safe download filename for a portable Project JSON export. */
export function projectExportFilename(name: string): string {
  const cleaned = name
    .trim()
    .replace(/[\\/:*?"<>|]+/g, "-")
    .replace(/\s+/g, " ")
    .replace(/\.+$/g, "")
    .trim();
  const base = cleaned || "project";
  return `${base}.grafy.json`;
}

/** Fetch a Project's portable JSON export and trigger a browser download. */
export async function exportProjectRemote(
  workspaceId: string,
  projectId: string,
  fallbackName: string,
): Promise<void> {
  const exported = await exportProject(workspaceId, projectId);
  const blob = new Blob([`${JSON.stringify(exported, null, 2)}\n`], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  try {
    const link = document.createElement("a");
    link.href = url;
    link.download = projectExportFilename(exported.name || fallbackName);
    document.body.append(link);
    link.click();
    link.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}

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
