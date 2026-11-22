import { readFileSync } from "node:fs";
import * as path from "node:path";
import { assert, describe, expect, it } from "vitest";

import type {
  NodeRegistry,
  NodeSpec,
  Port,
  SavedGraphDocument,
} from "@/lib/api";

import { COLLECTION_OPERATOR_ID } from "../authoring/collection-spec";
import {
  applyGraphCommandNormalized,
  authoredGraphDocument,
  createGraphDraft,
  type AuthoredGraphDocument,
  type AuthoredGraphNode,
  type GraphCommand,
} from "../authoring/graph-document";
import {
  CELL_SIZE,
  type CellCardKind,
  type CellCardModel,
  type CellResizeBounds,
} from "./cell-model";
import {
  cellArtifactImageCells,
  cellGraphFromAuthoredDocument,
  graphCommandsFromCellResize,
  graphCommandsFromCellResizeForDocument,
} from "./cell-document-adapter";

/**
 * The cell canvas resizes cards, and a resize is only legal while the pixels it
 * writes back sit inside the schema the API validates them against. Those
 * numbers are read from the committed OpenAPI document here, rather than from a
 * second copy of the limits that someone has to remember to keep in step.
 */

interface SchemaProperty {
  type?: string;
  minimum?: number;
  maximum?: number;
  anyOf?: readonly SchemaProperty[];
}

interface OpenApiDocument {
  components: {
    schemas: Record<
      string,
      {
        properties?: Record<string, SchemaProperty>;
      }
    >;
  };
}

const OPENAPI_PATH = path.resolve(__dirname, "../../../../openapi/grafy.json");
const openapi = JSON.parse(
  readFileSync(OPENAPI_PATH, "utf8"),
) as OpenApiDocument;

function numericBounds(
  schemaName: string,
  propertyName: string,
): { minimum: number; maximum: number } {
  const prop =
    openapi.components.schemas[schemaName]?.properties?.[propertyName];
  if (!prop) {
    throw new Error(`Missing schema property ${schemaName}.${propertyName}`);
  }
  const branch =
    prop.anyOf?.find((candidate) => candidate.type === "number") ?? prop;
  if (
    typeof branch.minimum !== "number" ||
    typeof branch.maximum !== "number"
  ) {
    throw new Error(`Missing numeric bounds on ${schemaName}.${propertyName}`);
  }
  return { minimum: branch.minimum, maximum: branch.maximum };
}

function expectWithin(
  value: number,
  bounds: { minimum: number; maximum: number },
): void {
  expect(value).toBeGreaterThanOrEqual(bounds.minimum);
  expect(value).toBeLessThanOrEqual(bounds.maximum);
}

/** Which schema validates the layout each card kind writes back. */
const KIND_SCHEMA: Record<
  CellCardKind,
  { schema: string; width: string; height: string }
> = {
  operator: {
    schema: "GraphNodeLayout",
    width: "width",
    height: "body_height",
  },
  collection: {
    schema: "GraphNodeLayout",
    width: "width",
    height: "body_height",
  },
  agent: { schema: "GraphAgent", width: "width", height: "height" },
  artifact: {
    schema: "GraphPresentationViewerLayout",
    width: "width",
    height: "body_height",
  },
  annotation: {
    schema: "GraphAnnotationLayout",
    width: "width",
    height: "height",
  },
};

const CARD_KINDS = Object.keys(KIND_SCHEMA) as CellCardKind[];

/** Commits a drag can hand over at the edges of its travel, and past them. */
const OUT_OF_RANGE_CELLS = [
  { widthCells: 0, heightCells: 0 },
  { widthCells: 1, heightCells: 1 },
  { widthCells: 8, heightCells: 3 },
  { widthCells: 999, heightCells: 999 },
];

function commitsWithin(bounds: CellResizeBounds) {
  return [
    ...OUT_OF_RANGE_CELLS,
    { widthCells: bounds.minWidthCells, heightCells: bounds.minHeightCells },
    {
      widthCells: bounds.maxWidthCells ?? bounds.minWidthCells,
      heightCells: bounds.maxHeightCells ?? bounds.minHeightCells,
    },
  ];
}

const textType = { id: "scalar.text", schema_version: 2 };

function port(name: string, overrides: Partial<Port> = {}): Port {
  return {
    name,
    kind: "artifact",
    accepted_shapes: ["one"],
    artifact_type: textType,
    direction: "input",
    instance_plugs: false,
    required: true,
    shape: "one",
    variadic: false,
    ...overrides,
  };
}

const operatorSpec: NodeSpec = {
  operator_id: "test.source",
  operator_version: 1,
  title: "Source",
  description: "",
  plugin_slug: "test",
  catalog_visible: true,
  origin: "builtin",
  runnable: true,
  input_schema: {},
  output_schema: {},
  inputs: [port("trigger")],
  outputs: [port("result", { direction: "output" })],
  config_schema: {},
};
const collectionSpec: NodeSpec = {
  ...operatorSpec,
  operator_id: COLLECTION_OPERATOR_ID,
  title: "Collect",
  inputs: [port("items", { instance_plugs: true, required: false })],
  outputs: [port("sequence", { direction: "output", shape: "many" })],
};
const registry: NodeRegistry = {
  nodes: [operatorSpec, collectionSpec],
  artifact_types: [],
  artifact_conversions: [],
  plugins: [],
};

function node(
  id: string,
  operatorId: string,
  layout: AuthoredGraphNode["layout"],
  inputPlugs: { id: string; port: string }[] = [],
): AuthoredGraphNode {
  return {
    id,
    kind: "builtin",
    operator_id: operatorId,
    operator_version: 1,
    position: { x: 0, y: 0 },
    layout,
    artifact_type_bindings: [],
    input_plugs: inputPlugs,
    config: {},
  };
}

type Presentation = NonNullable<SavedGraphDocument["presentation"]>;

/** One card of every kind, so every contract is read off the same scene. */
const SCENE_PRESENTATION: Presentation = {
  viewers: [
    {
      id: "viewer",
      position: { x: 400, y: 0 },
      layout: { width: 250, body_height: 150, appendix_height: null },
      mode: "artifact",
      artifact_ref: {
        artifact_id: "a1",
        artifact_type: textType.id,
        schema_version: textType.schema_version,
      },
    },
  ],
  links: [],
  bindings: [],
  annotations: [
    {
      id: "note",
      kind: "rectangle",
      position: { x: 0, y: 400 },
      layout: { width: 200, height: 150 },
      text: "",
      color: "slate",
    },
  ],
};

function scene(): AuthoredGraphDocument {
  return authoredGraphDocument(
    createGraphDraft(
      {
        name: "Bounds",
        nodes: [
          // appendix_height 101 sits under the schema floor on purpose: a
          // resize has to carry it back up, not repeat it.
          node("node", "test.source", {
            width: 300,
            body_height: 200,
            appendix_height: 101,
          }),
          node("collection", COLLECTION_OPERATOR_ID, null, [
            { id: "one", port: "items" },
          ]),
        ],
        edges: [],
        origins: [],
        agents: [
          {
            id: "agent",
            name: "Review",
            instructions: "",
            width: 360,
            height: 200,
            position: { x: 0, y: 800 },
            context: [],
            tools: [],
          },
        ],
      },
      SCENE_PRESENTATION,
    ),
  );
}

function readScene(
  document: AuthoredGraphDocument,
  presentation: Presentation = SCENE_PRESENTATION,
) {
  return cellGraphFromAuthoredDocument(document, registry, { presentation })
    .graph;
}

function cardOfKind(document: AuthoredGraphDocument, kind: CellCardKind) {
  const card = readScene(document).cards.find(
    (candidate) => candidate.kind === kind,
  );
  assert(card, `the scene has no ${kind} card`);
  return card;
}

function cardById(graphCards: readonly CellCardModel[], id: string) {
  const card = graphCards.find((candidate) => candidate.id === id);
  assert(card, `the scene has no card ${id}`);
  return card;
}

function resizeCommands(
  document: AuthoredGraphDocument,
  commit: { cardId: string; widthCells: number; heightCells: number },
): GraphCommand[] {
  const existingLayout = document.nodes.find(
    (candidate) => candidate.id === commit.cardId,
  )?.layout;
  // Both doors the canvas uses to resize a node have to land in the same place.
  const direct = graphCommandsFromCellResize(commit, existingLayout);
  const viaDocument = graphCommandsFromCellResizeForDocument(document, commit);
  expect(viaDocument).toEqual(direct);
  return direct;
}

/** A card box the canvas can hold: whole cells, at least one of each. */
function expectRealCells(card: { widthCells: number; heightCells: number }) {
  expect(Number.isFinite(card.widthCells)).toBe(true);
  expect(Number.isFinite(card.heightCells)).toBe(true);
  expect(card.widthCells).toBeGreaterThan(0);
  expect(card.heightCells).toBeGreaterThan(0);
}

/** For a card whose box *is* the layout the schema validates. */
function expectBoxWithinSchema(kind: CellCardKind, card: CellCardModel): void {
  const { schema, width, height } = KIND_SCHEMA[kind];
  expectRealCells(card);
  expectWithin(card.widthCells * CELL_SIZE, numericBounds(schema, width));
  expectWithin(card.heightCells * CELL_SIZE, numericBounds(schema, height));
}

describe("cell adapter resize bounds match OpenAPI layout contracts", () => {
  it("bounds every card kind inside the schema that validates its layout", () => {
    const document = scene();
    expect(CARD_KINDS).toHaveLength(5);
    for (const kind of CARD_KINDS) {
      const bounds = cardOfKind(document, kind).resizeBounds;
      assert(bounds, `the ${kind} card offers no resize bounds`);
      const { schema, width, height } = KIND_SCHEMA[kind];
      expectWithin(
        bounds.minWidthCells * CELL_SIZE,
        numericBounds(schema, width),
      );
      expectWithin(
        (bounds.maxWidthCells ?? bounds.minWidthCells) * CELL_SIZE,
        numericBounds(schema, width),
      );
      expectWithin(
        bounds.minHeightCells * CELL_SIZE,
        numericBounds(schema, height),
      );
      expectWithin(
        (bounds.maxHeightCells ?? bounds.minHeightCells) * CELL_SIZE,
        numericBounds(schema, height),
      );
    }
  });

  it.each(["operator", "collection"] as const)(
    "clamps an extreme %s resize into GraphNodeLayout and back",
    (kind) => {
      const document = scene();
      const cardId = kind === "operator" ? "node" : "collection";
      const bounds = cardOfKind(document, kind).resizeBounds;
      assert(bounds);
      const appendixBounds = numericBounds(
        "GraphNodeLayout",
        "appendix_height",
      );

      for (const cells of commitsWithin(bounds)) {
        const commands = resizeCommands(document, { cardId, ...cells });
        const [command]: GraphCommand[] = commands;
        assert(command?.kind === "update_node_layout");
        const layout = command.layout;
        assert(layout);
        expectWithin(layout.width!, numericBounds("GraphNodeLayout", "width"));
        expectWithin(
          layout.body_height!,
          numericBounds("GraphNodeLayout", "body_height"),
        );
        if (layout.appendix_height !== null) {
          expectWithin(layout.appendix_height!, appendixBounds);
        }

        const roundTripped = cardOfKind(
          commands.reduce(applyGraphCommandNormalized, document),
          kind,
        );
        expect(roundTripped.id).toBe(cardId);
        expectRealCells(roundTripped);
        // A resize never leaves a card under the floor the canvas offered it.
        expect(roundTripped.widthCells).toBeGreaterThanOrEqual(
          bounds.minWidthCells,
        );
        expect(roundTripped.heightCells).toBeGreaterThanOrEqual(
          bounds.minHeightCells,
        );
      }
    },
  );

  it("clamps an extreme agent resize into GraphAgent and back", () => {
    const document = scene();
    const bounds = cardOfKind(document, "agent").resizeBounds;
    assert(bounds);

    for (const cells of commitsWithin(bounds)) {
      const commands = graphCommandsFromCellResizeForDocument(document, {
        cardId: "agent",
        ...cells,
      });
      const [command]: GraphCommand[] = commands;
      assert(command?.kind === "configure_agent");
      expectWithin(command.agent.width, numericBounds("GraphAgent", "width"));
      expectWithin(command.agent.height, numericBounds("GraphAgent", "height"));

      const updated = commands.reduce(applyGraphCommandNormalized, document);
      expectBoxWithinSchema("agent", cardOfKind(updated, "agent"));
    }
  });

  it.each(["artifact", "annotation"] as const)(
    "sends no node layout for an %s resize and keeps its own range legal",
    (kind) => {
      const document = scene();
      const cardId = kind === "artifact" ? "viewer" : "note";
      const bounds = cardOfKind(document, kind).resizeBounds;
      assert(bounds);
      // These cards live in the presentation, not in a node layout, so the node
      // commands must stay silent rather than write a layout no one reads.
      expect(
        graphCommandsFromCellResizeForDocument(document, {
          cardId,
          widthCells: bounds.maxWidthCells ?? bounds.minWidthCells,
          heightCells: bounds.maxHeightCells ?? bounds.minHeightCells,
        }),
      ).toEqual([]);

      // What the canvas can drag one of these cards to is what it saves back,
      // so the scene is read with each corner of its own range applied to it.
      for (const saved of [
        {
          width: bounds.minWidthCells * CELL_SIZE,
          height: bounds.minHeightCells * CELL_SIZE,
        },
        {
          width: (bounds.maxWidthCells ?? bounds.minWidthCells) * CELL_SIZE,
          height: (bounds.maxHeightCells ?? bounds.minHeightCells) * CELL_SIZE,
        },
      ]) {
        const graph = readScene(
          document,
          presentationSavedAt(kind, saved.width, saved.height),
        );
        expectBoxWithinSchema(kind, cardById(graph.cards, cardId));
      }
    },
  );

  it("keeps a measured image footprint inside GraphPresentationViewerLayout", () => {
    const widthBounds = numericBounds("GraphPresentationViewerLayout", "width");
    const bodyBounds = numericBounds(
      "GraphPresentationViewerLayout",
      "body_height",
    );
    const naturals = [
      null,
      { width: 1, height: 1 },
      { width: 1, height: 100_000 },
      { width: 100_000, height: 1 },
      { width: 1920, height: 1080 },
      { width: 1200, height: 1600 },
    ];
    const layouts = [
      null,
      { width: 0, body_height: 0 },
      { width: 1, body_height: 1 },
      { width: 999_999, body_height: 999_999 },
      { width: 1200, body_height: null },
      { width: null, body_height: 1200 },
    ];

    for (const natural of naturals) {
      for (const layout of layouts) {
        const cells = cellArtifactImageCells(natural, layout);
        expectRealCells(cells);
        expectWithin(cells.widthCells * CELL_SIZE, widthBounds);
        expectWithin(cells.heightCells * CELL_SIZE, bodyBounds);
      }
    }
  });
});

/** The scene's one card of `kind`, saved at exactly these pixel dimensions. */
function presentationSavedAt(
  kind: "artifact" | "annotation",
  width: number,
  height: number,
): Presentation {
  if (kind === "artifact") {
    return {
      ...SCENE_PRESENTATION,
      viewers: SCENE_PRESENTATION.viewers.map((viewer) => ({
        ...viewer,
        layout: { width, body_height: height, appendix_height: null },
      })),
    };
  }
  return {
    ...SCENE_PRESENTATION,
    annotations: SCENE_PRESENTATION.annotations.map((annotation) => ({
      ...annotation,
      layout: { width, height },
    })),
  };
}
