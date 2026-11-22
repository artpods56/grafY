import { describe, expect, it } from "vitest";

import {
  createDemoCellGraph,
  createStressCellGraph,
} from "../../../../tests/fixtures/cell-router-graphs";
import {
  CELL_PIPE_LANE_MIN,
  CELL_PIPE_MAX_DEPTH,
  CELL_PIPE_STUB_MIN,
  CELL_SIZE,
  portCell,
  portSide,
  portWorldCenter,
  trackPositionsInBand,
  worldToCell,
  type CellCardModel,
  type CellDir,
  type CellGraph,
  type CellPipeModel,
  type CellPort,
  type CellRoutingOptions,
  type CellRoutingResult,
  type WorldPoint,
} from "./cell-model";
import { routeCellGraph } from "./cell-router";

function port(
  id: string,
  direction: CellPort["direction"],
  rowOffset: number,
): CellPort {
  return {
    id,
    name: id,
    direction,
    rowOffset,
    artifactTypeId: "text.markdown",
    shape: "one",
  };
}

function card(
  id: string,
  col: number,
  row: number,
  widthCells: number,
  heightCells: number,
  ports: CellPort[] = [],
): CellCardModel {
  return {
    id,
    title: id,
    subtitle: "",
    col,
    row,
    widthCells,
    heightCells,
    ports,
  };
}

function pipe(id: string, source: string, target: string): CellPipeModel {
  const [sourceCardId = "", sourcePortId = ""] = source.split(".");
  const [targetCardId = "", targetPortId = ""] = target.split(".");
  return { id, sourceCardId, sourcePortId, targetCardId, targetPortId };
}

/** Ports in awkward places: facing, behind, stacked and boxed in. */
const AWKWARD: CellGraph = {
  cards: [
    // Ports on one row, facing each other across no gutter at all.
    card("a", 0, 0, 6, 3, [port("out", "output", 1)]),
    card("b", 8, 0, 6, 3, [port("in", "input", 1), port("in2", "input", 2)]),
    // Target behind the source on the same row.
    card("e", 40, 10, 6, 3, [port("out", "output", 1)]),
    card("f", 30, 10, 6, 3, [port("in", "input", 1)]),
    // Three stacked outputs feeding three stacked inputs.
    card("p", 10, 14, 6, 4, [
      port("o1", "output", 1),
      port("o2", "output", 2),
      port("o3", "output", 3),
    ]),
    card("s", 20, 20, 6, 4, [
      port("i1", "input", 1),
      port("i2", "input", 2),
      port("i3", "input", 3),
    ]),
    // A card boxed in by cards on every side.
    card("g", 60, 20, 6, 3, [port("in", "input", 1), port("out", "output", 1)]),
    card("box-top", 55, 16, 17, 4),
    card("box-bottom", 55, 23, 17, 4),
    card("box-left", 53, 20, 6, 3),
    card("box-right", 67, 20, 6, 3),
  ],
  pipes: [
    pipe("facing", "a.out", "b.in"),
    pipe("behind", "e.out", "f.in"),
    pipe("stack-1", "p.o1", "s.i1"),
    pipe("stack-2", "p.o2", "s.i2"),
    pipe("stack-3", "p.o3", "s.i3"),
    pipe("into-box", "e.out", "g.in"),
    pipe("out-of-box", "g.out", "b.in2"),
  ],
};

const GRAPHS: Record<string, CellGraph> = {
  demo: createDemoCellGraph(),
  stress: createStressCellGraph(),
  awkward: AWKWARD,
};

const OPTIONS: CellRoutingOptions[] = [
  { exits: "side", underCards: "gaps", depth: true },
  { exits: "free", underCards: "gaps", depth: true },
  { exits: "free", underCards: "free", depth: false },
  { exits: "side", underCards: "avoid", depth: true },
  { exits: "free", underCards: "avoid", depth: false },
];

const OPPOSITE: Record<CellDir, CellDir> = {
  left: "right",
  right: "left",
  top: "bottom",
  bottom: "top",
};

/** The way a step from `from` to `to` heads. */
function heading(from: WorldPoint, to: WorldPoint): CellDir {
  if (Math.abs(to.x - from.x) > Math.abs(to.y - from.y)) {
    return to.x > from.x ? "right" : "left";
  }
  return to.y > from.y ? "bottom" : "top";
}

function segments(points: readonly WorldPoint[]): [WorldPoint, WorldPoint][] {
  const pairs: [WorldPoint, WorldPoint][] = [];
  for (let index = 1; index < points.length; index += 1) {
    const before = points[index - 1];
    const after = points[index];
    if (before && after) pairs.push([before, after]);
  }
  return pairs;
}

function endpoints(graph: CellGraph, model: CellPipeModel) {
  const sourceCard = graph.cards.find((c) => c.id === model.sourceCardId);
  const targetCard = graph.cards.find((c) => c.id === model.targetCardId);
  const sourcePort = sourceCard?.ports.find((p) => p.id === model.sourcePortId);
  const targetPort = targetCard?.ports.find((p) => p.id === model.targetPortId);
  if (!sourceCard || !targetCard || !sourcePort || !targetPort) {
    throw new Error(`${model.id} has a missing end`);
  }
  return { sourceCard, targetCard, sourcePort, targetPort };
}

function snapshot(result: CellRoutingResult): string {
  return JSON.stringify({
    pipes: [...result.pipes],
    deepCount: result.deepCount,
    maxDepthUsed: result.maxDepthUsed,
  });
}

function portCellKeys(graph: CellGraph): Set<string> {
  const keys = new Set<string>();
  for (const c of graph.cards) {
    for (const p of c.ports) {
      const cell = portCell(c, p);
      keys.add(`${cell.col},${cell.row}`);
    }
  }
  return keys;
}

function routed(result: CellRoutingResult, id: string) {
  const pipeResult = result.pipes.get(id);
  if (!pipeResult) throw new Error(`${id} was not routed`);
  return pipeResult;
}

describe("cell model", () => {
  it("repeats the underground pipe contract constants", () => {
    // The shortest stub leaves a 25px port cell for the next cell's track,
    // at least TRACK_MARGIN (6) inside it: 12.5 + 6 = 18.5.
    expect(CELL_PIPE_STUB_MIN).toBe(18);
    expect(CELL_PIPE_LANE_MIN).toBe(10);
    expect(CELL_PIPE_MAX_DEPTH).toBe(2);
  });

  it("places tracks inside a one-cell band", () => {
    expect(trackPositionsInBand(7, 7, 0, 7)).toEqual([]);
    expect(trackPositionsInBand(7, 7, 1, 7)).toEqual([187.5]);
    expect(trackPositionsInBand(7, 7, 1, 2)).toEqual([187.5]);
    // Over its one-track capacity a 25px band squeezes its tracks between
    // its 6px margins rather than let them leave it.
    expect(trackPositionsInBand(7, 7, 2, 7)).toEqual([181, 194]);
    const squeezed = trackPositionsInBand(7, 7, 4, 7);
    expect(squeezed[0]).toBeCloseTo(181, 6);
    expect(squeezed.at(-1)).toBeCloseTo(194, 6);
  });

  it("places tracks 14 apart inside a wider band", () => {
    expect(trackPositionsInBand(6, 8, 3, 7)).toEqual([173.5, 187.5, 201.5]);
    expect(trackPositionsInBand(6, 7, 2, 6)).toEqual([156, 170]);
  });

  it("puts inputs left of a card and outputs right of it", () => {
    const c = card("c", 3, 2, 6, 4);
    expect(portCell(c, port("in", "input", 1))).toEqual({ col: 2, row: 3 });
    expect(portCell(c, port("out", "output", 2))).toEqual({ col: 9, row: 4 });
    expect(portWorldCenter(c, port("in", "input", 1))).toEqual({
      x: 62.5,
      y: 87.5,
    });
    expect(portWorldCenter(c, port("in", "input", 1), { x: 1, y: -2 })).toEqual(
      { x: 63.5, y: 85.5 },
    );
    expect(worldToCell(62.5, 87.5)).toEqual({ col: 2, row: 3 });
    expect(worldToCell(-1, -1)).toEqual({ col: -1, row: -1 });
  });

  it("builds the demo and stress graphs", () => {
    const demo = createDemoCellGraph();
    expect(demo.cards).toHaveLength(4);
    expect(demo.pipes).toHaveLength(4);
    const stress = createStressCellGraph();
    expect(stress.cards).toHaveLength(60);
    expect(stress.pipes).toHaveLength(144);
  });
});

describe.each(Object.entries(GRAPHS))("routing the %s graph", (_, graph) => {
  it.each(OPTIONS)("keeps the contract with %o", (options) => {
    const result = routeCellGraph(graph, options);
    expect([...result.pipes.keys()].sort()).toEqual(
      graph.pipes.map((model) => model.id).sort(),
    );
    let deep = 0;
    let deepest = 0;
    for (const model of graph.pipes) {
      const { sourceCard, targetCard, sourcePort, targetPort } = endpoints(
        graph,
        model,
      );
      const routedPipe = routed(result, model.id);
      const { points } = routedPipe;
      expect(points[0]).toEqual(portWorldCenter(sourceCard, sourcePort));
      expect(points.at(-1)).toEqual(portWorldCenter(targetCard, targetPort));

      const [first, second] = [points[0], points[1]];
      const [beforeLast, last] = [points.at(-2), points.at(-1)];
      if (!first || !second || !beforeLast || !last) {
        throw new Error(`${model.id} has fewer than two points`);
      }
      expect(heading(first, second)).toBe(routedPipe.sourceExit);
      expect(heading(last, beforeLast)).toBe(routedPipe.targetExit);
      if (options.exits === "side") {
        expect(routedPipe.sourceExit).toBe(portSide(sourcePort));
        expect(routedPipe.targetExit).toBe(portSide(targetPort));
      } else {
        expect(routedPipe.sourceExit).not.toBe(OPPOSITE[portSide(sourcePort)]);
        expect(routedPipe.targetExit).not.toBe(OPPOSITE[portSide(targetPort)]);
      }
      if (points.length > 2) {
        expect(
          Math.hypot(second.x - first.x, second.y - first.y),
          model.id,
        ).toBeGreaterThanOrEqual(CELL_PIPE_STUB_MIN - 1e-6);
        expect(
          Math.hypot(last.x - beforeLast.x, last.y - beforeLast.y),
          model.id,
        ).toBeGreaterThanOrEqual(CELL_PIPE_STUB_MIN - 1e-6);
      }
      for (const [from, to] of segments(points)) {
        const dx = Math.abs(to.x - from.x);
        const dy = Math.abs(to.y - from.y);
        expect(dx + dy, model.id).toBeGreaterThan(0.5);
        expect(dx < 1e-6 || dy < 1e-6, model.id).toBe(true);
      }
      expect(Number.isInteger(routedPipe.depth)).toBe(true);
      expect(routedPipe.depth).toBeGreaterThanOrEqual(0);
      expect(routedPipe.depth).toBeLessThanOrEqual(CELL_PIPE_MAX_DEPTH);
      if (!options.depth) expect(routedPipe.depth).toBe(0);
      if (routedPipe.depth > 0) deep += 1;
      deepest = Math.max(deepest, routedPipe.depth);
    }
    expect(result.deepCount).toBe(deep);
    expect(result.maxDepthUsed).toBe(deepest);
  });

  it.each(OPTIONS)("gives the same layout twice with %o", (options) => {
    expect(snapshot(routeCellGraph(graph, options))).toBe(
      snapshot(routeCellGraph(graph, options)),
    );
  });

  it.each(OPTIONS)(
    "never runs through another port's cell with %o",
    (options) => {
      const ports = portCellKeys(graph);
      const result = routeCellGraph(graph, options);
      for (const model of graph.pipes) {
        const { cellPath, points } = routed(result, model.id);
        for (const cell of cellPath.slice(1, -1)) {
          expect(ports.has(`${cell.col},${cell.row}`), model.id).toBe(false);
        }
        // The drawn vertical runs keep out of port cells too, own ends aside.
        const own = new Set(
          [cellPath[0], cellPath.at(-1)].map(
            (cell) => `${cell?.col},${cell?.row}`,
          ),
        );
        for (const [from, to] of segments(points)) {
          if (Math.abs(from.x - to.x) > 1e-6) continue;
          const col = worldToCell(from.x, 0).col;
          const top = worldToCell(0, Math.min(from.y, to.y)).row;
          const bottom = worldToCell(0, Math.max(from.y, to.y)).row;
          for (let row = top; row <= bottom; row += 1) {
            const key = `${col},${row}`;
            if (own.has(key)) continue;
            expect(ports.has(key), `${model.id} at ${key}`).toBe(false);
          }
        }
      }
    },
  );
});

describe("gutter capacity", () => {
  const options: CellRoutingOptions = {
    exits: "side",
    underCards: "avoid",
    depth: true,
  };

  /**
   * Columns 7–9 are a three-cell gutter, one track a cell, between two tall
   * walls: three stacked outputs drop down it to a card below and right.
   */
  function verticalGutter(withPassThrough: boolean): CellGraph {
    const cards = [
      card("source", 0, 0, 6, 4, [
        port("o1", "output", 1),
        port("o2", "output", 2),
        port("o3", "output", 3),
      ]),
      card("far", 0, -6, 6, 4, [port("o", "output", 1)]),
      card("wall-left", 1, 5, 6, 10),
      card("wall-right", 10, -8, 6, 23),
      card("target", 20, 17, 6, 4, [
        port("i0", "input", 0),
        port("i1", "input", 1),
        port("i2", "input", 2),
        port("i3", "input", 3),
      ]),
    ];
    const pipes = [
      pipe("s1", "source.o1", "target.i0"),
      pipe("s2", "source.o2", "target.i1"),
      pipe("s3", "source.o3", "target.i2"),
    ];
    if (withPassThrough) pipes.push(pipe("pass", "far.o", "target.i3"));
    return { cards, pipes };
  }

  /** One track a cell, 14px apart, round the gutter's middle cell. */
  const GUTTER_TRACKS = [216, 230, 244];

  /** The x of the pipe's run down the gutter in columns 7–9. */
  function gutterX(result: CellRoutingResult, id: string): number {
    const { points } = routed(result, id);
    const run = segments(points).find(
      ([from, to]) =>
        Math.abs(from.x - to.x) < 1e-6 && Math.abs(from.y - to.y) > 250,
    );
    if (!run) throw new Error(`${id} has no run down the gutter`);
    return run[0].x;
  }

  it("fits three pipes on three tracks of a three-cell gutter", () => {
    const result = routeCellGraph(verticalGutter(false), options);
    for (const id of ["s1", "s2", "s3"]) {
      expect(routed(result, id).depth, id).toBe(0);
    }
    const xs = ["s1", "s2", "s3"].map((id) => gutterX(result, id));
    expect([...xs].sort((a, b) => a - b)).toEqual(GUTTER_TRACKS);
    expect(result.deepCount).toBe(0);
  });

  it("sinks only the pass-through pipe when a fourth one joins", () => {
    const result = routeCellGraph(verticalGutter(true), options);
    for (const id of ["s1", "s2", "s3"]) {
      expect(routed(result, id).depth, id).toBe(0);
    }
    expect(routed(result, "pass").depth).toBe(1);
    expect(result.deepCount).toBe(1);
    const xs = ["s1", "s2", "s3"].map((id) => gutterX(result, id));
    expect([...xs].sort((a, b) => a - b)).toEqual(GUTTER_TRACKS);
  });

  it("squeezes four pipes into the gutter without depth", () => {
    const result = routeCellGraph(verticalGutter(true), {
      ...options,
      depth: false,
    });
    const xs = ["s1", "s2", "s3", "pass"].map((id) => gutterX(result, id));
    expect(new Set(xs).size).toBe(4);
    for (const x of xs) {
      expect(x).toBeGreaterThanOrEqual(7 * CELL_SIZE + 6 - 1e-6);
      expect(x).toBeLessThanOrEqual(10 * CELL_SIZE - 6 + 1e-6);
    }
  });

  /**
   * Rows 6–11 are a six-cell gutter between two wide walls: six stacked
   * outputs cross it to six stacked inputs. Seven-cell gutters either side
   * carry the six pipes down to it and up again.
   */
  function horizontalGutter(withPassThrough: boolean): CellGraph {
    const outputs = [0, 1, 2, 3, 4, 5].map((n) => port(`o${n}`, "output", n));
    const inputs = [0, 1, 2, 3, 4, 5].map((n) => port(`i${n}`, "input", n));
    const cards = [
      card("source", 0, 0, 6, 6, outputs),
      card("wall-top", 14, -10, 20, 16),
      card("wall-bottom", 14, 12, 20, 13),
      card("target", 42, 0, 6, 6, inputs),
      card("far", -10, 12, 6, 4, [port("o", "output", 2)]),
      card("far-target", 52, 3, 6, 4, [port("i", "input", 1)]),
    ];
    const pipes = [0, 1, 2, 3, 4, 5].map((n) =>
      pipe(`s${n}`, `source.o${n}`, `target.i${n}`),
    );
    if (withPassThrough) pipes.push(pipe("pass", "far.o", "far-target.i"));
    return { cards, pipes };
  }

  /** The y of the pipe's run between the walls. */
  function gutterY(result: CellRoutingResult, id: string): number {
    const { points } = routed(result, id);
    const run = segments(points).find(
      ([from, to]) =>
        Math.abs(from.y - to.y) < 1e-6 &&
        Math.min(from.x, to.x) < 14 * CELL_SIZE &&
        Math.max(from.x, to.x) > 34 * CELL_SIZE,
    );
    if (!run) throw new Error(`${id} has no run between the walls`);
    return run[0].y;
  }

  const SIX = ["s0", "s1", "s2", "s3", "s4", "s5"];

  it("fits six pipes on six tracks of a six-cell gutter", () => {
    const result = routeCellGraph(horizontalGutter(false), options);
    for (const id of SIX) expect(routed(result, id).depth, id).toBe(0);
    const ys = SIX.map((id) => gutterY(result, id));
    expect(new Set(ys).size).toBe(6);
    for (const y of ys) {
      expect(y).toBeGreaterThanOrEqual(6 * CELL_SIZE + 6);
      expect(y).toBeLessThanOrEqual(12 * CELL_SIZE - 6);
    }
    const sorted = [...ys].sort((a, b) => a - b);
    for (let index = 1; index < sorted.length; index += 1) {
      expect((sorted[index] ?? 0) - (sorted[index - 1] ?? 0)).toBeCloseTo(
        14,
        6,
      );
    }
  });

  it("sinks only the pass-through pipe when a seventh one joins", () => {
    const result = routeCellGraph(horizontalGutter(true), options);
    for (const id of SIX) expect(routed(result, id).depth, id).toBe(0);
    expect(routed(result, "pass").depth).toBe(1);
    expect(result.deepCount).toBe(1);
    expect(result.maxDepthUsed).toBe(1);
  });
});

describe("under cards", () => {
  const ends = [
    card("from", 0, 0, 6, 3, [port("out", "output", 1)]),
    card("to", 30, 0, 6, 3, [port("in", "input", 1)]),
  ];
  const pipes = [pipe("p", "from.out", "to.in")];
  const small = card("small", 12, -1, 3, 5);
  const wall = card("wall", 12, -20, 6, 41);

  function crosses(result: CellRoutingResult, blocker: CellCardModel): boolean {
    return routed(result, "p").cellPath.some(
      (cell) =>
        cell.col >= blocker.col &&
        cell.col < blocker.col + blocker.widthCells &&
        cell.row >= blocker.row &&
        cell.row < blocker.row + blocker.heightCells,
    );
  }

  function route(
    blocker: CellCardModel,
    underCards: "free" | "gaps" | "avoid",
  ) {
    return routeCellGraph(
      { cards: [...ends, blocker], pipes },
      { exits: "side", underCards, depth: true },
    );
  }

  it("runs straight under any card when free", () => {
    for (const blocker of [small, wall]) {
      const result = route(blocker, "free");
      expect(routed(result, "p").points).toHaveLength(2);
      expect(crosses(result, blocker)).toBe(true);
    }
  });

  it("goes round a small card but under a wide wall in gaps", () => {
    const aroundSmall = route(small, "gaps");
    expect(routed(aroundSmall, "p").points.length).toBeGreaterThan(2);
    expect(crosses(aroundSmall, small)).toBe(false);
    const underWall = route(wall, "gaps");
    expect(routed(underWall, "p").points).toHaveLength(2);
    expect(crosses(underWall, wall)).toBe(true);
  });

  it("goes round even a wide wall when avoiding cards", () => {
    const result = route(wall, "avoid");
    expect(routed(result, "p").points.length).toBeGreaterThan(2);
    expect(crosses(result, wall)).toBe(false);
  });
});

describe("dragging", () => {
  const stress = createStressCellGraph();
  const options: CellRoutingOptions = {
    exits: "side",
    underCards: "gaps",
    depth: true,
  };

  it("routes only the given pipes, around every card", () => {
    const only = new Set(
      stress.pipes
        .filter(
          (p) =>
            p.sourceCardId === "stress-2-4" || p.targetCardId === "stress-2-4",
        )
        .map((p) => p.id),
    );
    const result = routeCellGraph(stress, options, only);
    expect([...result.pipes.keys()].sort()).toEqual([...only].sort());
    const full = routeCellGraph(stress, options);
    for (const id of only) {
      expect(routed(result, id).cellPath).toEqual(routed(full, id).cellPath);
    }
  });
});

describe("speed", () => {
  const stress = createStressCellGraph();
  const options: CellRoutingOptions = {
    exits: "side",
    underCards: "gaps",
    depth: true,
  };

  function fastest(run: () => void, times = 3): number {
    run();
    let best = Infinity;
    for (let index = 0; index < times; index += 1) {
      const start = performance.now();
      run();
      best = Math.min(best, performance.now() - start);
    }
    return best;
  }

  it("routes the 60-card stress graph in under 150ms", () => {
    expect(fastest(() => routeCellGraph(stress, options))).toBeLessThan(150);
  });

  it("routes one dragged card's pipes in under 10ms", () => {
    const only = new Set(
      stress.pipes
        .filter(
          (p) =>
            p.sourceCardId === "stress-2-4" || p.targetCardId === "stress-2-4",
        )
        .map((p) => p.id),
    );
    expect(only.size).toBeGreaterThan(0);
    expect(fastest(() => routeCellGraph(stress, options, only))).toBeLessThan(
      10,
    );
  });
});

describe("ports that share an id across directions", () => {
  it("routes each pipe end from the port on its own side of the card", () => {
    // An operator that takes an `image` and gives one back.
    const editor = card("editor", 10, 0, 6, 4, [
      port("image", "input", 1),
      port("image", "output", 2),
    ]);
    const graph: CellGraph = {
      cards: [
        card("source", 0, 0, 6, 4, [port("out", "output", 1)]),
        editor,
        card("sink", 22, 0, 6, 4, [port("in", "input", 2)]),
      ],
      pipes: [
        pipe("into", "source.out", "editor.image"),
        pipe("outof", "editor.image", "sink.in"),
      ],
    };
    const result = routeCellGraph(graph, {
      exits: "side",
      underCards: "gaps",
      depth: true,
    });
    const into = result.pipes.get("into");
    const outof = result.pipes.get("outof");
    expect(into && outof).toBeTruthy();
    const input = editor.ports[0]!;
    const output = editor.ports[1]!;
    expect(into!.points.at(-1)).toEqual(portWorldCenter(editor, input));
    expect(outof!.points[0]).toEqual(portWorldCenter(editor, output));
    // The two ends sit on opposite sides of the card.
    expect(portCell(editor, input).col).toBeLessThan(editor.col);
    expect(portCell(editor, output).col).toBe(editor.col + editor.widthCells);
  });
});
