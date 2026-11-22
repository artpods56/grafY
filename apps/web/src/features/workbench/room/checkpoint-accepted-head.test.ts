import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  checkpointProject,
  getCollaborativeHead,
  type CollaborativeHead,
} from "@/lib/api";
import { ApiError } from "@/lib/api/client";

import { checkpointAcceptedHead } from "./checkpoint-accepted-head";

vi.mock("@/lib/api", () => ({
  checkpointProject: vi.fn(),
  getCollaborativeHead: vi.fn(),
}));

const accepted: CollaborativeHead = {
  project_id: "project",
  room_epoch: "epoch",
  collaboration_sequence: 4,
  checkpoint_sequence: 3,
  checkpoint_revision: 3,
  name: "Test project",
  updated_at: "2026-08-07T10:00:00Z",
  document: { graphs: [] },
};
const peerEdit = {
  ...accepted,
  collaboration_sequence: 5,
  name: "Peer's project name",
};
const saved = { ...peerEdit, checkpoint_sequence: 5, checkpoint_revision: 4 };
const conflict = new ApiError(409, "Collaborative head moved");

beforeEach(() => vi.resetAllMocks());

describe("checkpointAcceptedHead", () => {
  it("checkpoints the peer's newer head after a sequence conflict", async () => {
    vi.mocked(checkpointProject)
      .mockRejectedValueOnce(conflict)
      .mockResolvedValueOnce({ head: saved, checkpoint_revision: 4 });
    vi.mocked(getCollaborativeHead).mockResolvedValueOnce(peerEdit);

    await expect(
      checkpointAcceptedHead("workspace", "project", accepted),
    ).resolves.toEqual(saved);
    expect(checkpointProject).toHaveBeenNthCalledWith(
      1,
      "workspace",
      "project",
      {
        expected_room_epoch: "epoch",
        expected_sequence: 4,
      },
    );
    expect(checkpointProject).toHaveBeenNthCalledWith(
      2,
      "workspace",
      "project",
      {
        expected_room_epoch: "epoch",
        expected_sequence: 5,
      },
    );
  });

  it("uses a newer head that another writer already checkpointed", async () => {
    vi.mocked(checkpointProject).mockRejectedValueOnce(conflict);
    vi.mocked(getCollaborativeHead).mockResolvedValueOnce(saved);

    await expect(
      checkpointAcceptedHead("workspace", "project", accepted),
    ).resolves.toEqual(saved);
    expect(checkpointProject).toHaveBeenCalledOnce();
  });

  it.each([accepted, { ...peerEdit, room_epoch: "new-epoch" }])(
    "preserves the conflict without verified sequence progress in the same epoch",
    async (latest) => {
      vi.mocked(checkpointProject).mockRejectedValueOnce(conflict);
      vi.mocked(getCollaborativeHead).mockResolvedValueOnce(latest);

      await expect(
        checkpointAcceptedHead("workspace", "project", accepted),
      ).rejects.toBe(conflict);
      expect(checkpointProject).toHaveBeenCalledOnce();
    },
  );
});
