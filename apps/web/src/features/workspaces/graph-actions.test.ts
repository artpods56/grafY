// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  deleteProjectRemote,
  exportProjectRemote,
  projectExportFilename,
  renameProjectRemote,
} from "./graph-actions";

const api = vi.hoisted(() => ({
  checkpointProject: vi.fn(),
  deleteProject: vi.fn(),
  exportProject: vi.fn(),
  getCollaborativeHead: vi.fn(),
  submitProjectCommand: vi.fn(),
}));

vi.mock("@/lib/api", () => api);

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
  it("renames through the live journal", async () => {
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
    expect(api.checkpointProject).not.toHaveBeenCalled();
  });

  it("surfaces a refused rename", async () => {
    api.getCollaborativeHead.mockResolvedValue(headAt(4));
    api.submitProjectCommand.mockRejectedValue(new Error("head moved"));

    await expect(
      renameProjectRemote("team", project, "Signal map v2"),
    ).rejects.toThrow("head moved");
    expect(api.checkpointProject).not.toHaveBeenCalled();
  });
});

describe("deleteProjectRemote", () => {
  it.each([0, 2])(
    "asserts the live head when the checkpoint is %s batches behind",
    async (behind) => {
      api.getCollaborativeHead.mockResolvedValue(
        headAt(7, { checkpointBehind: behind }),
      );

      await expect(deleteProjectRemote("team", project)).resolves.toBe(true);

      expect(api.checkpointProject).not.toHaveBeenCalled();
      expect(api.deleteProject).toHaveBeenCalledWith("team", "project-1", {
        expectedRoomEpoch: "epoch-1",
        expectedSequence: 7,
      });
    },
  );

  it("asks nothing of the server once the user declines", async () => {
    window.confirm = vi.fn(() => false);

    await expect(deleteProjectRemote("team", project)).resolves.toBe(false);
    expect(api.getCollaborativeHead).not.toHaveBeenCalled();
    expect(api.deleteProject).not.toHaveBeenCalled();
  });
});

describe("exportProjectRemote", () => {
  it("builds safe filenames for project exports", () => {
    expect(projectExportFilename("Signal / Map: v1")).toBe(
      "Signal - Map- v1.grafy.json",
    );
    expect(projectExportFilename("   ")).toBe("project.grafy.json");
  });

  it("downloads the exported project JSON envelope", async () => {
    api.exportProject.mockResolvedValue({
      format: "grafy.project",
      format_version: 1,
      name: "Signal map",
      document: { graphs: [] },
    });
    const createObjectURL = vi.fn(() => "blob:project-export");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL,
      revokeObjectURL,
    });
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);

    await exportProjectRemote("team", "project-1", "Fallback");

    expect(api.exportProject).toHaveBeenCalledWith("team", "project-1");
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:project-export");
    clickSpy.mockRestore();
  });
});
