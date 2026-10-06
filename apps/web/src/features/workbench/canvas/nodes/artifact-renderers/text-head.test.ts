import { afterEach, describe, expect, it, vi } from "vitest";

import { formatTextHead, readTextHead } from "./text-head";

function respondWith(bytes: Uint8Array) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(bytes as BodyInit, { status: 200 })),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("readTextHead", () => {
  it("returns UTF-8 bytes as text", async () => {
    respondWith(new TextEncoder().encode('{"zażółć": 1}'));
    expect(await readTextHead("/x")).toEqual({
      text: '{"zażółć": 1}',
      truncated: false,
    });
  });

  it("treats bytes with a NUL as binary", async () => {
    respondWith(new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0x00]));
    expect(await readTextHead("/x")).toBeNull();
  });

  it("treats invalid UTF-8 as binary", async () => {
    respondWith(new Uint8Array([0xff, 0xfe, 0xfd]));
    expect(await readTextHead("/x")).toBeNull();
  });

  it("keeps a multibyte character cut by the limit from reading as binary", async () => {
    // "é" is two bytes; a limit of 3 splits the second one.
    respondWith(new TextEncoder().encode("aéé"));
    const head = await readTextHead("/x", 3);
    expect(head?.truncated).toBe(true);
    expect(head?.text).toBe("aé");
  });
});

describe("formatTextHead", () => {
  it("indents a complete JSON document", () => {
    expect(formatTextHead({ text: '{"a":[1,2]}', truncated: false })).toBe(
      '{\n  "a": [\n    1,\n    2\n  ]\n}',
    );
  });

  it("leaves other text and truncated JSON alone", () => {
    expect(formatTextHead({ text: "a,b\n1,2", truncated: false })).toBe(
      "a,b\n1,2",
    );
    expect(formatTextHead({ text: '{"a":1', truncated: true })).toBe('{"a":1');
  });
});
