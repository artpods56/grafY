// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";

import { deleteProjectRemote, renameProjectRemote } from "./graph-actions";

const api = vi.hoisted(() => ({
  checkpointProject: vi.fn(),
  deleteProject: vi.fn(),
  getCollaborativeHead: vi.fn(),
  submitProjectCommand: vi.fn(),
}));

vi.mock("@/lib/api", () => api);

/**
 * A head at sequence `sequence` with its durable checkpoint `behind` steps back.
 * `checkpoint_sequence` is where the document was last saved, so a head that is
 * ahead of it holds edits only the room has seen.
 */
function headAt(
  sequence: number,
  { checkpointBehind = 0, epoch = "epoch-1" } = {},
) {
  return {
    checkpoint_revision: 2,
    checkpoint_sequence: sequence - checkpointBehind,
    collaboration_sequence: sequence,
    document: { graphs: [] },
    name: "Signal map",
    project_id: "project-1",
    room_epoch: epoch,
    updated_at: "2026-08-01T00:00:00Z",
  };
}

const project = { id: "project-1", name: "Signal map" } as never;

beforeEach(() => {
  vi.clearAllMocks();
  api.checkpointProject.mockResolvedValue({
    checkpoint_revision: 3,
    head: headAt(1),
  });
  api.deleteProject.mockResolvedValue(undefined);
  window.confirm = vi.fn(() => true);
});

describe("renameProjectRemote", () => {
  it("checkpoints at the sequence its own rename moved the head to", async () => {
    // The rename IS a write: the head goes 4 -> 5 while this call runs. A
    // checkpoint that asserts the 4 read before the submit is refused by
    // construction, so the shipped behaviour was "every rail rename fails".
    api.getCollaborativeHead.mockResolvedValue(headAt(4));
    api.submitProjectCommand.mockResolvedValue({
      head: headAt(5),
      receipt: { status: "accepted" },
    });

    await renameProjectRemote("team", project, "Signal map v2");

    expect(api.submitProjectCommand).toHaveBeenCalledWith(
      "team",
      "project-1",
      expect.objectContaining({ observed_sequence: 4 }),
    );
    expect(api.checkpointProject).toHaveBeenCalledWith("team", "project-1", {
      expected_room_epoch: "epoch-1",
      expected_sequence: 5,
    });
  });

  it("stops rather than checkpointing blind when the batch is refused", async () => {
    api.getCollaborativeHead.mockResolvedValue(headAt(4));
    api.submitProjectCommand.mockRejectedValue(new Error("head moved"));

    await expect(
      renameProjectRemote("team", project, "Signal map v2"),
    ).rejects.toThrow("head moved");
    expect(api.checkpointProject).not.toHaveBeenCalled();
  });
});

describe("deleteProjectRemote", () => {
  it("settles edits the room was holding before asking for the delete", async () => {
    // The server refuses to delete a head carrying uncheckpointed edits, and this
    // path runs from the rail, where no canvas can save them. The dialog has
    // already promised the user that unsaved changes are discarded.
    api.getCollaborativeHead
      .mockResolvedValueOnce(headAt(7, { checkpointBehind: 2 }))
      .mockResolvedValueOnce(headAt(7));

    await expect(deleteProjectRemote("team", project)).resolves.toBe(true);

    expect(api.checkpointProject).toHaveBeenCalledWith("team", "project-1", {
      expected_room_epoch: "epoch-1",
      expected_sequence: 7,
    });
    expect(api.deleteProject).toHaveBeenCalledWith("team", "project-1", {
      expectedRoomEpoch: "epoch-1",
      expectedSequence: 7,
    });
  });

  it("sends no tokens when nothing is outstanding", async () => {
    // A fresh Project head really is sequence 0, and `ge=0` on the server means a
    // guessed 0 is a number it will believe. Absence is the honest signal.
    api.getCollaborativeHead.mockResolvedValue(headAt(0));

    await expect(deleteProjectRemote("team", project)).resolves.toBe(true);

    expect(api.checkpointProject).not.toHaveBeenCalled();
    expect(api.deleteProject).toHaveBeenCalledWith("team", "project-1");
  });

  it("asks nothing of the server once the user declines", async () => {
    window.confirm = vi.fn(() => false);

    await expect(deleteProjectRemote("team", project)).resolves.toBe(false);
    expect(api.getCollaborativeHead).not.toHaveBeenCalled();
    expect(api.deleteProject).not.toHaveBeenCalled();
  });
});
