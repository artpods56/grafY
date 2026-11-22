import {
  checkpointProject,
  getCollaborativeHead,
  type CollaborativeHead,
} from "@/lib/api";
import { ApiError } from "@/lib/api/client";

const MAX_CHECKPOINT_RETRIES = 2;

/** Checkpoint an accepted edit even if a peer adds another edit before the save. */
export async function checkpointAcceptedHead(
  workspaceId: string,
  projectId: string,
  acceptedHead: CollaborativeHead,
): Promise<CollaborativeHead> {
  let target = acceptedHead;
  for (let retries = 0; ; retries += 1) {
    try {
      const result = await checkpointProject(workspaceId, projectId, {
        expected_room_epoch: target.room_epoch,
        expected_sequence: target.collaboration_sequence,
      });
      return result.head;
    } catch (error) {
      if (
        retries === MAX_CHECKPOINT_RETRIES ||
        !(error instanceof ApiError) ||
        error.status !== 409
      ) {
        throw error;
      }

      const latest = await getCollaborativeHead(workspaceId, projectId);
      if (
        latest.room_epoch !== acceptedHead.room_epoch ||
        latest.collaboration_sequence <= target.collaboration_sequence
      ) {
        throw error;
      }
      if (latest.checkpoint_sequence === latest.collaboration_sequence) {
        return latest;
      }
      target = latest;
    }
  }
}
