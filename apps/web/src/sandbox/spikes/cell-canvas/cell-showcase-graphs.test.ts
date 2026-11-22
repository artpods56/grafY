import { describe, expect, it } from "vitest";

import type {
  CellCardModel,
  CellRect,
} from "@/features/workbench/cell-canvas/cell-model";
import { routeCellGraph } from "@/features/workbench/cell-canvas/cell-router";
import { cellGraphFromAuthoredDocument } from "@/features/workbench/cell-canvas/cell-document-adapter";
import { applyGraphCommandNormalized } from "@/features/workbench/authoring/graph-document";

import {
  createRealAnatomyShowcaseGraph,
  createShowcaseAuthoredDocument,
  createStressGroupBenchmarkGraph,
  mergeShowcaseRegistry,
  showcaseFallbackRegistry,
} from "./cell-showcase-graphs";

function rectanglesOverlap(a: CellRect, b: CellRect): boolean {
  return (
    a.col < b.col + b.widthCells &&
    b.col < a.col + a.widthCells &&
    a.row < b.row + b.heightCells &&
    b.row < a.row + a.heightCells
  );
}

function overlappingPairs(cards: readonly CellCardModel[]): string[] {
  return cards.flatMap((card, index) =>
    cards
      .slice(index + 1)
      .filter((other) => rectanglesOverlap(card, other))
      .map((other) => `${card.id} overlaps ${other.id}`),
  );
}

describe("real anatomy showcase graph", () => {
  it("gives every card matching surface data and valid cell coordinates and ports", () => {
    const { graph, surfaceById } = createRealAnatomyShowcaseGraph();

    for (const card of graph.cards) {
      expect(surfaceById[card.id]?.kind, card.id).toBe(card.kind ?? "operator");
      for (const value of [
        card.col,
        card.row,
        card.widthCells,
        card.heightCells,
      ]) {
        expect(Number.isInteger(value), card.id).toBe(true);
      }
      for (const port of card.ports) {
        const label = `${card.id}.${port.id}`;
        expect(port.rowOffset, label).toBeGreaterThanOrEqual(1);
        expect(port.rowOffset, label).toBeLessThan(card.heightCells);
      }
    }
  });

  it("keeps cards clear of each other outside the annotation frame", () => {
    const { graph, surfaceById } = createRealAnatomyShowcaseGraph();
    const nonFrameCards = graph.cards.filter((card) => {
      const surface = surfaceById[card.id];
      return surface?.kind !== "annotation" || surface.variant !== "frame";
    });
    const foregroundCards = graph.cards.filter((card) => {
      const surface = surfaceById[card.id];
      return surface?.kind !== "annotation" || surface.layer !== "under-cards";
    });

    expect(overlappingPairs(nonFrameCards)).toEqual([]);
    expect(overlappingPairs(foregroundCards)).toEqual([]);
  });

  it("lines the scan output up with the OCR input across a three-cell gap", () => {
    const { graph } = createRealAnatomyShowcaseGraph();
    const pipe = graph.pipes.find((pipe) => pipe.id === "scan-to-ocr");
    expect(pipe).toMatchObject({
      sourceCardId: "doc-scan",
      sourcePortId: "image",
      targetCardId: "ocr-extract",
      targetPortId: "source",
    });
    const source = graph.cards.find((card) => card.id === pipe?.sourceCardId);
    const target = graph.cards.find((card) => card.id === pipe?.targetCardId);
    const sourcePort = source?.ports.find(
      (port) => port.id === pipe?.sourcePortId,
    );
    const targetPort = target?.ports.find(
      (port) => port.id === pipe?.targetPortId,
    );
    if (!source || !target || !sourcePort || !targetPort) {
      throw new Error("The scan pipe must refer to existing cards and ports");
    }

    // One cell for each port's well and a gutter cell between them: the pipe
    // shows a short straight run.
    expect(target.col - (source.col + source.widthCells)).toBe(3);
    expect(source.row + sourcePort.rowOffset).toBe(
      target.row + targetPort.rowOffset,
    );
    const routed = routeCellGraph(graph, {
      exits: "side",
      underCards: "gaps",
      depth: true,
    }).pipes.get("scan-to-ocr");
    const rows = new Set(routed?.points.map((point) => point.y));
    expect(rows.size).toBe(1);
  });

  it("provides projection and conversion labels for the collection pipe", () => {
    const { graph } = createRealAnatomyShowcaseGraph();
    expect(
      graph.pipes.find((pipe) => pipe.id === "collection-to-summarize"),
    ).toMatchObject({
      projectionLabel: "tables.line_items",
      conversionLabel: "List → Table",
    });
  });

  it("routes every pipe", () => {
    const { graph } = createRealAnatomyShowcaseGraph();
    const result = routeCellGraph(graph, {
      exits: "side",
      underCards: "gaps",
      depth: true,
    });

    for (const { id } of graph.pipes) {
      expect(
        result.pipes.get(id)?.points.length ?? 0,
        id,
      ).toBeGreaterThanOrEqual(2);
    }
  });
});

it("points the benchmark group and its anchor at cards in the stress graph", () => {
  const { graph, groupCardIds, anchorCardId } =
    createStressGroupBenchmarkGraph();
  const cardIds = new Set(graph.cards.map((card) => card.id));

  expect(new Set(groupCardIds).size).toBe(6);
  expect(groupCardIds).toContain(anchorCardId);
  expect(groupCardIds.filter((id) => !cardIds.has(id))).toEqual([]);
  expect(cardIds.has(anchorCardId)).toBe(true);
});

it("drives the showcase authored document through normalized commands and merges live registry", () => {
  const state = createShowcaseAuthoredDocument(showcaseFallbackRegistry);
  const { graph, surfaceById } = cellGraphFromAuthoredDocument(
    state.document,
    showcaseFallbackRegistry,
    {
      presentation: state.presentation,
      nodeRunState: state.nodeRunState,
    },
  );

  expect(graph.cards.map((c) => c.id)).toEqual(
    expect.arrayContaining([
      "ocr-extract",
      "page-batch",
      "summarize",
      "ask-model",
      "reviewer-agent",
      "doc-scan",
      "frame-ingest",
      "note-hint",
    ]),
  );
  expect(surfaceById["ocr-extract"]).toMatchObject({
    kind: "operator",
    statusLabel: "240 ms",
    appendix: { title: "Extracted markdown" },
  });

  const moved = applyGraphCommandNormalized(state.document, {
    kind: "move_nodes",
    positions: [{ node_id: "summarize", x: 1300, y: 150 }],
  });
  const afterMove = cellGraphFromAuthoredDocument(
    moved,
    showcaseFallbackRegistry,
  );
  expect(afterMove.graph.cards.find((c) => c.id === "summarize")).toMatchObject(
    { col: 52, row: 6 },
  );

  const merged = mergeShowcaseRegistry({
    ...showcaseFallbackRegistry,
    nodes: [
      {
        ...showcaseFallbackRegistry.nodes[0]!,
        title: "Ask a Live Model",
      },
    ],
  });
  expect(
    merged.nodes.find(
      (n) => n.operator_id === "llm.openai_compatible.chat_completion",
    )?.title,
  ).toBe("Ask a Live Model");
});
