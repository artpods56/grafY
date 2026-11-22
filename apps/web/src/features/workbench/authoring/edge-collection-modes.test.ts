import { describe, expect, it } from "vitest";

import type { NodeRegistry, NodeSpec, Port, SavedGraphOrigin } from "@/lib/api";
import {
  collectionModeRepairCommands,
  collectionModesToRepair,
  foldCollectionModeRepairs,
  originModesToRepair,
  type CollectionModeConnection,
  type CollectionModeOrigin,
  type CollectionModeStep,
} from "./edge-collection-modes";
import {
  authoredGraphDocument,
  createSavedGraphRequest,
  type AuthoredGraphDocument,
} from "./graph-document";

function port(
  direction: Port["direction"],
  name: string,
  shape: Port["shape"],
  overrides: Partial<Port> = {},
): Port {
  return {
    accepted_shapes: [shape],
    direction,
    instance_plugs: false,
    kind: "artifact",
    name,
    required: true,
    shape,
    variadic: false,
    ...overrides,
  };
}

/**
 * `sequence` offers a page per item; `reader` takes a page and a reader and
 * offers a reading; `boxes` paints a reading onto a page; `viewer` shows a page.
 */
const STEPS: Record<string, CollectionModeStep> = {
  sequence: {
    inputs: [],
    outputs: [port("output", "items", "many")],
  },
  reader: {
    inputs: [
      port("input", "document", "one"),
      port("input", "reader", "one", { kind: "service" }),
    ],
    outputs: [port("output", "markdown", "one")],
  },
  boxes: {
    inputs: [port("input", "image", "one"), port("input", "regions", "one")],
    outputs: [port("output", "image", "one")],
  },
  viewer: {
    inputs: [port("input", "image", "one")],
    outputs: [],
  },
};

const resolveStep = (nodeId: string): CollectionModeStep | null =>
  STEPS[nodeId] ?? null;

function step(id: string): CollectionModeStep {
  const ports = STEPS[id];
  if (!ports) throw new Error(`step fixture ${id} is missing`);
  return ports;
}

function edge(
  id: string,
  fromNode: string,
  fromPort: string,
  toNode: string,
  toPort: string,
  collectionMode: CollectionModeConnection["collection_mode"],
): CollectionModeConnection {
  return {
    id,
    from_node: fromNode,
    from_port: fromPort,
    to_node: toNode,
    to_port: toPort,
    collection_mode: collectionMode,
  };
}

describe("collection modes the graph leaves behind", () => {
  it("keeps a mode the step's own map connection asks for", () => {
    const repairs = collectionModesToRepair(
      [
        edge("feed", "sequence", "items", "reader", "document", "map"),
        edge("reading", "reader", "markdown", "boxes", "regions", "map"),
      ],
      [],
      resolveStep,
    );

    expect([...repairs]).toEqual([]);
  });

  it("turns a connection off the list once its step no longer runs per item", () => {
    // The OCR step lost its sequence feed: it runs once, so its reading is one
    // value and the connection carrying it cannot ask for a list.
    const repairs = collectionModesToRepair(
      [edge("reading", "reader", "markdown", "boxes", "regions", "map")],
      [],
      resolveStep,
    );

    expect([...repairs]).toEqual([["reading", "direct"]]);
  });

  it("settles a chain of steps in one call", () => {
    // Repairing the first connection unmaps the step it feeds, which moves the
    // mode of the connection after it too.
    const repairs = collectionModesToRepair(
      [
        edge("a", "reader", "markdown", "boxes", "regions", "map"),
        edge("b", "boxes", "image", "viewer", "image", "map"),
      ],
      [],
      resolveStep,
    );

    expect([...repairs].sort()).toEqual([
      ["a", "direct"],
      ["b", "direct"],
    ]);
  });

  it("asks for the list a step running per item offers", () => {
    // A map feed appeared on the step, so a whole reading is now a sequence and
    // the connection after it cannot carry it as one value.
    const repairs = collectionModesToRepair(
      [
        edge("feed", "sequence", "items", "reader", "document", "map"),
        edge("reading", "reader", "markdown", "boxes", "regions", "direct"),
      ],
      [],
      resolveStep,
    );

    expect([...repairs]).toEqual([["reading", "map"]]);
  });

  it("leaves a mode no mappedness of the step could have carried", () => {
    // `sequence` has no input, so it never runs per item: this map was not left
    // behind by an edit, it disagrees with the node types it names.
    const repairs = collectionModesToRepair(
      [edge("feed", "sequence", "items", "boxes", "image", "map")],
      [],
      (nodeId) =>
        nodeId === "sequence"
          ? { inputs: [], outputs: [port("output", "items", "one")] }
          : resolveStep(nodeId),
    );

    expect([...repairs]).toEqual([]);
  });

  it("leaves a connection whose two ports do not fit at all", () => {
    const repairs = collectionModesToRepair(
      [edge("paint", "reader", "markdown", "boxes", "image", "direct")],
      [],
      resolveStep,
    );

    expect([...repairs]).toEqual([]);
  });

  it("leaves the choice between two map drivers of one input to the reader", () => {
    const repairs = collectionModesToRepair(
      [
        edge("first", "sequence", "items", "reader", "document", "map"),
        edge("second", "sequence", "items", "reader", "document", "map"),
        edge("reading", "reader", "markdown", "boxes", "regions", "map"),
      ],
      [],
      resolveStep,
    );

    expect([...repairs]).toEqual([]);
  });

  it("counts a map origin as a step running per item", () => {
    const origins: Pick<SavedGraphOrigin, "to_node" | "collection_mode">[] = [
      { to_node: "reader", collection_mode: "map" },
    ];

    expect([...collectionModesToRepair([], origins, resolveStep)]).toEqual([]);
    expect([
      ...collectionModesToRepair(
        [edge("reading", "reader", "markdown", "boxes", "regions", "map")],
        origins,
        resolveStep,
      ),
    ]).toEqual([]);
  });

  it("leaves a connection whose step is out of the registry", () => {
    const repairs = collectionModesToRepair(
      [edge("gone", "retired", "markdown", "boxes", "regions", "map")],
      [],
      resolveStep,
    );

    expect([...repairs]).toEqual([]);
  });

  it("propagates map across origins and downstream edges when a single-item origin becomes a sequence", () => {
    const sequenceValue: SavedGraphOrigin["value"] = {
      artifact_type: "file.jpeg",
      schema_version: 1,
      item_refs: [
        {
          artifact_id: "scan-1",
          artifact_type: "file.jpeg",
          schema_version: 1,
        },
        {
          artifact_id: "scan-2",
          artifact_type: "file.jpeg",
          schema_version: 1,
        },
      ],
      ordered: true,
      index_key: "order_index",
      sequence_id: "seq-1",
    };
    const origins: CollectionModeOrigin[] = [
      {
        id: "ocr-scan",
        to_node: "reader",
        to_port: "document",
        value: sequenceValue,
        collection_mode: "direct",
      },
      {
        id: "boxes-image",
        to_node: "boxes",
        to_port: "image",
        value: sequenceValue,
        collection_mode: "direct",
      },
    ];
    const edges = [
      edge("reading", "reader", "markdown", "boxes", "regions", "direct"),
      edge("painted", "boxes", "image", "viewer", "image", "direct"),
    ];

    expect([...originModesToRepair(edges, origins, resolveStep)]).toEqual([
      ["ocr-scan", "map"],
      ["boxes-image", "map"],
    ]);
    expect([...collectionModesToRepair(edges, origins, resolveStep)]).toEqual([
      ["reading", "map"],
      ["painted", "map"],
    ]);
  });

  it("reverts origins and downstream edges to direct when a sequence origin is unstacked to one item", () => {
    const singleValue: SavedGraphOrigin["value"] = {
      artifact_id: "scan-1",
      artifact_type: "file.jpeg",
      schema_version: 1,
    };
    const origins: CollectionModeOrigin[] = [
      {
        id: "ocr-scan",
        to_node: "reader",
        to_port: "document",
        value: singleValue,
        collection_mode: "map",
      },
      {
        id: "boxes-image",
        to_node: "boxes",
        to_port: "image",
        value: singleValue,
        collection_mode: "map",
      },
    ];
    const edges = [
      edge("reading", "reader", "markdown", "boxes", "regions", "map"),
      edge("painted", "boxes", "image", "viewer", "image", "map"),
    ];

    expect([...originModesToRepair(edges, origins, resolveStep)]).toEqual([
      ["ocr-scan", "direct"],
      ["boxes-image", "direct"],
    ]);
    expect([...collectionModesToRepair(edges, origins, resolveStep)]).toEqual([
      ["reading", "direct"],
      ["painted", "direct"],
    ]);
  });
});

function spec(operatorId: string, step: CollectionModeStep): NodeSpec {
  return {
    operator_id: operatorId,
    operator_version: 1,
    plugin_slug: "test",
    origin: "builtin",
    title: operatorId,
    description: operatorId,
    catalog_visible: true,
    runnable: true,
    config_schema: {},
    input_schema: {},
    output_schema: {},
    inputs: step.inputs,
    outputs: step.outputs,
  };
}

const REGISTRY: NodeRegistry = {
  plugins: [],
  artifact_types: [],
  artifact_conversions: [],
  nodes: [
    spec("test.sequence", step("sequence")),
    spec("test.reader", step("reader")),
    spec("test.boxes", step("boxes")),
  ],
};

function documentOf(
  edges: AuthoredGraphDocument["edges"],
  origins: AuthoredGraphDocument["origins"] = [],
): AuthoredGraphDocument {
  return authoredGraphDocument(
    createSavedGraphRequest({
      name: "Main",
      nodes: [
        {
          id: "sequence",
          kind: "builtin",
          operator_id: "test.sequence",
          operator_version: 1,
          config: {},
          input_plugs: [],
          artifact_type_bindings: [],
          position: { x: 0, y: 0 },
        },
        {
          id: "reader",
          kind: "builtin",
          operator_id: "test.reader",
          operator_version: 1,
          config: {},
          input_plugs: [],
          artifact_type_bindings: [],
          position: { x: 300, y: 0 },
        },
        {
          id: "boxes",
          kind: "builtin",
          operator_id: "test.boxes",
          operator_version: 1,
          config: {},
          input_plugs: [],
          artifact_type_bindings: [],
          position: { x: 600, y: 0 },
        },
      ],
      edges,
      origins,
      agents: [],
    }),
  );
}

const savedEdge = (
  id: string,
  fromNode: string,
  fromPort: string,
  toNode: string,
  toPort: string,
  collectionMode: CollectionModeConnection["collection_mode"],
) => ({
  id,
  enabled: true,
  from_node: fromNode,
  from_port: fromPort,
  to_node: toNode,
  to_port: toPort,
  to_plug: null,
  collection_mode: collectionMode,
  conversion_path: [],
  route_offset: null,
});

describe("collection mode repairs as authored commands", () => {
  it("rewrites the modes an edit left behind", () => {
    const document = documentOf([
      savedEdge("reading", "reader", "markdown", "boxes", "regions", "map"),
    ]);

    expect(collectionModeRepairCommands(document, REGISTRY)).toEqual([
      {
        kind: "update_edge",
        edge_id: "reading",
        update: { collection_mode: "direct" },
      },
    ]);
  });

  it("says nothing when the document already agrees with its steps", () => {
    const document = documentOf([
      savedEdge("feed", "sequence", "items", "reader", "document", "map"),
      savedEdge("reading", "reader", "markdown", "boxes", "regions", "map"),
    ]);

    expect(collectionModeRepairCommands(document, REGISTRY)).toEqual([]);
  });

  it("says nothing until the node types are known", () => {
    const document = documentOf([
      savedEdge("reading", "reader", "markdown", "boxes", "regions", "map"),
    ]);

    expect(collectionModeRepairCommands(document, null)).toEqual([]);
  });

  it("emits origin and downstream edge repairs and folds them into the origin update batch", () => {
    const sequenceValue: SavedGraphOrigin["value"] = {
      artifact_type: "file.jpeg",
      schema_version: 1,
      item_refs: [
        {
          artifact_id: "scan-1",
          artifact_type: "file.jpeg",
          schema_version: 1,
        },
        {
          artifact_id: "scan-2",
          artifact_type: "file.jpeg",
          schema_version: 1,
        },
      ],
      ordered: true,
      index_key: "order_index",
      sequence_id: "seq-1",
    };
    const document = documentOf(
      [
        savedEdge(
          "reading",
          "reader",
          "markdown",
          "boxes",
          "regions",
          "direct",
        ),
      ],
      [
        {
          id: "ocr-scan",
          to_node: "reader",
          to_port: "document",
          to_plug: null,
          value: sequenceValue,
          source_card_ids: ["card-a", "card-a"],
          collection_mode: "direct",
          conversion_path: [],
        },
        {
          id: "boxes-image",
          to_node: "boxes",
          to_port: "image",
          to_plug: null,
          value: sequenceValue,
          source_card_ids: ["card-a", "card-a"],
          collection_mode: "direct",
          conversion_path: [],
        },
      ],
    );

    const repairs = collectionModeRepairCommands(document, REGISTRY);
    expect(repairs).toEqual([
      {
        kind: "update_origin",
        origin_id: "ocr-scan",
        update: { collection_mode: "map" },
      },
      {
        kind: "update_origin",
        origin_id: "boxes-image",
        update: { collection_mode: "map" },
      },
      {
        kind: "update_edge",
        edge_id: "reading",
        update: { collection_mode: "map" },
      },
    ]);

    const folded = foldCollectionModeRepairs(
      [
        {
          kind: "update_origin",
          origin_id: "ocr-scan",
          update: {
            value: sequenceValue,
            source_card_ids: ["card-a", "card-a"],
          },
        },
        {
          kind: "update_origin",
          origin_id: "boxes-image",
          update: {
            value: sequenceValue,
            source_card_ids: ["card-a", "card-a"],
          },
        },
      ],
      repairs,
    );
    expect(folded).toEqual([
      {
        kind: "update_origin",
        origin_id: "ocr-scan",
        update: {
          value: sequenceValue,
          source_card_ids: ["card-a", "card-a"],
          collection_mode: "map",
        },
      },
      {
        kind: "update_origin",
        origin_id: "boxes-image",
        update: {
          value: sequenceValue,
          source_card_ids: ["card-a", "card-a"],
          collection_mode: "map",
        },
      },
      {
        kind: "update_edge",
        edge_id: "reading",
        update: { collection_mode: "map" },
      },
    ]);
  });
});
