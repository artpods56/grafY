import { Position } from "@xyflow/react";
import { describe, expect, it } from "vitest";

import {
  applyHandleFanOffset,
  edgeFanOffsets,
  edgeFanOffsetsById,
  fanSortAxis,
  routedBezierPath,
} from "./edge-path";

describe("edgeFanOffsets", () => {
  const edges = [
    {
      id: "to-high",
      source: "n1",
      target: "high",
      sourceHandle: "out",
      targetHandle: "in",
    },
    {
      id: "to-low",
      source: "n1",
      target: "low",
      sourceHandle: "out",
      targetHandle: "in-b",
    },
  ];

  it("spreads sibling edges by far-end position, not id", () => {
    const sourceOrderPoints = new Map([
      ["to-high", { x: 300, y: 10 }],
      ["to-low", { x: 300, y: 200 }],
    ]);

    expect(
      edgeFanOffsets(edges, "to-high", { sourceOrderPoints, sourceAxis: "y" }),
    ).toEqual({ source: -3.5, target: 0 });
    expect(
      edgeFanOffsets(edges, "to-low", { sourceOrderPoints, sourceAxis: "y" }),
    ).toEqual({ source: 3.5, target: 0 });
  });

  it("reorders when the far-end positions swap", () => {
    const before = new Map([
      ["to-high", { x: 300, y: 10 }],
      ["to-low", { x: 300, y: 200 }],
    ]);
    const after = new Map([
      ["to-high", { x: 300, y: 220 }],
      ["to-low", { x: 300, y: 40 }],
    ]);

    expect(
      edgeFanOffsets(edges, "to-high", {
        sourceOrderPoints: before,
        sourceAxis: "y",
      }).source,
    ).toBe(-3.5);
    expect(
      edgeFanOffsets(edges, "to-high", {
        sourceOrderPoints: after,
        sourceAxis: "y",
      }).source,
    ).toBe(3.5);
  });

  it("spreads sibling edges that share a target handle by source position", () => {
    const incoming = [
      {
        id: "a",
        source: "n1",
        target: "n3",
        sourceHandle: "out-a",
        targetHandle: "in",
      },
      {
        id: "b",
        source: "n2",
        target: "n3",
        sourceHandle: "out-b",
        targetHandle: "in",
      },
      {
        id: "c",
        source: "n4",
        target: "n3",
        sourceHandle: "out-c",
        targetHandle: "in",
      },
    ];
    const targetOrderPoints = new Map([
      ["a", { x: 0, y: 0 }],
      ["b", { x: 0, y: 50 }],
      ["c", { x: 0, y: 100 }],
    ]);

    expect(
      edgeFanOffsets(incoming, "a", { targetOrderPoints, targetAxis: "y" })
        .target,
    ).toBe(-7);
    expect(
      edgeFanOffsets(incoming, "b", { targetOrderPoints, targetAxis: "y" })
        .target,
    ).toBe(0);
    expect(
      edgeFanOffsets(incoming, "c", { targetOrderPoints, targetAxis: "y" })
        .target,
    ).toBe(7);
  });

  it("computes source and target fan groups together", () => {
    const graphEdges = [
      {
        id: "a",
        source: "s1",
        target: "t1",
        sourceHandle: "out",
        targetHandle: "in-a",
      },
      {
        id: "b",
        source: "s1",
        target: "t2",
        sourceHandle: "out",
        targetHandle: "in",
      },
      {
        id: "c",
        source: "s2",
        target: "t2",
        sourceHandle: "out-c",
        targetHandle: "in",
      },
    ];

    const offsets = edgeFanOffsetsById(graphEdges, {
      sourceOrderPoints: new Map([
        ["a", { x: 300, y: 0 }],
        ["b", { x: 300, y: 100 }],
        ["c", { x: 300, y: 100 }],
      ]),
      targetOrderPoints: new Map([
        ["a", { x: 0, y: 0 }],
        ["b", { x: 0, y: 0 }],
        ["c", { x: 0, y: 100 }],
      ]),
      sourceAxis: "y",
      targetAxis: "y",
    });

    expect(offsets.get("a")).toEqual({ source: -3.5, target: 0 });
    expect(offsets.get("b")).toEqual({ source: 3.5, target: -3.5 });
    expect(offsets.get("c")).toEqual({ source: 0, target: 3.5 });
  });
});

describe("fanSortAxis", () => {
  it("picks the axis perpendicular to the handle exit", () => {
    expect(fanSortAxis(Position.Right)).toBe("y");
    expect(fanSortAxis(Position.Left)).toBe("y");
    expect(fanSortAxis(Position.Top)).toBe("x");
    expect(fanSortAxis(Position.Bottom)).toBe("x");
  });
});

describe("applyHandleFanOffset", () => {
  it("offsets along the axis perpendicular to the handle exit", () => {
    expect(applyHandleFanOffset({ x: 10, y: 20 }, Position.Right, 4)).toEqual({
      x: 10,
      y: 24,
    });
    expect(applyHandleFanOffset({ x: 10, y: 20 }, Position.Top, -3)).toEqual({
      x: 7,
      y: 20,
    });
  });
});

describe("routedBezierPath", () => {
  it("keeps the bend anchor near the midpoint of the curved span", () => {
    const { anchor, path } = routedBezierPath({
      source: { x: 0, y: 0 },
      target: { x: 200, y: 0 },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
      routeOffset: { x: 10, y: -20 },
    });

    expect(path.startsWith("M0,0 C")).toBe(true);
    expect(anchor.x).toBeCloseTo(110, 0);
    expect(anchor.y).toBeCloseTo(-20, 0);
  });
});
