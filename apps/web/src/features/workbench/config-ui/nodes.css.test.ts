import { describe, expect, it } from "vitest";

import { artifactTypeColor } from "./nodes.css";

describe("artifactTypeColor", () => {
  it("colors artifact types introduced after the original workbench palette", () => {
    const fallback = "fallback";

    expect(artifactTypeColor("table.data", fallback)).not.toBe(fallback);
    expect(artifactTypeColor("json.schema", fallback)).not.toBe(fallback);
    expect(artifactTypeColor("prompt.message", fallback)).not.toBe(fallback);
    expect(artifactTypeColor("llm.completion", fallback)).not.toBe(fallback);
    expect(artifactTypeColor("geo.map_document", fallback)).not.toBe(fallback);
  });

  it("uses the artifact namespace for unlisted plugin types", () => {
    expect(artifactTypeColor("geo.custom_layer", "fallback")).toBe(
      "light-dark(#27865f, #3fbf88)",
    );
  });

  it("keeps the caller fallback for an unknown artifact namespace", () => {
    expect(artifactTypeColor("custom.result", "fallback")).toBe("fallback");
  });
});
