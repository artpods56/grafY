import { describe, expect, it } from "vitest";

import { getSpike } from "./catalog";

describe("sandbox catalog", () => {
  it("registers the port types spike", () => {
    expect(getSpike("port-types")?.title).toBe("Port types");
    expect(getSpike("missing")).toBeUndefined();
  });
});
