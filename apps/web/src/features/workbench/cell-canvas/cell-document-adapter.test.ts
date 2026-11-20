import { describe, expect, it } from "vitest";

import type {
  NodeRegistry,
  NodeSpec,
  Port,
  SavedGraphDocument,
} from "@/lib/api";

import {
  applyGraphCommandNormalized,
  authoredGraphDocument,
  createGraphDraft,
  type AuthoredGraphDocument,
  type AuthoredGraphEdge,
  type AuthoredGraphNode,
  type AuthoredGraphOrigin,
} from "../model/graph-document";
import {
  cellGraphFromAuthoredDocument,
  cellOriginFromWorld,
  graphCommandsFromCellConnect,
  graphCommandsFromCellDelete,
  graphCommandsFromCellMoves,
  graphCommandsFromCellResize,
  snapPixelsToCell,
} from "./cell-document-adapter";

const textType = { id: "scalar.text", schema_version: 2 };

function port(name: string, overrides: Partial<Port> = {}): Port {
  return {
    name,
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

const variableInput = port("incoming", {
  title: "Incoming",
  artifact_type: null,
  artifact_type_variable: "T",
  instance_plugs: true,
  accepted_shapes: ["many"],
  shape: "many",
  required: false,
});
const baseSpec: NodeSpec = {
  operator_id: "test.source",
  operator_version: 2,
  title: "Source v2",
  description: "",
  plugin_slug: "test",
  catalog_visible: true,
  origin: "builtin",
  runnable: true,
  input_schema: {},
  output_schema: {},
  inputs: [
    variableInput,
    port("trigger"),
    port("more", { ...variableInput, name: "more", title: null }),
  ],
  outputs: [port("result", { title: "Result", direction: "output" })],
  config_schema: {
    properties: {
      caption: { type: "string", title: "Caption" },
      mode: { type: "string", enum: ["fast", "slow"] },
      enabled: { type: "boolean" },
      limit: { type: "integer" },
      body: { type: "string", format: "textarea" },
    },
  },
};
const registry: NodeRegistry = {
  nodes: [
    { ...baseSpec, operator_version: 1, title: "Source v1" },
    baseSpec,
    {
      ...baseSpec,
      operator_id: "sequence.collect",
      operator_version: 1,
      title: "Collect",
      config_schema: {},
      inputs: [
        port("items", {
          instance_plugs: true,
          artifact_type: null,
          artifact_type_variable: "T",
        }),
      ],
      outputs: [
        port("sequence", {
          direction: "output",
          shape: "many",
          artifact_type: null,
          artifact_type_variable: "T",
        }),
      ],
    },
  ],
  artifact_types: [],
  artifact_conversions: [],
  plugins: [],
};

const source: AuthoredGraphNode = {
  id: "source",
  kind: "builtin",
  operator_id: "test.source",
  operator_version: 2,
  position: { x: -1, y: 76 },
  layout: { width: 324, body_height: 551, appendix_height: 101 },
  artifact_type_bindings: [{ variable: "T", artifact_type: textType }],
  input_plugs: [
    { port: "incoming", id: "plug-a" },
    { port: "more", id: "more-a" },
    { port: "incoming", id: "plug-b" },
  ],
  config: { caption: "sample", mode: "slow", body: "line one\nline two" },
};
const collection: AuthoredGraphNode = {
  ...source,
  id: "collection",
  operator_id: "sequence.collect",
  operator_version: 9,
  position: { x: 401, y: -76 },
  layout: null,
  config: {},
  input_plugs: [
    { port: "items", id: "library" },
    { port: "items", id: "wired" },
    { port: "items", id: "spare" },
  ],
};
const edge: AuthoredGraphEdge = {
  id: "edge",
  from_node: "source",
  from_port: "result",
  to_node: "collection",
  to_port: "items",
  to_plug: "wired",
  enabled: false,
  collection_mode: "direct",
  projection: { path: ["data", "title"] },
  conversion_path: [
    { id: "to-text", version: 1 },
    { id: "normalize", version: 2 },
  ],
  route_offset: null,
};
const libraryOrigin: AuthoredGraphOrigin = {
  id: "library-origin",
  to_node: "collection",
  to_port: "items",
  to_plug: "library",
  value: {
    artifact_id: "artifact-id",
    artifact_type: textType.id,
    schema_version: 2,
  },
  collection_mode: "direct",
  conversion_path: [],
};
const presentation: NonNullable<SavedGraphDocument["presentation"]> = {
  annotations: [
    {
      id: "note",
      kind: "text",
      position: { x: 149, y: -49 },
      layout: { width: 100, height: 50 },
      text: "Read this",
      color: "#B45309",
    },
    {
      id: "frame",
      kind: "ellipse",
      position: { x: 201, y: 147 },
      layout: { width: 260, height: 243 },
      text: "",
      color: "#010203",
    },
  ],
  viewers: [],
  links: [],
  bindings: [],
};

function savedDocument() {
  return createGraphDraft(
    {
      name: "Demo graph",
      nodes: [source, collection],
      edges: [
        edge,
        {
          ...edge,
          id: "back",
          from_node: "collection",
          from_port: "sequence",
          to_node: "source",
          to_port: "incoming",
          to_plug: "plug-a",
          projection: { path: [] },
          conversion_path: [],
        },
      ],
      origins: [
        libraryOrigin,
        {
          ...libraryOrigin,
          id: "operator-origin",
          to_node: "source",
          to_port: "more",
          to_plug: "more-a",
        },
      ],
      agents: [
        {
          id: "agent",
          name: "Review",
          instructions: "Check the result",
          model: {
            kind: "custom",
            model: "example-model",
            endpoint: "https://example.test",
          },
          width: 401,
          height: 101,
          position: { x: -151, y: 99 },
          context: [],
          tools: [
            {
              id: "tool",
              name: "inspect",
              node_id: "source",
              description: "",
              filled_ports: [],
              returned_ports: ["result"],
            },
          ],
        },
        {
          id: "default-agent",
          name: "",
          instructions: "",
          width: 0,
          height: 0,
          context: [],
          tools: [],
        },
      ],
    },
    presentation,
  );
}

describe("cell document adapter", () => {
  it("rounds world positions to whole cells and returns positive zero near the origin", () => {
    expect(snapPixelsToCell(25)).toBe(1);
    expect(snapPixelsToCell(24)).toBe(0);
    expect(snapPixelsToCell(-26)).toBe(-1);
    expect(snapPixelsToCell(-75)).toBe(-1);
    expect(Object.is(snapPixelsToCell(-1), 0)).toBe(true);
    expect(cellOriginFromWorld({ x: 126, y: -76 })).toEqual({
      col: 3,
      row: -2,
    });
  });

  it("hydrates a saved graph with exact and fallback versions, plug wiring, and card data", () => {
    const saved = savedDocument();
    const document = authoredGraphDocument(saved);
    const { graph, surfaceById } = cellGraphFromAuthoredDocument(
      document,
      registry,
      {
        presentation: saved.document.presentation,
      },
    );
    const [operator, collect, agent, defaultAgent, note, frame] = graph.cards;

    expect(operator).toEqual({
      id: "source",
      title: "Source v2",
      subtitle: "test.source",
      kind: "operator",
      col: 0,
      row: 2,
      widthCells: 6,
      heightCells: 14,
      resizable: true,
      resizeBounds: {
        minWidthCells: 4,
        maxWidthCells: 24,
        minHeightCells: 5,
        maxHeightCells: 30,
      },
      ports: [
        {
          id: "trigger",
          name: "trigger",
          direction: "input",
          rowOffset: 1,
          artifactTypeId: "scalar.text",
          shape: "one",
          required: true,
        },
        {
          id: "result",
          name: "Result",
          direction: "output",
          rowOffset: 1,
          artifactTypeId: "scalar.text",
          shape: "one",
          required: true,
        },
        {
          id: "incoming::plug-a",
          name: "Incoming #1",
          direction: "input",
          rowOffset: 2,
          artifactTypeId: "scalar.text",
          shape: "many",
          required: false,
        },
        {
          id: "incoming::plug-b",
          name: "Incoming #2",
          direction: "input",
          rowOffset: 3,
          artifactTypeId: "scalar.text",
          shape: "many",
          required: false,
        },
        {
          id: "more::more-a",
          name: "more #1",
          direction: "input",
          rowOffset: 4,
          artifactTypeId: "scalar.text",
          shape: "many",
          required: false,
        },
      ],
    });
    expect(surfaceById.source).toMatchObject({
      kind: "operator",
      configFields: [
        {
          id: "caption",
          label: "Caption",
          kind: "text",
          value: "sample",
          span: 1,
          denseRows: 2,
        },
        {
          id: "mode",
          label: "mode",
          kind: "select",
          value: "slow",
          span: 1,
          denseRows: 2,
          options: [
            { value: "fast", label: "fast" },
            { value: "slow", label: "slow" },
          ],
        },
        { id: "enabled", kind: "toggle", value: false, span: 1, denseRows: 2 },
        { id: "limit", kind: "number", value: 0, span: 1, denseRows: 2 },
        {
          id: "body",
          kind: "multiline",
          value: "line one\nline two",
          span: 2,
          denseRows: 4,
        },
      ],
      instancePlugGroups: [
        {
          portName: "incoming",
          title: "Incoming",
          artifactTypeId: "scalar.text",
          shape: "many",
          startRowOffset: 2,
          canAdd: true,
          plugs: [
            { plugId: "plug-a", label: "Incoming #1", connected: true },
            { plugId: "plug-b", label: "Incoming #2", connected: false },
          ],
        },
        {
          portName: "more",
          title: "more",
          artifactTypeId: "scalar.text",
          shape: "many",
          startRowOffset: 4,
          canAdd: true,
          plugs: [{ plugId: "more-a", label: "more #1", connected: true }],
        },
      ],
      appendix: { heightCells: 3 },
    });
    expect(collect).toMatchObject({
      id: "collection",
      title: "Collect",
      kind: "collection",
      col: 8,
      row: -2,
      widthCells: 5,
      heightCells: 5,
    });
    expect(collect?.ports.map((item) => [item.id, item.rowOffset])).toEqual([
      ["sequence", 1],
      ["items::library", 2],
      ["items::wired", 3],
      ["items::spare", 4],
    ]);
    expect(surfaceById.collection).toEqual({
      kind: "collection",
      artifactTypeId: "scalar.text",
      typeLabel: "scalar.text@2",
      members: [
        {
          id: "library",
          label: "scalar.text@2",
          artifactTypeId: "scalar.text",
          typeLabel: "scalar.text@2",
        },
        {
          id: "wired",
          label: "Source v2 → Result",
          artifactTypeId: "scalar.text",
          typeLabel: "scalar.text@2",
        },
      ],
      showSparePlug: true,
    });
    expect(agent).toMatchObject({
      id: "agent",
      kind: "agent",
      title: "Review",
      subtitle: "example-model",
      col: -3,
      row: 2,
      widthCells: 8,
      heightCells: 4,
      ports: [],
    });
    expect(surfaceById.agent).toEqual({
      kind: "agent",
      modelLabel: "example-model",
      linkedToolCount: 1,
      agentStatus: "idle",
      lastMessageSnippet: "Check the result",
    });
    expect(defaultAgent).toMatchObject({
      title: "Agent",
      subtitle: "Deployment model",
      col: 0,
      row: 0,
      widthCells: 7,
      heightCells: 4,
    });

    expect(note).toMatchObject({
      id: "note",
      kind: "annotation",
      title: "Note",
      col: 3,
      row: -1,
      widthCells: 3,
      heightCells: 2,
      resizable: true,
    });
    expect(surfaceById.note).toEqual({
      kind: "annotation",
      variant: "note",
      color: "amber",
      bodyText: "Read this",
      layer: "under-cards",
    });
    expect(frame).toMatchObject({
      title: "Frame",
      subtitle: "ellipse",
      widthCells: 5,
      heightCells: 5,
    });
    expect(surfaceById.frame).toMatchObject({
      variant: "frame",
      color: "slate",
    });
    expect(graph.pipes).toEqual([
      {
        id: "edge",
        sourceCardId: "source",
        sourcePortId: "result",
        targetCardId: "collection",
        targetPortId: "items::wired",
        enabled: false,
        projectionLabel: "data.title",
        conversionLabel: "2 conv",
      },
      {
        id: "back",
        sourceCardId: "collection",
        sourcePortId: "sequence",
        targetCardId: "source",
        targetPortId: "incoming::plug-a",
        enabled: false,
        projectionLabel: null,
        conversionLabel: null,
      },
    ]);
    expect(createGraphDraft(document, saved.document.presentation)).toEqual(
      saved,
    );
    expect(
      cellGraphFromAuthoredDocument(document, registry).graph.cards.map(
        ({ id }) => id,
      ),
    ).toEqual(["source", "collection", "agent", "default-agent"]);
  });

  it("uses packed shelf height and the minimum appendix size when the saved body is too short", () => {
    const document = authoredGraphDocument(savedDocument());
    const result = cellGraphFromAuthoredDocument(
      {
        ...document,
        nodes: [
          {
            ...source,
            layout: { width: 149, body_height: 10, appendix_height: 1 },
            artifact_type_bindings: [],
          },
        ],
      },
      registry,
      { presentation: null },
    );
    expect(result.graph.cards[0]).toMatchObject({
      widthCells: 4,
      heightCells: 11,
    });
    expect(
      result.graph.cards[0]?.ports.find(({ id }) => id === "incoming::plug-a"),
    ).toMatchObject({ artifactTypeId: "T" });
    expect(result.surfaceById.source).toMatchObject({
      appendix: { heightCells: 2 },
    });
  });

  it("hydrates an unavailable collection by its canonical operator id", () => {
    const document = authoredGraphDocument(savedDocument());
    const result = cellGraphFromAuthoredDocument(document, {
      ...registry,
      nodes: [],
    });
    expect(result.graph.cards[0]).toMatchObject({
      title: "test.source",
      kind: "operator",
      ports: [],
    });
    expect(result.graph.cards[1]).toMatchObject({
      kind: "collection",
      widthCells: 5,
    });
    expect(result.surfaceById.collection).toMatchObject({
      kind: "collection",
      showSparePlug: true,
    });
  });

  it("applies one move command and a resize through the normalized graph reducer", () => {
    const document = authoredGraphDocument(savedDocument());
    const moves = graphCommandsFromCellMoves([
      { cardId: "source", col: -2, row: 4 },
      { cardId: "collection", col: 6, row: 3 },
    ]);
    expect(moves).toEqual([
      {
        kind: "move_nodes",
        positions: [
          { node_id: "source", x: -100, y: 200 },
          { node_id: "collection", x: 300, y: 150 },
        ],
      },
    ]);
    const resize = graphCommandsFromCellResize(
      { cardId: "source", widthCells: 10, heightCells: 8 },
      source.layout,
    );
    expect(resize).toEqual([
      {
        kind: "update_node_layout",
        node_id: "source",
        layout: { width: 500, body_height: 400, appendix_height: 101 },
      },
    ]);
    const updated = [...moves, ...resize].reduce(
      applyGraphCommandNormalized,
      document,
    );
    const { graph } = cellGraphFromAuthoredDocument(updated, registry);
    expect(graph.cards[0]).toMatchObject({
      col: -2,
      row: 4,
      widthCells: 10,
      heightCells: 12,
    });
    expect(graph.cards[1]).toMatchObject({ col: 6, row: 3 });
    const withoutAppendix = graphCommandsFromCellResize({
      cardId: "collection",
      widthCells: 5,
      heightCells: 6,
    });
    expect(
      withoutAppendix.reduce(applyGraphCommandNormalized, updated).nodes[1]
        ?.layout,
    ).toEqual({
      width: 250,
      body_height: 300,
      appendix_height: null,
    });
    expect(graphCommandsFromCellMoves([])).toEqual([]);
  });

  it.each([
    { targetPortName: "items::spare", toPort: "items", toPlug: "spare" },
    {
      targetPortName: "items",
      targetPlugId: "spare",
      toPort: "items",
      toPlug: "spare",
    },
    {
      targetPortName: "trigger",
      targetPlugId: null,
      toPort: "trigger",
      toPlug: null,
    },
    { targetPortName: "trigger", toPort: "trigger", toPlug: null },
  ])(
    "adds a normalized edge for target $targetPortName and plug $targetPlugId",
    ({ targetPortName, targetPlugId, toPort, toPlug }) => {
      const document = authoredGraphDocument(savedDocument());
      const commands = graphCommandsFromCellConnect({
        edgeId: "new",
        sourceCardId: toPlug ? "source" : "collection",
        sourcePortName: toPlug ? "result" : "sequence",
        targetCardId: toPlug ? "collection" : "source",
        targetPortName,
        targetPlugId,
      });
      const expected: AuthoredGraphEdge = {
        id: "new",
        from_node: toPlug ? "source" : "collection",
        from_port: toPlug ? "result" : "sequence",
        to_node: toPlug ? "collection" : "source",
        to_port: toPort,
        to_plug: toPlug,
        enabled: true,
        collection_mode: "direct",
        projection: null,
        conversion_path: [],
        route_offset: null,
      };
      expect(commands).toEqual([{ kind: "add_edge", edge: expected }]);
      const updated: AuthoredGraphDocument = commands.reduce(
        applyGraphCommandNormalized,
        document,
      );
      expect(updated.edges.at(-1)).toEqual(expected);
      expect(
        cellGraphFromAuthoredDocument(updated, registry).graph.pipes.at(-1)
          ?.targetPortId,
      ).toBe(toPlug ? "items::spare" : "trigger");
    },
  );

  it("removes selected edges before nodes and skips empty commands", () => {
    const document = authoredGraphDocument(savedDocument());
    const commands = graphCommandsFromCellDelete(["collection"], ["edge"]);
    expect(commands).toEqual([
      { kind: "remove_edges", edge_ids: ["edge"] },
      { kind: "remove_nodes", node_ids: ["collection"] },
    ]);
    const updated = commands.reduce(applyGraphCommandNormalized, document);
    expect(updated.nodes.map(({ id }) => id)).toEqual(["source"]);
    expect(updated.edges).toEqual([]);
    expect(updated.origins.map(({ id }) => id)).toEqual(["operator-origin"]);
    expect(graphCommandsFromCellDelete([], ["edge"])).toEqual([
      { kind: "remove_edges", edge_ids: ["edge"] },
    ]);
    expect(graphCommandsFromCellDelete(["collection"], [])).toEqual([
      { kind: "remove_nodes", node_ids: ["collection"] },
    ]);
    expect(graphCommandsFromCellDelete([], [])).toEqual([]);
  });
});
