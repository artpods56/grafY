import { describe, expect, it } from "vitest";

import type { ArtifactRef } from "@/lib/api";

import {
  artifactCardContract,
  artifactCardValue,
  canMergeIntoCard,
  cardArtifactRefs,
  isImageArtifact,
  mergedArtifactCardValue,
  moveArtifactCardRef,
  originCarriesCardArtifacts,
  presentsArtifacts,
  type ArtifactCardValue,
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

  it("tells a card that carries artifacts from a viewer that does not", () => {
    expect(presentsArtifacts(ref("aaaa"))).toBe(true);
    expect(presentsArtifacts(null)).toBe(false);
    expect(presentsArtifacts(undefined)).toBe(false);
  });

  it("knows an origin carries what a card presents", () => {
    const card = artifactCardValue([ref("aaaa"), ref("bbbb")]);

    expect(originCarriesCardArtifacts(ref("aaaa"), card)).toBe(true);
    expect(originCarriesCardArtifacts(ref("bbbb"), card)).toBe(true);
    expect(originCarriesCardArtifacts(ref("cccc"), card)).toBe(false);
    expect(originCarriesCardArtifacts(ref("aaaa"), null)).toBe(false);
    const partlyDifferent: ArtifactCardValue = {
      artifact_type: "file.jpg",
      schema_version: 1,
      item_refs: [ref("aaaa"), ref("cccc")],
      ordered: true,
      index_key: "order_index",
    };

    expect(originCarriesCardArtifacts(partlyDifferent, card)).toBe(false);
  });

  it("paints an artifact by its declared type when no content type is known", () => {
    expect(isImageArtifact(ref("aaaa", "file.jpeg"))).toBe(true);
    expect(isImageArtifact(ref("aaaa", "file.csv"))).toBe(false);
    expect(isImageArtifact(ref("aaaa", "file.csv"), "image/png")).toBe(true);
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
