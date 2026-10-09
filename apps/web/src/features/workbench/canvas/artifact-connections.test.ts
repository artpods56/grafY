import { describe, expect, it } from "vitest";
import type {
  ArtifactRef,
  ArtifactRefSequence,
  RunNodeResult,
} from "@/lib/api";
import {
  ARTIFACT_VIEWER_EDGE_TYPE,
  type ArtifactViewerEdge,
} from "./artifact-viewer";
import {
  outputReleasePlacesArtifactCard,
  resolveArtifactCardSource,
} from "./artifact-connections";

const saved: ArtifactRef = {
  artifact_id: "saved",
  artifact_type: "file.png",
  schema_version: 1,
};
const produced: ArtifactRef = { ...saved, artifact_id: "produced" };
const sequence: ArtifactRefSequence = {
  artifact_type: "file.png",
  schema_version: 1,
  item_refs: [produced],
  sequence_id: "sequence-1",
  ordered: true,
  index_key: "order_index",
};
const feed: ArtifactViewerEdge = {
  id: "feed",
  type: ARTIFACT_VIEWER_EDGE_TYPE,
  source: "producer",
  target: "viewer",
  data: { sourcePortName: "image" },
};
const run: RunNodeResult = {
  node_id: "producer",
  status: "succeeded",
  error: null,
  outputs: [
    {
      port: "image",
      kind: "sequence",
      value: sequence,
      artifacts: [{ ...produced, content_type: "image/png" }],
    },
  ],
};

describe("releasing an output on the canvas", () => {
  it("plants a sequence card even before the output has artifacts", () => {
    expect(
      outputReleasePlacesArtifactCard({
        onCanvas: true,
        portShape: "many",
        hasMaterializedArtifacts: false,
      }),
    ).toBe(true);
  });

  it("leaves a sequence release off the canvas to the node menu", () => {
    expect(
      outputReleasePlacesArtifactCard({
        onCanvas: false,
        portShape: "many",
        hasMaterializedArtifacts: true,
      }),
    ).toBe(false);
  });

  it("opens the node menu for a single output that has not produced an artifact", () => {
    expect(
      outputReleasePlacesArtifactCard({
        onCanvas: true,
        portShape: "one",
        hasMaterializedArtifacts: false,
      }),
    ).toBe(false);
  });
});

describe("artifact source resolution", () => {
  it("preserves the exact sequence and its identity when only one item was produced", () => {
    expect(resolveArtifactCardSource({ value: saved, feed, run })).toEqual({
      kind: "output",
      value: sequence,
      output: run.outputs[0],
    });
  });

  it("does not substitute a saved artifact when the producer has not succeeded", () => {
    expect(
      resolveArtifactCardSource({
        value: saved,
        feed,
        run: { ...run, status: "failed" },
      }),
    ).toEqual({ kind: "waiting", value: null, output: null });
  });

  it("keeps a standalone card fixed even if a run is supplied", () => {
    expect(
      resolveArtifactCardSource({ value: saved, feed: undefined, run }),
    ).toEqual({ kind: "fixed", value: saved, output: null });
  });

  it("does not pass a whole artifact through a projected viewer", () => {
    const projected = {
      ...feed,
      data: { sourcePortName: "image", projection: { path: ["field"] } },
    };
    expect(
      resolveArtifactCardSource({ value: saved, feed: projected, run }),
    ).toEqual({ kind: "waiting", value: null, output: null });
  });
});
