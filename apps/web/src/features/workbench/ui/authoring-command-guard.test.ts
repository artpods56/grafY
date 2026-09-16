import { describe, expect, it } from "vitest";

import { shouldBlockAuthoringCommand } from "./authoring-command-guard";

describe("shouldBlockAuthoringCommand", () => {
  it("applies commands while local authoring is enabled", () => {
    expect(shouldBlockAuthoringCommand(true)).toBe(false);
  });

  it("blocks unrelated commands while local authoring is paused", () => {
    expect(shouldBlockAuthoringCommand(false)).toBe(true);
    expect(shouldBlockAuthoringCommand(false, {})).toBe(true);
  });

  it("never treats a room replay as new authoring", () => {
    expect(shouldBlockAuthoringCommand(false, { syncRoom: false })).toBe(false);
  });
});