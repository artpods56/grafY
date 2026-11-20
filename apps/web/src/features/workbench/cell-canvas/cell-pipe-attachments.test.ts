import { describe, expect, it } from "vitest";
import { detectCellDockedJoins } from "./cell-docking";
import {
  ATTACHMENT_HEIGHT_PX,
  ATTACHMENT_WIDTH_PX,
  solvePipeAttachmentAnchors,
} from "./cell-pipe-attachments";
import {
  cardWorldRect,
  portWorldCenter,
  type CellCardModel,
  type CellPipeModel,
  type CellPort,
  type RoutedCellPipe,
  type WorldPoint,
} from "./cell-model";
import { routeCellGraph } from "./cell-router";

const output: CellPort = {
  id: "out",
  name: "Result",
  direction: "output",
  artifactTypeId: "result",
  rowOffset: 1,
  shape: "one",
};
const input: CellPort = { ...output, id: "in", direction: "input" };
const source: CellCardModel = {
  id: "source",
  title: "Source",
  subtitle: "",
  col: 0,
  row: 0,
  widthCells: 2,
  heightCells: 3,
  ports: [output],
};
const target: CellCardModel = {
  ...source,
  id: "target",
  col: 14,
  ports: [input],
};
const obstacle: CellCardModel = {
  ...source,
  id: "obstacle",
  col: 7,
  ports: [],
};
const pipe: CellPipeModel = {
  id: "pipe",
  sourceCardId: source.id,
  sourcePortId: output.id,
  targetCardId: target.id,
  targetPortId: input.id,
  projectionLabel: "field.name",
};
const resolveColor = (type: string) => `color:${type}`;
const baseParams = {
  cards: [source, target],
  dockedJoins: [],
  resolveColor,
};

function routed(id: string, points: WorldPoint[]): RoutedCellPipe {
  return {
    id,
    points,
    cellPath: [],
    sourceExit: "right",
    targetExit: "left",
    depth: 0,
  };
}

describe("solvePipeAttachmentAnchors", () => {
  it("shows labeled pipes by default and includes blank pills on request", () => {
    const unlabeled = { ...pipe, id: "unlabeled", projectionLabel: null };
    const conversion = {
      ...pipe,
      id: "converted",
      projectionLabel: "",
      conversionLabel: "2 conv",
    };
    const points = [
      portWorldCenter(source, output),
      portWorldCenter(target, input),
    ];
    const params = {
      ...baseParams,
      pipes: [unlabeled, conversion],
      routedPipes: new Map([
        [unlabeled.id, routed(unlabeled.id, points)],
        [conversion.id, routed(conversion.id, points)],
      ]),
    };

    expect(solvePipeAttachmentAnchors(params)).toEqual([
      {
        pipeId: "converted",
        anchor: { x: 400, y: 75 },
        segmentOrientation: "horizontal",
        widthCells: 3,
        heightCells: 1,
        label: "2 conv",
        conversionLabel: "2 conv",
        color: "color:result",
        enabled: true,
        isDocked: false,
      },
    ]);
    expect(
      solvePipeAttachmentAnchors({ ...params, includeAll: true }).map(
        ({ pipeId, label }) => [pipeId, label],
      ),
    ).toEqual([
      ["converted", "2 conv"],
      ["unlabeled", ""],
    ]);
  });

  it("anchors a docked pill on the seam and preserves its join color", () => {
    const graph = {
      cards: [source, { ...target, col: 2 }],
      pipes: [{ ...pipe, conversionLabel: "1 conv", enabled: false }],
    };
    const { dockedJoins } = detectCellDockedJoins(graph, () => "seam-color");

    expect(
      solvePipeAttachmentAnchors({
        ...graph,
        routedPipes: new Map(),
        dockedJoins,
        resolveColor,
      }),
    ).toEqual([
      {
        pipeId: "pipe",
        anchor: { x: 100, y: 75 },
        segmentOrientation: "horizontal",
        widthCells: 3,
        heightCells: 1,
        label: "field.name",
        conversionLabel: "1 conv",
        color: "seam-color",
        enabled: false,
        isDocked: true,
      },
    ]);
  });

  it("places the pill clear of cards and endpoint wells on a real routed graph", () => {
    const graph = { cards: [source, obstacle, target], pipes: [pipe] };
    const { pipes: routedPipes } = routeCellGraph(graph, {
      exits: "side",
      underCards: "avoid",
      depth: false,
    });

    const attachments = solvePipeAttachmentAnchors({
      ...baseParams,
      ...graph,
      routedPipes,
    });
    expect(attachments).toHaveLength(1);
    const [attachment] = attachments;
    if (!attachment) throw new Error("Expected a routed pill");
    expect(attachment.segmentOrientation).toBe("horizontal");

    const { x, y } = attachment.anchor;
    const halfWidth = ATTACHMENT_WIDTH_PX / 2;
    const halfHeight = ATTACHMENT_HEIGHT_PX / 2;
    for (const card of graph.cards) {
      const rect = cardWorldRect(card);
      expect(
        x + halfWidth <= rect.x ||
          x - halfWidth >= rect.x + rect.width ||
          y + halfHeight <= rect.y ||
          y - halfHeight >= rect.y + rect.height,
      ).toBe(true);
    }
    for (const port of [
      portWorldCenter(source, output),
      portWorldCenter(target, input),
    ]) {
      const dx = Math.max(0, Math.abs(x - port.x) - halfWidth);
      const dy = Math.max(0, Math.abs(y - port.y) - halfHeight);
      expect(Math.hypot(dx, dy)).toBeGreaterThanOrEqual(37.5);
    }
  });

  it("uses a clear quarter point when a long segment's midpoint is covered", () => {
    const route = routed(pipe.id, [
      portWorldCenter(source, output),
      portWorldCenter(target, input),
    ]);

    expect(
      solvePipeAttachmentAnchors({
        ...baseParams,
        cards: [source, obstacle, target],
        pipes: [pipe],
        routedPipes: new Map([[pipe.id, route]]),
      }),
    ).toMatchObject([
      { anchor: { x: 262.5, y: 75 }, segmentOrientation: "horizontal" },
    ]);
  });

  it("keeps a vertical fallback and skips routes without a nonzero segment", () => {
    const start = { x: 125, y: 75 };
    const end = { x: 125, y: 125 };
    const collapsed = { ...pipe, id: "collapsed" };

    expect(
      solvePipeAttachmentAnchors({
        ...baseParams,
        pipes: [collapsed, pipe],
        routedPipes: new Map([
          [collapsed.id, routed(collapsed.id, [start, start])],
          [pipe.id, routed(pipe.id, [start, start, end])],
        ]),
      }),
    ).toMatchObject([
      {
        pipeId: "pipe",
        anchor: { x: 125, y: 100 },
        segmentOrientation: "vertical",
      },
    ]);
  });

  it("separates parallel pills by pipe ID regardless of input order", () => {
    const first = { ...pipe, id: "a" };
    const second = { ...pipe, id: "b" };
    const routedPipes = new Map([
      [
        first.id,
        routed(first.id, [
          { x: 125, y: 75 },
          { x: 675, y: 75 },
        ]),
      ],
      [
        second.id,
        routed(second.id, [
          { x: 125, y: 89 },
          { x: 675, y: 89 },
        ]),
      ],
    ]);
    const expected = [
      { pipeId: "a", anchor: { x: 400, y: 75 } },
      { pipeId: "b", anchor: { x: 400, y: 139 } },
    ];

    for (const pipes of [
      [first, second],
      [second, first],
    ]) {
      expect(
        solvePipeAttachmentAnchors({ ...baseParams, pipes, routedPipes }),
      ).toMatchObject(expected);
    }
  });
});
