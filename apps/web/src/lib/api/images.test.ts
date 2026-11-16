import { describe, expect, it, vi } from "vitest";
import {
  getImageInfo,
  imagePath,
  imageThumbnailUrl,
  imageTileUrl,
} from "./images";

describe("TIFF API", () => {
  it("encodes identities and binds every image read to its page", () => {
    const path = imagePath("workspace/a", "scan/b");
    expect(path).toBe("/v1/workspaces/workspace%2Fa/artifacts/scan%2Fb/image");
    expect(imageThumbnailUrl(path, 2)).toBe(
      `/api${path}/thumbnail?edge=512&page=2`,
    );
    expect(imageTileUrl(path, 2, { z: 12, x: 3, y: 4, extension: "png" })).toBe(
      `/api${path}/tiles/12/3/4.png?page=2`,
    );
  });

  it("loads info through the authenticated client with cancellation", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ width: 12000 })));
    vi.stubGlobal("fetch", fetch);
    const controller = new AbortController();
    try {
      await expect(
        getImageInfo(imagePath("w", "a"), 1, controller.signal),
      ).resolves.toEqual({ width: 12000 });
      expect(fetch).toHaveBeenCalledWith(
        "/api/v1/workspaces/w/artifacts/a/image/info?page=1",
        expect.objectContaining({
          credentials: "same-origin",
          signal: controller.signal,
        }),
      );
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
