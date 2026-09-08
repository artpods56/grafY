import { afterEach, describe, expect, it, vi } from "vitest";

import { createUuid } from "./uuid";

describe("workbench UUIDs", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("uses the native UUID generator when available", () => {
    const expected = "bb7d0762-4823-46d0-98d0-aecb8ed52f07";
    vi.stubGlobal("crypto", { randomUUID: () => expected });

    expect(createUuid()).toBe(expected);
  });

  it.each([
    [0x00, "00000000-0000-4000-8000-000000000000"],
    [0xff, "ffffffff-ffff-4fff-bfff-ffffffffffff"],
  ])("formats random byte %i as a version 4 UUID on HTTP", (byte, expected) => {
    vi.stubGlobal("crypto", {
      getRandomValues(bytes: Uint8Array) {
        bytes.fill(byte);
        return bytes;
      },
    });

    expect(createUuid()).toBe(expected);
  });
});
