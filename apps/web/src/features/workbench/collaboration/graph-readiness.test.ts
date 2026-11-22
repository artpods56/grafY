import { describe, expect, it } from "vitest";

import { graphReadiness } from "./graph-readiness";

describe("graphReadiness", () => {
  it("trusts only a ready room with a confirmed head", () => {
    expect(graphReadiness("ready", true)).toEqual({
      state: "current",
      trusted: true,
    });
    expect(graphReadiness("reconnecting", true)).toEqual({
      state: "stale",
      trusted: false,
    });
    expect(graphReadiness("stopped", true)).toEqual({
      state: "stale",
      trusted: false,
    });
    expect(graphReadiness("connecting", false)).toEqual({
      state: "unavailable",
      trusted: false,
    });
  });
});
