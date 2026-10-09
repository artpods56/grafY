import { describe, expect, it } from "vitest";

import type { WorkflowInputPlug } from "./input-plugs";
import {
  artifactQueryRelations,
  createArtifactQueryRelation,
  moveArtifactQueryRelation,
  reconcileArtifactQueryRelationInputPlugs,
  removeArtifactQueryRelation,
  type ArtifactQueryRelation,
} from "./query-artifact-tables";

describe("Query artifact table relations", () => {
  it("keeps editable aliases while rejecting malformed or duplicate identities", () => {
    expect(
      artifactQueryRelations([
        { id: "parcels-plug", alias: "parcels" },
        { id: "owners-plug", alias: "owners" },
        { id: "parcels-plug", alias: "duplicate_id" },
        { id: "duplicate-alias", alias: "OWNERS" },
        { id: "empty-alias", alias: "" },
        { id: "invalid-alias", alias: "not a table" },
        { id: "missing-alias" },
        { id: "", alias: "missing_id" },
      ]),
    ).toEqual([
      { id: "parcels-plug", alias: "parcels" },
      { id: "owners-plug", alias: "owners" },
      { id: "duplicate-alias", alias: "OWNERS" },
      { id: "empty-alias", alias: "" },
      { id: "invalid-alias", alias: "not a table" },
    ]);
    expect(artifactQueryRelations({ relations: [] })).toEqual([]);
  });

  it("creates a unique default alias while accepting a caller-owned plug id", () => {
    const existing: ArtifactQueryRelation[] = [
      { id: "a", alias: "relation_2" },
      { id: "b", alias: "RELATION_3" },
    ];

    expect(createArtifactQueryRelation(0, "initial-plug")).toEqual({
      id: "initial-plug",
      alias: "relation_1",
    });
    expect(createArtifactQueryRelation(1, "stable-plug", existing)).toEqual({
      id: "stable-plug",
      alias: "relation_4",
    });
  });

  it("removes and reorders relations without changing stable identities", () => {
    const relations: ArtifactQueryRelation[] = [
      { id: "a", alias: "alpha" },
      { id: "b", alias: "bravo" },
      { id: "c", alias: "charlie" },
    ];

    const remaining = removeArtifactQueryRelation(relations, "b");
    expect(moveArtifactQueryRelation(remaining, "c", 0)).toEqual([
      { id: "c", alias: "charlie" },
      { id: "a", alias: "alpha" },
    ]);
    const firstRelation = relations[0];
    if (!firstRelation) throw new Error("expected a first relation");
    expect(removeArtifactQueryRelation([firstRelation], "a")).toEqual([
      { id: "a", alias: "alpha" },
    ]);
    expect(relations.map((relation) => relation.id)).toEqual(["a", "b", "c"]);
  });

  it("aligns relation plugs to relation ids and order", () => {
    const inputPlugs: WorkflowInputPlug[] = [
      { id: "statement-a", portName: "statements" },
      { id: "stale-relation", portName: "relations" },
      { id: "other", portName: "other" },
      { id: "statement-b", portName: "statements" },
    ];
    const relations: ArtifactQueryRelation[] = [
      { id: "owners-plug", alias: "owners" },
      { id: "parcels-plug", alias: "parcels" },
    ];

    expect(
      reconcileArtifactQueryRelationInputPlugs(inputPlugs, relations),
    ).toEqual([
      { id: "statement-a", portName: "statements" },
      { id: "owners-plug", portName: "relations" },
      { id: "parcels-plug", portName: "relations" },
      { id: "other", portName: "other" },
      { id: "statement-b", portName: "statements" },
    ]);
    expect(inputPlugs.map((plug) => plug.id)).toEqual([
      "statement-a",
      "stale-relation",
      "other",
      "statement-b",
    ]);
  });
});
