import { describe, expect, it } from "vitest";

import { SPIKES, getSpike } from "./catalog";

describe("sandbox catalog", () => {
  it("registers the port inspector spike", () => {
    expect(SPIKES.map((spike) => spike.id)).toContain("port-inspector");
    expect(getSpike("port-inspector")?.title).toBe("Port inspector");
    expect(getSpike("missing")).toBeUndefined();
  });

  it("registers the viewer link spike", () => {
    expect(SPIKES.map((spike) => spike.id)).toContain("viewer-link");
    expect(getSpike("viewer-link")?.title).toBe("Link viewers");
  });

  it("registers the port types spike", () => {
    expect(getSpike("port-types")?.title).toBe("Port types");
  });
});
