import { describe, expect, it } from "vitest";

import type {
  ArtifactTypeSpec,
  NodeRegistry,
  NodeSpec,
  Port,
  SavedGraphAgent,
} from "@/lib/api";

import type {
  ArtifactViewerCanvasState,
  ArtifactViewerEdge,
  ArtifactViewerNode,
} from "../artifacts/artifact-viewer";
import { presentationFromArtifactViewers } from "../artifacts/artifact-viewer";
import type { AnnotationNode } from "../authoring/annotations";
import {
  applyGraphCommandNormalized,
  createGraphDraft,
  type AuthoredGraphDocument,
  type AuthoredGraphEdge,
  type AuthoredGraphNode,
  type AuthoredGraphOrigin,
  type GraphCommand,
} from "../authoring/graph-document";

import { findArtifactMergeSuggestions } from "./cell-artifact-stacking";
import { cellGraphFromAuthoredDocument } from "./cell-document-adapter";
import {
  buildCleanupUndoPlan,
  mergeCleanupUndoSnapshots,
  planCellGraphCleanup,
} from "./cell-graph-cleanup";
import { CELL_SIZE, type CellCardModel } from "./cell-model";
import { routeCellGraph } from "./cell-router";

// --- The catalog ------------------------------------------------------------

const PNG = { id: "image.png", schema_version: 1 };
const MD = { id: "text.markdown", schema_version: 1 };
const TABLE = { id: "table.data", schema_version: 1 };
const TIFF = { id: "file.tiff", schema_version: 1 };
const REGIONS = { id: "ocr.tiff_text_regions", schema_version: 1 };
const SCALAR_INT = { id: "scalar.integer", schema_version: 1 };
const MAP = { id: "geo.map_layer", schema_version: 1 };

function catalogEntry(
  key: { id: string; schema_version: number },
  preview: ArtifactTypeSpec["preview_kind"],
): ArtifactTypeSpec {
  return {
    key,
    title: key.id,
    preview_kind: preview,
    bundle: { format: "inline-json", version: 1 },
    field_projections: [],
    payload_schema: {},
  };
}

function port(name: string, overrides: Partial<Port> = {}): Port {
  return {
    name,
    title: name,
    kind: "artifact",
    direction: "input",
    artifact_type: MD,
    accepted_shapes: ["one"],
    shape: "one",
    instance_plugs: false,
    required: false,
    ...overrides,
  } as Port;
}

function servicePort(name: string, overrides: Partial<Port> = {}): Port {
  return port(name, {
    kind: "service",
    artifact_type: null,
    service_contracts: [{ id: "engine.contract", version: 1 }],
    ...overrides,
  });
}

function nodeSpec(
  operatorId: string,
  inputs: Port[],
  outputs: Port[],
  overrides: Partial<NodeSpec> = {},
): NodeSpec {
  return {
    operator_id: operatorId,
    operator_version: 1,
    title: operatorId,
    description: "",
    role: "operator",
    origin: "builtin",
    runnable: true,
    catalog_visible: true,
    plugin_slug: "test",
    pack_slugs: [],
    input_schema: {},
    output_schema: {},
    config_schema: {},
    inputs,
    outputs,
    ...overrides,
  };
}

const registry: NodeRegistry = {
  packs: [],
  plugins: [],
  artifact_conversions: [],
  artifact_types: [
    catalogEntry(PNG, "image"),
    catalogEntry(MD, "markdown"),
    catalogEntry(TABLE, "table"),
    catalogEntry(TIFF, "tiff"),
    catalogEntry(REGIONS, "tiff-text"),
    catalogEntry(SCALAR_INT, "text"),
    catalogEntry(MAP, "map"),
  ],
  nodes: [
    // Reads a document picture through a service and hands back markdown.
    nodeSpec(
      "test.document_ocr",
      [port("document", { artifact_type: PNG }), servicePort("engine")],
      [port("markdown", { direction: "output", artifact_type: MD })],
    ),
    // A provider: it stores nothing, so every output is a service.
    nodeSpec(
      "test.mistral_provider",
      [],
      [servicePort("engine", { direction: "output" })],
      { role: "provider" },
    ),
    nodeSpec(
      "test.extract_table",
      [port("markdown", { artifact_type: MD })],
      [port("table", { direction: "output", artifact_type: TABLE })],
    ),
    nodeSpec(
      "test.recognize",
      [port("regions", { artifact_type: REGIONS }), servicePort("engine")],
      [port("text", { direction: "output", artifact_type: MD })],
    ),
    nodeSpec(
      "test.transliterate",
      [port("regions", { artifact_type: REGIONS }), servicePort("engine")],
      [port("text_out", { direction: "output", artifact_type: MD })],
    ),
    nodeSpec(
      "test.read_png",
      [],
      [port("png", { direction: "output", artifact_type: PNG })],
    ),
    nodeSpec(
      "test.counter",
      [],
      [port("count", { direction: "output", artifact_type: SCALAR_INT })],
    ),
  ],
  service_contracts: [{ id: "engine.contract", version: 1, title: "Engine" }],
};

// --- Fixtures ---------------------------------------------------------------

/** A saved node with the layout a drag leaves behind, unless told otherwise. */
function node(
  id: string,
  operatorId: string,
  x: number,
  y: number,
  overrides: Partial<AuthoredGraphNode> = {},
): AuthoredGraphNode {
  return {
    id,
    kind: "builtin",
    operator_id: operatorId,
    operator_version: 1,
    position: { x, y },
    // Bloated on purpose: cleanup takes a card back to its 300px default.
    layout: { width: 525, body_height: 250, appendix_height: null },
    artifact_type_bindings: [],
    input_plugs: [],
    config: {},
    ...overrides,
  };
}

function sizedNode(
  id: string,
  operatorId: string,
  x: number,
  y: number,
): AuthoredGraphNode {
  return node(id, operatorId, x, y, { layout: null });
}

function edge(
  id: string,
  fromNode: string,
  fromPort: string,
  toNode: string,
  toPort: string,
  overrides: Partial<AuthoredGraphEdge> = {},
): AuthoredGraphEdge {
  return {
    id,
    from_node: fromNode,
    from_port: fromPort,
    to_node: toNode,
    to_port: toPort,
    to_plug: null,
    enabled: true,
    collection_mode: "direct",
    projection: null,
    conversion_path: [],
    route_offset: null,
    ...overrides,
  };
}

/** The card-to-plug wire: this card's artifact fills that node's input. */
function origin(
  id: string,
  cardIds: readonly string[],
  toNode: string,
  toPort: string,
  key: { id: string; schema_version: number },
): AuthoredGraphOrigin {
  return {
    id,
    source_card_ids: cardIds,
    to_node: toNode,
    to_port: toPort,
    to_plug: null,
    value: {
      artifact_id: `artifact-${cardIds[0]}`,
      artifact_type: key.id,
      schema_version: key.schema_version,
    },
    collection_mode: "direct",
    conversion_path: [],
  };
}

function viewer(
  id: string,
  x: number,
  y: number,
  key: { id: string; schema_version: number } | null,
  layout: { width?: number; bodyHeight?: number } | null = null,
): ArtifactViewerNode {
  return {
    id,
    position: { x, y },
    data: {
      layout,
      mode: null,
      artifactRef: key
        ? {
            artifact_id: `artifact-${id}`,
            artifact_type: key.id,
            schema_version: key.schema_version,
          }
        : null,
    },
  };
}

function link(
  id: string,
  source: string,
  sourcePort: string,
  target: string,
  routeOffset?: { x: number; y: number },
): ArtifactViewerEdge {
  return {
    id,
    source,
    target,
    targetHandle: "artifact-viewer-input",
    data: {
      sourcePortName: sourcePort,
      ...(routeOffset ? { routeOffset } : {}),
    },
  };
}

function viewers(
  nodes: ArtifactViewerNode[],
  edges: ArtifactViewerEdge[] = [],
  annotations: AnnotationNode[] = [],
): ArtifactViewerCanvasState {
  return { nodes, edges, bindings: [], annotations };
}

function documentOf(
  nodes: AuthoredGraphNode[],
  edges: AuthoredGraphEdge[] = [],
  origins: AuthoredGraphOrigin[] = [],
  agents: SavedGraphAgent[] = [],
): AuthoredGraphDocument {
  return { name: "Cleanup", nodes, edges, origins, agents };
}

function tool(id: string, nodeId: string): SavedGraphAgent["tools"][number] {
  return {
    id,
    name: id,
    description: "",
    node_id: nodeId,
    filled_ports: [],
    returned_ports: [],
  };
}

function agent(
  id: string,
  x: number,
  y: number,
  overrides: Partial<SavedGraphAgent> = {},
): SavedGraphAgent {
  return {
    id,
    name: id,
    instructions: "",
    position: { x, y },
    width: 900,
    height: 900,
    tools: [],
    context: [],
    ...overrides,
  };
}

function annotation(
  id: string,
  kind: AnnotationNode["data"]["kind"],
  x: number,
  y: number,
  width: number,
  height: number,
  text = "",
): AnnotationNode {
  return {
    id,
    position: { x, y },
    data: { kind, layout: { width, height }, text, color: "#475569" },
  };
}

// --- Reading the plan back as a canvas --------------------------------------

function applyCommands(
  document: AuthoredGraphDocument,
  commands: readonly GraphCommand[],
): AuthoredGraphDocument {
  return commands.reduce(
    (current, command) => applyGraphCommandNormalized(current, command),
    document,
  );
}

/** Drop every projection the adapters add, so two documents compare fairly. */
function normalize(document: AuthoredGraphDocument): AuthoredGraphDocument {
  return applyGraphCommandNormalized(document, {
    kind: "replace_document",
    document,
  });
}

interface Canvas {
  readonly document: AuthoredGraphDocument;
  readonly viewers: ArtifactViewerCanvasState;
  readonly cards: ReadonlyMap<string, CellCardModel>;
  readonly scene: ReturnType<typeof cellGraphFromAuthoredDocument>;
}

/**
 * The canvas the plan produces: commands applied to the document, presentation
 * taken from the plan's viewer state, and every card read back the way the
 * canvas reads it. Assertions are made on cells, ports, and routes because that
 * is what a person actually sees.
 */
function canvasOf(
  document: AuthoredGraphDocument,
  viewerState: ArtifactViewerCanvasState,
): Canvas {
  const scene = cellGraphFromAuthoredDocument(document, registry, {
    presentation: presentationFromArtifactViewers(viewerState),
  });
  return {
    document,
    viewers: viewerState,
    scene,
    cards: new Map(scene.graph.cards.map((card) => [card.id, card])),
  };
}

interface Scenario {
  readonly source: AuthoredGraphDocument;
  readonly viewerState: ArtifactViewerCanvasState;
}

function planned(
  source: AuthoredGraphDocument,
  viewerState: ArtifactViewerCanvasState,
  options?: Parameters<typeof planCellGraphCleanup>[3],
) {
  const before = canvasOf(source, viewerState);
  const plan = planCellGraphCleanup(source, viewerState, registry, options);
  return {
    plan,
    before,
    after: canvasOf(
      applyCommands(source, plan.graphCommands),
      plan.nextArtifactViewers,
    ),
  };
}

function plannedScenario(
  scenario: Scenario,
  options?: Parameters<typeof planCellGraphCleanup>[3],
) {
  return planned(scenario.source, scenario.viewerState, options);
}

function cardOf(canvas: Canvas, id: string): CellCardModel {
  const card = canvas.cards.get(id);
  if (!card) throw new Error(`the canvas has no card ${id}`);
  return card;
}

function portRow(card: CellCardModel, id: string): number {
  const port = card.ports.find((entry) => entry.id === id);
  if (!port) throw new Error(`card ${card.id} has no port ${id}`);
  return port.rowOffset;
}

/** Do two cards' rectangles meet once each gets `marginCells` of port gutter? */
function overlaps(
  a: CellCardModel,
  b: CellCardModel,
  marginCells: number,
): boolean {
  return (
    a.col - marginCells < b.col + b.widthCells + marginCells &&
    b.col - marginCells < a.col + a.widthCells + marginCells &&
    a.row - marginCells < b.row + b.heightCells + marginCells &&
    b.row - marginCells < a.row + a.heightCells + marginCells
  );
}

function foreground(canvas: Canvas): CellCardModel[] {
  return [...canvas.cards.values()].filter(
    (card) => card.kind && card.kind !== "annotation",
  );
}

/** The same round trip the canvas makes before it offers to pile cards up. */
function mergeSuggestions(canvas: Canvas) {
  return findArtifactMergeSuggestions(
    [...canvas.cards.values()],
    canvas.scene.surfaceById,
    () => true,
  );
}

function clashes(
  cards: readonly CellCardModel[],
  marginCells: number,
): string[] {
  const found: string[] = [];
  for (let left = 0; left < cards.length; left += 1) {
    for (let right = left + 1; right < cards.length; right += 1) {
      const a = cards[left] as CellCardModel;
      const b = cards[right] as CellCardModel;
      if (overlaps(a, b, marginCells)) found.push(`${a.id} / ${b.id}`);
    }
  }
  return found;
}

// --- 1. One pipeline, read left to right ------------------------------------

describe("planCellGraphCleanup: a single pipeline", () => {
  /**
   * [Image Card] --origin--> [Document OCR] (+ [Mistral Provider] on its
   * service input) --link--> [Markdown Card] --origin--> [Extract Table]
   * --link--> [Table Card]
   */
  function scenario() {
    const source = documentOf(
      [
        node("ocr", "test.document_ocr", 1000, 410),
        node("mistral", "test.mistral_provider", 1010, 700),
        node("extract", "test.extract_table", 1500, 405),
      ],
      [edge("ocr-engine", "mistral", "engine", "ocr", "engine")],
      [
        origin("ocr-image", ["image-card"], "ocr", "document", PNG),
        origin(
          "extract-markdown",
          ["markdown-card"],
          "extract",
          "markdown",
          MD,
        ),
      ],
    );
    const viewerState = viewers(
      [
        viewer("image-card", 700, 400, PNG),
        viewer("markdown-card", 900, 380, MD, { width: 1200, bodyHeight: 600 }),
        viewer("table-card", 1400, 420, TABLE, {
          width: 1200,
          bodyHeight: 900,
        }),
      ],
      [
        link("ocr-out", "ocr", "markdown", "markdown-card"),
        link("extract-out", "extract", "table", "table-card"),
      ],
    );
    return { source, viewerState };
  }

  it("resizes every card to the size its kind is worth", () => {
    const { plan, after } = plannedScenario(scenario());
    expect(cardOf(after, "markdown-card")).toMatchObject({
      widthCells: 16,
      heightCells: 12,
    });
    expect(cardOf(after, "table-card")).toMatchObject({
      widthCells: 20,
      heightCells: 12,
    });
    // A bloated operator goes back to the 300px card the band computes itself.
    expect(cardOf(after, "ocr")).toMatchObject({ widthCells: 12 });
    expect(
      after.document.nodes.find((entry) => entry.id === "ocr")?.layout,
    ).toBeNull();
    expect(
      after.document.nodes.find((entry) => entry.id === "extract")?.layout,
    ).toBeNull();
    expect(
      after.viewers.nodes.find((entry) => entry.id === "markdown-card")?.data
        .layout,
    ).toEqual({ width: 400, bodyHeight: 300 });
    expect(plan.affectedCardCount).toBe(6);
  });

  it("reads strictly left to right", () => {
    const { after } = plannedScenario(scenario());
    const columns = [
      "image-card",
      "ocr",
      "markdown-card",
      "extract",
      "table-card",
    ].map((id) => cardOf(after, id).col);
    expect([...columns].sort((a, b) => a - b)).toEqual(columns);
    expect(new Set(columns).size).toBe(columns.length);
  });

  it("tucks the single-consumer provider under the head card, right-aligned", () => {
    const { after } = plannedScenario(scenario());
    const ocr = cardOf(after, "ocr");
    const image = cardOf(after, "image-card");
    const provider = cardOf(after, "mistral");
    // The provider holds no column of its own: it shares the head's.
    const headColumnRight = Math.max(
      ...foreground(after)
        .filter((card) => card.col < ocr.col)
        .map((card) => card.col + card.widthCells),
    );
    expect(provider.col + provider.widthCells).toBe(headColumnRight);
    // It reads underneath the card above it, in the same column, not a new row
    // of the pipeline: the trunk still starts at the safe origin.
    expect(provider.row).toBeGreaterThanOrEqual(
      image.row + image.heightCells + 2,
    );
    expect(image.col).toBe(4);
    expect(image.row).toBe(5);
    // ...and its wire runs straight into the card it serves.
    expect(provider.col + provider.widthCells).toBeLessThanOrEqual(ocr.col);
  });

  it("keeps the trunk on one baseline instead of staircasing it", () => {
    const { after } = plannedScenario(scenario());
    const rows = [
      "image-card",
      "ocr",
      "markdown-card",
      "extract",
      "table-card",
    ].map((id) => cardOf(after, id).row);
    expect(new Set(rows).size).toBe(1);
  });

  it("leaves no card, or the port cells around it, on top of another", () => {
    const { after } = plannedScenario(scenario());
    const cards = foreground(after);
    expect(cards).toHaveLength(6);
    // One cell of margin is where a card's ports and their wells live.
    expect(clashes(cards, 1)).toEqual([]);
  });

  it("never offers a merge seam between cards that only look paired", () => {
    const { after } = plannedScenario(scenario());
    expect(mergeSuggestions(after)).toEqual([]);
  });

  it("routes every pipe without pushing one below the glass", () => {
    const { after } = plannedScenario(scenario());
    const routed = routeCellGraph(after.scene.graph, {
      exits: "side",
      underCards: "avoid",
      depth: true,
    });
    expect(routed.pipes.size).toBe(after.scene.graph.pipes.length);
    expect(after.scene.graph.pipes.length).toBeGreaterThan(0);
    expect(routed.maxDepthUsed).toBe(0);
  });

  it("starts clear of the chrome pinned to the canvas' top-left corner", () => {
    const { after } = plannedScenario(scenario());
    for (const card of foreground(after)) {
      expect(card.col * CELL_SIZE).toBeGreaterThanOrEqual(4 * CELL_SIZE);
      expect(card.row * CELL_SIZE).toBeGreaterThanOrEqual(5 * CELL_SIZE);
    }
  });

  it("sees one experiment and reports the box it filled", () => {
    const { plan, after } = plannedScenario(scenario());
    expect(plan.experimentCount).toBe(1);
    expect(plan.changed).toBe(true);
    const cards = foreground(after);
    expect(plan.bounds).toEqual({
      x: Math.min(...cards.map((card) => card.col)) * CELL_SIZE,
      y: Math.min(...cards.map((card) => card.row)) * CELL_SIZE,
      width:
        (Math.max(...cards.map((card) => card.col + card.widthCells)) -
          Math.min(...cards.map((card) => card.col))) *
        CELL_SIZE,
      height:
        (Math.max(...cards.map((card) => card.row + card.heightCells)) -
          Math.min(...cards.map((card) => card.row))) *
        CELL_SIZE,
    });
  });
});

// --- 2. Branches and several experiments ------------------------------------

describe("planCellGraphCleanup: branches and stacked experiments", () => {
  function scenario() {
    const source = documentOf(
      [
        sizedNode("top", "test.read_png", 300, -200),
        node("recognize", "test.recognize", 700, 780),
        node("reader-a", "test.mistral_provider", 450, 900),
        node("transliterate", "test.transliterate", 700, 1010),
        node("reader-b", "test.mistral_provider", 430, 1130),
      ],
      [
        edge("recognize-a", "reader-a", "engine", "recognize", "engine"),
        edge(
          "transliterate-b",
          "reader-b",
          "engine",
          "transliterate",
          "engine",
        ),
      ],
      [
        origin("recognize-scan", ["tiff-card"], "recognize", "regions", TIFF),
        origin(
          "transliterate-scan",
          ["tiff-card"],
          "transliterate",
          "regions",
          TIFF,
        ),
      ],
    );
    const viewerState = viewers(
      [viewer("top-card", 700, -210, PNG), viewer("tiff-card", 200, 800, TIFF)],
      [link("top-out", "top", "png", "top-card")],
    );
    return { source, viewerState };
  }

  it("keeps the experiment that was on top on top", () => {
    const { plan, after } = plannedScenario(scenario());
    expect(plan.experimentCount).toBe(2);
    const first = ["top", "top-card"].map((id) => cardOf(after, id));
    const second = ["tiff-card", "recognize", "transliterate"].map((id) =>
      cardOf(after, id),
    );
    const firstBottom = Math.max(
      ...first.map((card) => card.row + card.heightCells),
    );
    expect(Math.min(...second.map((card) => card.row))).toBeGreaterThanOrEqual(
      firstBottom + 5,
    );
  });

  it("runs the first branch along the lane and drops the second beneath it", () => {
    const { after } = plannedScenario(scenario());
    const tiff = cardOf(after, "tiff-card");
    const recognize = cardOf(after, "recognize");
    const transliterate = cardOf(after, "transliterate");
    // Branch A is the lane the experiment was entered on: level with its head.
    expect(recognize.row).toBe(tiff.row);
    // Branch B opens a lane below, with room for a floating title between.
    expect(transliterate.row).toBeGreaterThan(
      recognize.row + recognize.heightCells,
    );
    expect(transliterate.col).toBe(recognize.col);
    expect(clashes(foreground(after), 1)).toEqual([]);
  });

  it("aligns a provider that owns a column to the port it feeds", () => {
    const { after } = plannedScenario(scenario());
    const tiff = cardOf(after, "tiff-card");
    const recognize = cardOf(after, "recognize");
    const transliterate = cardOf(after, "transliterate");
    const readerA = cardOf(after, "reader-a");
    const readerB = cardOf(after, "reader-b");

    // Branch A's provider shares the head's column, right-aligned to its seam.
    expect(readerA.col + readerA.widthCells).toBe(tiff.col + tiff.widthCells);
    expect(readerA.row).toBeGreaterThan(tiff.row + tiff.heightCells);
    // Branch B's provider has an empty column to itself, so it drops to put its
    // output exactly on the service-input row of the card it serves.
    expect(readerB.row + portRow(readerB, "engine")).toBe(
      transliterate.row + portRow(transliterate, "engine"),
    );
    // ...which is not where the lane's top row would have put it.
    expect(readerB.row).not.toBe(transliterate.row);
    expect(recognize.id).toBeTruthy();
  });
});

// --- 3. Paired comparisons and the parked cards -----------------------------

describe("planCellGraphCleanup: paired cards and strays", () => {
  function scenario() {
    const source = documentOf([
      sizedNode("producer", "test.read_png", 0, 0),
      sizedNode("stray", "test.counter", 60, 1400),
    ]);
    const viewerState = viewers(
      [
        viewer("wired-md", 420, 0, MD),
        // 25px clear of the wired card, level with it: a side-by-side compare.
        viewer("companion-md", 420 + 250 + 25, 10, MD),
        viewer("stray-card", 600, 1600, SCALAR_INT),
      ],
      [link("producer-out", "producer", "png", "wired-md")],
    );
    return { source, viewerState };
  }

  it("keeps a paired card beside its partner", () => {
    const { plan, after } = plannedScenario(scenario());
    const wired = cardOf(after, "wired-md");
    const companion = cardOf(after, "companion-md");
    expect(plan.experimentCount).toBe(1);
    expect(companion.row).toBe(wired.row);
    // Two cells: clear enough that the canvas never reads them as one pile.
    expect(companion.col - (wired.col + wired.widthCells)).toBe(2);
    expect(mergeSuggestions(after)).toEqual([]);
  });

  it("parks the cards that belong to nothing, below the wired graph", () => {
    const { after } = plannedScenario(scenario());
    const experimentBottom = Math.max(
      cardOf(after, "wired-md").row + cardOf(after, "wired-md").heightCells,
      cardOf(after, "producer").row + cardOf(after, "producer").heightCells,
      cardOf(after, "companion-md").row +
        cardOf(after, "companion-md").heightCells,
    );
    const strayNode = cardOf(after, "stray");
    const strayCard = cardOf(after, "stray-card");
    expect(strayNode.row).toBeGreaterThanOrEqual(experimentBottom + 5);
    expect(strayCard.row).toBeGreaterThanOrEqual(strayNode.row);
    // The strip keeps the order the author left them in.
    expect(strayCard.col).toBeGreaterThan(strayNode.col);
    expect(clashes(foreground(after), 1)).toEqual([]);
  });
});

// --- 4. Cleaning up a selection --------------------------------------------

describe("planCellGraphCleanup: a scoped selection", () => {
  function scenario() {
    const source = documentOf(
      [
        node("mess-a", "test.read_png", 1500, 900),
        node("mess-b", "test.read_png", 1450, 400),
        node("far-node", "test.counter", 40, 40, {
          layout: { width: 700, body_height: 500, appendix_height: 400 },
        }),
      ],
      [edge("a-b", "mess-b", "png", "mess-a", "png")],
    );
    const viewerState = viewers(
      [
        viewer("mess-card", 1900, 700, PNG),
        viewer("far-card", 900, 120, MD, { width: 800, bodyHeight: 500 }),
      ],
      [link("a-out", "mess-a", "png", "mess-card")],
    );
    return { source, viewerState };
  }

  it("arranges only the selection, at the selection's own corner", () => {
    const { source, viewerState } = scenario();
    const { plan, after } = planned(source, viewerState, {
      selectedCardIds: new Set(["mess-a", "mess-b", "mess-card"]),
    });
    // Anchored where the selection already stood, not at the graph's safe origin.
    expect(plan.bounds?.x).toBe(1450);
    const moved = ["mess-a", "mess-b", "mess-card"].map((id) =>
      cardOf(after, id),
    );
    expect(Math.min(...moved.map((card) => card.col))).toBe(58);
    expect(Math.min(...moved.map((card) => card.row))).toBe(16);
    expect(plan.affectedCardCount).toBe(3);
    // Still a pipeline: the card it feeds sits right of the card that feeds it.
    expect(cardOf(after, "mess-card").col).toBeGreaterThan(
      cardOf(after, "mess-a").col,
    );

    // Everything else is left exactly as the author left it.
    const far = cardOf(after, "far-node");
    expect({ col: far.col, row: far.row }).toEqual({ col: 2, row: 2 });
    expect(
      after.document.nodes.find((entry) => entry.id === "far-node")?.layout,
    ).toEqual({
      width: 700,
      body_height: 500,
      appendix_height: 400,
    });
    const farCard = after.viewers.nodes.find(
      (entry) => entry.id === "far-card",
    );
    expect(farCard?.position).toEqual({ x: 900, y: 120 });
    expect(farCard?.data.layout).toEqual({ width: 800, bodyHeight: 500 });
  });

  it("treats a single selected card as no selection at all", () => {
    const { source, viewerState } = scenario();
    const { plan } = planned(source, viewerState, {
      selectedCardIds: new Set(["mess-a"]),
    });
    expect(plan.experimentCount).toBe(1);
    expect(plan.bounds?.x).toBe(4 * CELL_SIZE);
    expect(plan.bounds?.y).toBe(5 * CELL_SIZE);
  });
});

// --- 5. The furniture layer and hand-drawn wire offsets ---------------------

describe("planCellGraphCleanup: annotations and route offsets", () => {
  it("closes a frame on the cards it enclosed", () => {
    const source = documentOf(
      [
        sizedNode("left", "test.read_png", 400, 400),
        sizedNode("right", "test.counter", 900, 410),
      ],
      [
        edge("l-r", "left", "png", "right", "count", {
          route_offset: { x: 40, y: -60 },
        }),
      ],
    );
    const viewerState = viewers(
      [],
      [],
      [
        annotation("frame", "rectangle", 350, 350, 900, 300),
        annotation("note", "text", 1800, 380, 240, 120, "look here"),
      ],
    );
    const { plan, after } = planned(source, viewerState);
    const frame = after.viewers.annotations.find(
      (entry) => entry.id === "frame",
    );
    const left = cardOf(after, "left");
    const right = cardOf(after, "right");
    const pad = 2 * CELL_SIZE;
    expect(frame?.position).toEqual({
      x: left.col * CELL_SIZE - pad,
      y: left.row * CELL_SIZE - pad,
    });
    expect(frame?.data.layout).toEqual({
      width: (right.col + right.widthCells - left.col) * CELL_SIZE + pad * 2,
      height: (left.row + left.heightCells - left.row) * CELL_SIZE + pad * 2,
    });

    // A wire the author nudged by hand has no reason to keep that nudge.
    expect(
      after.document.edges.find((entry) => entry.id === "l-r")?.route_offset,
    ).toBeNull();
    expect(
      plan.graphCommands.filter((command) => command.kind === "update_edge"),
    ).toHaveLength(1);
    // A note with no card near it keeps its place, on the grid.
    const note = after.viewers.annotations.find((entry) => entry.id === "note");
    expect(note?.position).toEqual({ x: 1800, y: 375 });
  });

  it("clears a following card's stored offset too", () => {
    const source = documentOf([
      sizedNode("producer", "test.read_png", 100, 100),
    ]);
    const viewerState = viewers(
      [viewer("card", 600, 100, PNG)],
      [link("out", "producer", "png", "card", { x: 30, y: 20 })],
    );
    const { plan, after } = planned(source, viewerState);
    expect(
      plan.nextArtifactViewers.edges[0]?.data?.routeOffset,
    ).toBeUndefined();
    expect(after.viewers.edges[0]?.data?.routeOffset).toBeUndefined();
  });
});

// --- 6. Undo ----------------------------------------------------------------

describe("buildCleanupUndoPlan", () => {
  it("puts every card back exactly where it started", () => {
    const assistant = agent("assistant", 2100, 300, {
      tools: [tool("t1", "ocr")],
      context: [
        { id: "c1", kind: "node_output", node_id: "extract", port: "table" },
      ],
    });
    const source = documentOf(
      [
        node("ocr", "test.document_ocr", 1000, 410, {
          layout: { width: 480, body_height: 220, appendix_height: 300 },
        }),
        node("mistral", "test.mistral_provider", 1010, 700),
        node("extract", "test.extract_table", 1500, 405),
      ],
      [
        edge("ocr-engine", "mistral", "engine", "ocr", "engine", {
          route_offset: { x: 12, y: 8 },
        }),
      ],
      [
        origin("ocr-image", ["image-card"], "ocr", "document", PNG),
        origin("extract-md", ["markdown-card"], "extract", "markdown", MD),
      ],
      [assistant],
    );
    const viewerState = viewers(
      [
        viewer("image-card", 700, 400, PNG),
        viewer("markdown-card", 900, 380, MD, { width: 1200, bodyHeight: 600 }),
        viewer("map-card", 2000, 900, MAP, { width: 900, bodyHeight: 700 }),
      ],
      [
        link("ocr-out", "ocr", "markdown", "markdown-card", { x: 5, y: -5 }),
        link("map-out", "extract", "table", "map-card"),
      ],
      [annotation("note", "text", 1500, 200, 240, 120, "note")],
    );

    const before = normalize(source);
    const beforeViewers = structuredClone(viewerState);
    const plan = planCellGraphCleanup(source, viewerState, registry);
    expect(plan.changed).toBe(true);
    expect(foreground(canvasOf(source, viewerState))).toHaveLength(7);

    const cleaned = applyCommands(source, plan.graphCommands);
    const cleanedViewers = plan.nextArtifactViewers;
    // Something really did move, or the undo proves nothing.
    expect(normalize(cleaned).nodes[0]?.position).not.toEqual(
      before.nodes[0]?.position,
    );

    const undo = buildCleanupUndoPlan(
      cleaned,
      cleanedViewers,
      plan.undoSnapshot,
    );
    expect(undo.changed).toBe(true);
    const restored = normalize(
      applyCommands(cleaned, undo.graphCommands as GraphCommand[]),
    );

    for (const original of before.nodes) {
      const entry = restored.nodes.find(
        (candidate) => candidate.id === original.id,
      );
      expect(entry?.position).toEqual(original.position);
      expect(entry?.layout ?? null).toEqual(original.layout ?? null);
    }
    expect(restored.edges.map((entry) => entry.route_offset ?? null)).toEqual(
      before.edges.map((entry) => entry.route_offset ?? null),
    );
    expect(restored.agents[0]?.position).toEqual(assistant.position);
    expect(restored.agents[0]?.width).toEqual(assistant.width);
    expect(restored.agents[0]?.height).toEqual(assistant.height);

    expect(cleanedViewers.nodes.map((entry) => entry.position)).not.toEqual(
      beforeViewers.nodes.map((entry) => entry.position),
    );
    expect(undo.nextArtifactViewers.nodes).toEqual(beforeViewers.nodes);
    expect(undo.nextArtifactViewers.edges).toEqual(beforeViewers.edges);
    expect(undo.nextArtifactViewers.annotations).toEqual(
      beforeViewers.annotations,
    );
  });

  it("is a no-op when nothing was recorded", () => {
    const source = documentOf([sizedNode("solo", "test.read_png", 100, 100)]);
    const undo = buildCleanupUndoPlan(source, viewers([]), {
      nodeSnapshots: new Map(),
      edgeRouteOffsets: new Map(),
      agentSnapshots: new Map(),
      viewerSnapshots: new Map(),
      viewerEdgeRouteOffsets: new Map(),
      annotationSnapshots: new Map(),
    });
    expect(undo.changed).toBe(false);
    expect(undo.graphCommands).toEqual([]);
  });
});

// --- The plan's own honesty -------------------------------------------------

describe("planCellGraphCleanup: the plan itself", () => {
  it("emits nothing when the graph is already straight", () => {
    const source = documentOf([
      sizedNode("solo", "test.read_png", 4 * CELL_SIZE, 5 * CELL_SIZE),
    ]);
    const { plan } = planned(source, viewers([]));
    expect(plan.changed).toBe(false);
    expect(plan.graphCommands).toEqual([]);
    expect(plan.nextArtifactViewers).toEqual(viewers([]));
    expect(plan.experimentCount).toBe(0);
    expect(plan.affectedCardCount).toBe(1);
  });

  it("can leave sizes alone and only tidy the layout", () => {
    const source = documentOf([node("solo", "test.read_png", 100, 100)]);
    const { plan } = planned(source, viewers([]), { resizeCards: false });
    expect(
      plan.graphCommands.some(
        (command) => command.kind === "update_node_layout",
      ),
    ).toBe(false);
    // The document it was handed is never touched.
    expect(source.nodes[0]?.layout).toEqual({
      width: 525,
      body_height: 250,
      appendix_height: null,
    });
    expect(source.nodes[0]?.position).toEqual({ x: 100, y: 100 });
  });

  it("resizes an agent's box to what it holds", () => {
    const big = agent("assistant", 0, 0, {
      tools: [tool("t1", "solo"), tool("t2", "solo"), tool("t3", "solo")],
    });
    const source = documentOf(
      [sizedNode("solo", "test.read_png", 0, 0)],
      [],
      [],
      [big],
    );
    const { plan } = planned(source, viewers([]));
    const configs = plan.graphCommands.filter(
      (command) => command.kind === "configure_agent",
    );
    // One command carries the move and the resize together.
    expect(configs).toHaveLength(1);
    const command = configs[0];
    expect(command?.kind === "configure_agent" ? command.agent.width : 0).toBe(
      14 * CELL_SIZE,
    );
    expect(command?.kind === "configure_agent" ? command.agent.height : 0).toBe(
      16 * CELL_SIZE,
    );
    expect(
      cardOf(planned(source, viewers([])).after, "assistant").widthCells,
    ).toBe(14);
  });

  it("keeps a card that only the presentation knows about", () => {
    const source = documentOf([sizedNode("solo", "test.read_png", 0, 0)]);
    const viewerState = viewers([viewer("ghost", 3000, 3000, PNG)]);
    const { plan, after } = planned(source, viewerState);
    expect(cardOf(after, "solo")).toMatchObject({ col: 4, row: 5 });
    // The card follows the graph, so it is parked too, not left at 3000,3000.
    expect(cardOf(after, "ghost").col).toBeGreaterThan(
      cardOf(after, "solo").col,
    );
    expect(plan.experimentCount).toBe(0);
  });

  it("records what it overwrote without editing the document", () => {
    const source = documentOf([node("solo", "test.read_png", 111, 222)]);
    const plan = planCellGraphCleanup(source, viewers([]), registry);
    expect(source.nodes[0]?.position).toEqual({ x: 111, y: 222 });
    expect(plan.undoSnapshot.nodeSnapshots.get("solo")?.position).toEqual({
      x: 111,
      y: 222,
    });
    expect(createGraphDraft(source).document.nodes[0]?.id).toBe("solo");
  });
});

// --- Tunable cleanup parameters ---------------------------------------------

describe("planCellGraphCleanup: tunable parameters", () => {
  it("applies custom column, lane, stack, and experiment gaps", () => {
    const source = documentOf(
      [
        sizedNode("top", "test.read_png", 0, 0),
        sizedNode("recognize", "test.recognize", 400, 500),
        sizedNode("reader-a", "test.mistral_provider", 200, 620),
        sizedNode("transliterate", "test.transliterate", 400, 740),
      ],
      [edge("rec-engine", "reader-a", "engine", "recognize", "engine")],
      [
        origin("rec-scan", ["tiff-card"], "recognize", "regions", TIFF),
        origin("tr-scan", ["tiff-card"], "transliterate", "regions", TIFF),
      ],
    );
    const viewerState = viewers(
      [viewer("top-card", 400, 0, PNG), viewer("tiff-card", 100, 500, TIFF)],
      [link("top-out", "top", "png", "top-card")],
    );

    const { after } = planned(source, viewerState, {
      params: {
        columnGapCells: 7,
        laneGapCells: 5,
        stackGapCells: 4,
        experimentGapCells: 9,
      },
    });

    const top = cardOf(after, "top");
    const topCard = cardOf(after, "top-card");
    const tiff = cardOf(after, "tiff-card");
    const readerA = cardOf(after, "reader-a");
    const recognize = cardOf(after, "recognize");
    const transliterate = cardOf(after, "transliterate");

    // Column gap: 7 cells between pipeline steps
    expect(topCard.col - (top.col + top.widthCells)).toBe(7);
    expect(recognize.col - (tiff.col + tiff.widthCells)).toBe(7);
    // Stack gap: 4 cells between tiff and tucked provider below it
    expect(readerA.row - (tiff.row + tiff.heightCells)).toBe(4);
    // Experiment gap: 9 cells between experiment 1 bottom and experiment 2 top
    const exp1Bottom = Math.max(
      top.row + top.heightCells,
      topCard.row + topCard.heightCells,
    );
    expect(tiff.row - exp1Bottom).toBe(9);
    // Lane gap: 5 cells between first lane bottom and second branch
    const lane1Bottom = Math.max(
      tiff.row + tiff.heightCells,
      readerA.row + readerA.heightCells,
      recognize.row + recognize.heightCells,
    );
    expect(transliterate.row - lane1Bottom).toBe(5);
  });

  it("scales canonical card sizes via compact and roomy presets", () => {
    const source = documentOf([sizedNode("producer", "test.read_png", 0, 0)]);
    const viewerState = viewers(
      [viewer("md-card", 500, 0, MD), viewer("tbl-card", 900, 0, TABLE)],
      [
        link("out-md", "producer", "png", "md-card"),
        link("out-tbl", "producer", "png", "tbl-card"),
      ],
    );

    const compact = planned(source, viewerState, {
      params: { cardSize: "compact" },
    }).after;
    const roomy = planned(source, viewerState, {
      params: { cardSize: "roomy" },
    }).after;

    expect(cardOf(compact, "md-card")).toMatchObject({
      widthCells: 12,
      heightCells: 9,
    });
    expect(cardOf(compact, "tbl-card")).toMatchObject({
      widthCells: 16,
      heightCells: 10,
    });
    expect(cardOf(roomy, "md-card")).toMatchObject({
      widthCells: 20,
      heightCells: 15,
    });
    expect(cardOf(roomy, "tbl-card")).toMatchObject({
      widthCells: 24,
      heightCells: 15,
    });
  });

  it("respects tuckProviders, alignPorts, keepCompanions, and clearRouteOffsets toggles", () => {
    const source = documentOf(
      [
        sizedNode("ocr", "test.document_ocr", 500, 200),
        sizedNode("mistral", "test.mistral_provider", 100, 500),
      ],
      [
        edge("ocr-engine", "mistral", "engine", "ocr", "engine", {
          route_offset: { x: 40, y: -20 },
        }),
      ],
      [origin("ocr-img", ["img-card"], "ocr", "document", PNG)],
    );
    const viewerState = viewers(
      [
        viewer("img-card", 100, 200, PNG),
        viewer("md-card", 900, 200, MD),
        viewer("pair-md", 900 + 250 + 25, 200, MD),
      ],
      [link("ocr-out", "ocr", "markdown", "md-card", { x: 15, y: 10 })],
    );

    const { after } = planned(source, viewerState, {
      params: {
        tuckProviders: false,
        alignPorts: false,
        keepCompanions: false,
        clearRouteOffsets: false,
      },
    });

    // Without tuckProviders, mistral is ranked as its own root rather than right-aligned under img-card
    const img = cardOf(after, "img-card");
    const mistral = cardOf(after, "mistral");
    expect(mistral.col).toBe(img.col);

    // Without keepCompanions, pair-md is parked below the experiment rather than beside md-card
    const md = cardOf(after, "md-card");
    const pair = cardOf(after, "pair-md");
    expect(pair.row).toBeGreaterThan(md.row + md.heightCells);

    // Without clearRouteOffsets, manual offsets remain untouched
    expect(after.document.edges[0]?.route_offset).toEqual({ x: 40, y: -20 });
    expect(after.viewers.edges[0]?.data?.routeOffset).toEqual({ x: 15, y: 10 });
  });

  it("is idempotent on a second cleanup with the same parameters", () => {
    const source = documentOf(
      [
        node("ocr", "test.document_ocr", 1000, 410),
        node("mistral", "test.mistral_provider", 1010, 700),
      ],
      [edge("ocr-engine", "mistral", "engine", "ocr", "engine")],
      [origin("ocr-image", ["image-card"], "ocr", "document", PNG)],
    );
    const viewerState = viewers(
      [
        viewer("image-card", 700, 400, PNG),
        viewer("markdown-card", 900, 380, MD, { width: 1200, bodyHeight: 600 }),
      ],
      [link("ocr-out", "ocr", "markdown", "markdown-card")],
    );

    const first = planCellGraphCleanup(source, viewerState, registry);
    expect(first.changed).toBe(true);
    const docAfterFirst = applyCommands(source, first.graphCommands);
    const second = planCellGraphCleanup(
      docAfterFirst,
      first.nextArtifactViewers,
      registry,
    );
    expect(second.changed).toBe(false);
    expect(second.graphCommands).toEqual([]);
  });

  it("restores the initial state after multiple cleanups with different parameters and scopes", () => {
    const source = documentOf(
      [
        node("ocr", "test.document_ocr", 1010, 415),
        node("mistral", "test.mistral_provider", 1020, 705),
        node("stray", "test.counter", 1850, 95),
      ],
      [
        edge("ocr-engine", "mistral", "engine", "ocr", "engine", {
          route_offset: { x: 25, y: -50 },
        }),
      ],
      [origin("ocr-image", ["image-card"], "ocr", "document", PNG)],
    );
    const viewerState = viewers(
      [
        viewer("image-card", 710, 405, PNG),
        viewer("markdown-card", 910, 385, MD, { width: 900, bodyHeight: 500 }),
      ],
      [link("ocr-out", "ocr", "markdown", "markdown-card", { x: 10, y: 10 })],
    );

    const beforeDoc = normalize(source);
    const beforeViewers = structuredClone(viewerState);

    // Cleanup 1: scoped selection with compact sizes
    const p1 = planCellGraphCleanup(source, viewerState, registry, {
      selectedCardIds: new Set(["ocr", "image-card", "markdown-card"]),
      params: { cardSize: "compact", columnGapCells: 3 },
    });
    expect(p1.changed).toBe(true);
    const doc1 = applyCommands(source, p1.graphCommands);
    const viewers1 = p1.nextArtifactViewers;

    // Cleanup 2: whole canvas with roomy sizes and wide gutters
    const p2 = planCellGraphCleanup(doc1, viewers1, registry, {
      params: { cardSize: "roomy", columnGapCells: 8 },
    });
    expect(p2.changed).toBe(true);
    const doc2 = applyCommands(doc1, p2.graphCommands);
    const viewers2 = p2.nextArtifactViewers;

    // Merged initial snapshot reverts all the way back to the original canvas in one pass
    const initialSnapshot = mergeCleanupUndoSnapshots(
      p1.undoSnapshot,
      p2.undoSnapshot,
    );
    const revert = buildCleanupUndoPlan(doc2, viewers2, initialSnapshot);
    expect(revert.changed).toBe(true);
    const restored = normalize(applyCommands(doc2, revert.graphCommands));

    for (const original of beforeDoc.nodes) {
      const entry = restored.nodes.find((n) => n.id === original.id);
      expect(entry?.position).toEqual(original.position);
      expect(entry?.layout ?? null).toEqual(original.layout ?? null);
    }
    expect(restored.edges[0]?.route_offset).toEqual({ x: 25, y: -50 });
    expect(revert.nextArtifactViewers.nodes).toEqual(beforeViewers.nodes);
    expect(revert.nextArtifactViewers.edges).toEqual(beforeViewers.edges);
  });
});
