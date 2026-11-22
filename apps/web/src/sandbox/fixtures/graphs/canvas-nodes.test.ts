import { expect, it } from "vitest";
import { cellGraphFromAuthoredDocument } from "@/features/workbench/cell-canvas/cell-document-adapter";
import {
  canvasNodesDocument,
  nodeFixtureRegistry,
  readNodeIds,
} from "./canvas-nodes";

it("defaults to Ask a model and accepts an explicitly empty canvas", () => {
  expect(readNodeIds(null)).toEqual(["ask-model"]);
  expect(readNodeIds("")).toEqual([]);
});

it("renders the requested catalog nodes and connects their schema ports", () => {
  const ids = readNodeIds("schema-builder,ask-model,schema-builder,unknown");
  const { graph, surfaceById } = cellGraphFromAuthoredDocument(
    canvasNodesDocument(ids),
    nodeFixtureRegistry,
  );
  expect(graph.cards.map(({ id }) => id)).toEqual([
    "schema-builder",
    "ask-model",
  ]);
  expect(Object.keys(surfaceById).sort()).toEqual([
    "ask-model",
    "schema-builder",
  ]);
  expect(graph.pipes).toMatchObject([
    { sourceCardId: "schema-builder", targetCardId: "ask-model" },
  ]);
  expect(canvasNodesDocument(["schema-builder"]).edges).toEqual([]);
});
