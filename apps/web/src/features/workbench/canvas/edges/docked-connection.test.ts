import { Position } from "@xyflow/react";
import { describe, expect, it } from "vitest";

import { ARTIFACT_VIEWER_INTERACTION_EDGE_TYPE } from "../artifact-viewer";
import {
  connectionIsDocked,
  dockedBridgeLayout,
  dockedConnections,
  dockedHandleKey,
  type DockedGraphNode,
} from "./docked-connection";

const cellSize = 50;
const dockableTypes = new Set(["workflow", "viewer"]);

function dockedInput(
  overrides: Partial<Parameters<typeof connectionIsDocked>[0]> = {},
) {
  return connectionIsDocked({
    source: { x: 294, y: 80 },
    target: { x: 306, y: 80 },
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
    cellSize,
    sourceDegree: 1,
    targetDegree: 1,
    ...overrides,
  });
}

function nodeWithHandle(
  origin: { x: number; y: number },
  handle: {
    id: string;
    type: "source" | "target";
    x: number;
    y: number;
    position: Position;
  },
): DockedGraphNode {
  return {
    internals: {
      positionAbsolute: origin,
      handleBounds: {
        [handle.type]: [
          {
            id: handle.id,
            x: handle.x,
            y: handle.y,
            width: 30,
            height: 30,
            position: handle.position,
          },
        ],
      },
    },
  };
}

describe("connectionIsDocked", () => {
  it("docks a 1:1 right-to-left pair in the lattice gutter", () => {
    expect(dockedInput()).toBe(true);
  });

  it("docks when facing handles overlap in the gutter", () => {
    expect(
      dockedInput({
        source: { x: 300, y: 80 },
        target: { x: 300, y: 80 },
      }),
    ).toBe(true);
  });

  it("does not dock across an empty lattice cell", () => {
    expect(
      dockedInput({
        target: { x: 294 + 50, y: 80 },
      }),
    ).toBe(false);
  });

  it("does not dock when the handles are on different rows", () => {
    expect(dockedInput({ target: { x: 306, y: 130 } })).toBe(false);
  });

  it("does not dock a wrapping leftward path", () => {
    expect(
      dockedInput({
        source: { x: 400, y: 80 },
        target: { x: 100, y: 80 },
      }),
    ).toBe(false);
  });

  it("does not dock fans or reverse handle directions", () => {
    expect(dockedInput({ sourceDegree: 2 })).toBe(false);
    expect(dockedInput({ targetDegree: 2 })).toBe(false);
    expect(dockedInput({ sourcePosition: Position.Left })).toBe(false);
    expect(dockedInput({ targetPosition: Position.Right })).toBe(false);
  });
});

describe("dockedBridgeLayout", () => {
  it("centers a 3-cell pill on the facing handles", () => {
    expect(
      dockedBridgeLayout({ x: 294, y: 80 }, { x: 306, y: 80 }, cellSize),
    ).toEqual({
      anchor: { x: 300, y: 80 },
      width: 150,
      height: 24,
    });
  });
});

describe("dockedConnections", () => {
  const sourceHandle = "out::scalar.text::1::one::output";
  const targetHandle = "in::scalar.text::1::one::input";

  it("marks both facing handles when a dockable edge joins adjacent cards", () => {
    const nodes = new Map<string, DockedGraphNode>([
      [
        "left",
        nodeWithHandle(
          { x: 0, y: 0 },
          {
            id: sourceHandle,
            type: "source",
            x: 279,
            y: 65,
            position: Position.Right,
          },
        ),
      ],
      [
        "right",
        nodeWithHandle(
          { x: 300, y: 0 },
          {
            id: targetHandle,
            type: "target",
            x: -9,
            y: 65,
            position: Position.Left,
          },
        ),
      ],
    ]);

    const docked = dockedConnections(
      [
        {
          id: "join",
          type: "workflow",
          source: "left",
          target: "right",
          sourceHandle,
          targetHandle,
        },
      ],
      nodes,
      cellSize,
      dockableTypes,
    );

    expect([...docked.edgeIds]).toEqual(["join"]);
    expect(docked.handleKeys).toEqual(
      new Set([
        dockedHandleKey("left", sourceHandle),
        dockedHandleKey("right", targetHandle),
      ]),
    );
  });

  it("ignores instance plugs, fans, and non-dockable edge types", () => {
    const plugHandle = "items::scalar.text::1::one::input::plug-1";
    const nodes = new Map<string, DockedGraphNode>([
      [
        "left",
        nodeWithHandle(
          { x: 0, y: 0 },
          {
            id: sourceHandle,
            type: "source",
            x: 279,
            y: 65,
            position: Position.Right,
          },
        ),
      ],
      [
        "right",
        nodeWithHandle(
          { x: 300, y: 0 },
          {
            id: plugHandle,
            type: "target",
            x: -9,
            y: 65,
            position: Position.Left,
          },
        ),
      ],
    ]);

    const docked = dockedConnections(
      [
        {
          id: "plug",
          type: "workflow",
          source: "left",
          target: "right",
          sourceHandle,
          targetHandle: plugHandle,
        },
        {
          id: "interaction",
          type: "interaction",
          source: "left",
          target: "right",
          sourceHandle,
          targetHandle,
        },
      ],
      nodes,
      cellSize,
      dockableTypes,
    );

    expect(docked.edgeIds.size).toBe(0);
    expect(docked.handleKeys.size).toBe(0);
  });

  it("docks viewer follow edges when that type is allowed", () => {
    const nodes = new Map<string, DockedGraphNode>([
      [
        "left",
        nodeWithHandle(
          { x: 0, y: 0 },
          {
            id: sourceHandle,
            type: "source",
            x: 279,
            y: 65,
            position: Position.Right,
          },
        ),
      ],
      [
        "right",
        nodeWithHandle(
          { x: 300, y: 0 },
          {
            id: targetHandle,
            type: "target",
            x: -9,
            y: 65,
            position: Position.Left,
          },
        ),
      ],
    ]);

    const docked = dockedConnections(
      [
        {
          id: "follow",
          type: ARTIFACT_VIEWER_INTERACTION_EDGE_TYPE,
          source: "left",
          target: "right",
          sourceHandle,
          targetHandle,
        },
      ],
      nodes,
      cellSize,
      new Set([ARTIFACT_VIEWER_INTERACTION_EDGE_TYPE]),
    );

    expect([...docked.edgeIds]).toEqual(["follow"]);
  });
});
