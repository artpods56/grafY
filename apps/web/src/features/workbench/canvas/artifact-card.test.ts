import { describe, expect, it } from "vitest";

import type { ArtifactRef } from "@/lib/api";

import {
  artifactCardContract,
  artifactCardValue,
  canMergeIntoCard,
  cardArtifactRefs,
  mergedArtifactCardValue,
  moveArtifactCardRef,
} from "./artifact-card";

function ref(id: string, artifactType = "file.jpg", schemaVersion = 1): ArtifactRef {
  return {
    artifact_id: id,
    artifact_type: artifactType,
    schema_version: schemaVersion,
  };
}

describe("artifact card value", () => {
  it("reads one artifact as a single-item card", () => {
    const single = ref("11111111-1111-1111-1111-111111111111");

    expect(cardArtifactRefs(single)).toEqual([single]);
    expect(artifactCardContract(single)).toBe("file.jpg@1");
  });

  it("reads a sequence as the ordered run it presents", () => {
    const value = artifactCardValue([ref("aaaa"), ref("bbbb")]);

    expect(value).not.toBeNull();
    expect(cardArtifactRefs(value).map((item) => item.artifact_id)).toEqual([
      "aaaa",
      "bbbb",
    ]);
    expect(artifactCardContract(value)).toBe("file.jpg@1 · 2 items");
  });

  it("refuses one card for two artifact types", () => {
    expect(
      artifactCardValue([ref("aaaa"), ref("bbbb", "table.csv")]),
    ).toBeNull();
  });

  it("keeps one sequence identity across a reorder", () => {
    const original = artifactCardValue([ref("aaaa"), ref("bbbb"), ref("cccc")]);
    const reordered = artifactCardValue(
      moveArtifactCardRef(cardArtifactRefs(original), 2, -2),
      original,
    );

    expect(cardArtifactRefs(reordered).map((item) => item.artifact_id)).toEqual([
      "cccc",
      "aaaa",
      "bbbb",
    ]);
    expect(reordered).toMatchObject({ sequence_id: (original as never as { sequence_id: string }).sequence_id });
  });

  it("clamps a reorder at the ends of the run", () => {
    const refs = [ref("aaaa"), ref("bbbb")];

    expect(
      moveArtifactCardRef(refs, 0, -4).map((item) => item.artifact_id),
    ).toEqual(["aaaa", "bbbb"]);
    expect(
      moveArtifactCardRef(refs, 1, 4).map((item) => item.artifact_id),
    ).toEqual(["aaaa", "bbbb"]);
  });

  it("appends a dropped card's artifacts once, in drop order", () => {
    const target = artifactCardValue([ref("aaaa"), ref("bbbb")]);
    const merged = mergedArtifactCardValue(target, ref("cccc"));

    expect(cardArtifactRefs(merged).map((item) => item.artifact_id)).toEqual([
      "aaaa",
      "bbbb",
      "cccc",
    ]);
    expect(mergedArtifactCardValue(target, ref("aaaa"))).toBeNull();
  });

  it("will not merge cards of different artifact types", () => {
    expect(
      canMergeIntoCard(artifactCardValue([ref("aaaa")]), ref("zzzz", "scalar.text")),
    ).toBe(false);
    expect(canMergeIntoCard(artifactCardValue([ref("aaaa")]), ref("zzzz"))).toBe(
      true,
    );
  });
});
