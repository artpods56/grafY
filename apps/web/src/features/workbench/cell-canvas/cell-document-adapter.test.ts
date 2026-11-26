import { assert, describe, expect, it } from "vitest";

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
} from "../authoring/graph-document";
import {
  annotationHexFromToken,
  cellArtifactImageCells,
  cellGraphFromAuthoredDocument,
  cellOriginFromWorld,
  graphCommandsFromCellAddPlug,
  graphCommandsFromCellConfigChange,
  graphCommandsFromCellConnect,
  graphCommandsFromCellDelete,
  graphCommandsFromCellDeleteForDocument,
  graphCommandsFromCellMoves,
  graphCommandsFromCellMovesForDocument,
  graphCommandsFromCellRemovePlug,
  graphCommandsFromCellResize,
  graphCommandsFromCellResizeForDocument,
  snapPixelsToCell,
} from "./cell-document-adapter";

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
  pack_slugs: [],
  role: "operator",
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
const apiKeyInput = {
  name: "api_key",
  title: "API key",
  description: "Write-only bearer credential for the configured API base URL.",
  config_dependencies: ["base_url"],
  provider_kind: "openai_compatible",
  supports_verification: true,
};
const registry: NodeRegistry = {
  packs: [],
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
    expect(snapPixelsToCell(13)).toBe(1);
    expect(snapPixelsToCell(12)).toBe(0);
    expect(snapPixelsToCell(-13)).toBe(-1);
    expect(snapPixelsToCell(-37)).toBe(-1);
    expect(Object.is(snapPixelsToCell(-1), 0)).toBe(true);
    expect(cellOriginFromWorld({ x: 126, y: -76 })).toEqual({
      col: 5,
      row: -3,
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
      row: 3,
      widthCells: 13,
      heightCells: 27,
      resizable: true,
      resizeBounds: {
        minWidthCells: 11,
        maxWidthCells: 48,
        minHeightCells: 14,
        maxHeightCells: 60,
      },
      ports: [
        {
          id: "trigger",
          name: "trigger",
          direction: "input",
          rowOffset: 2,
          artifactTypeId: "scalar.text",
          shape: "one",
          required: true,
        },
        {
          id: "result",
          name: "Result",
          direction: "output",
          rowOffset: 2,
          artifactTypeId: "scalar.text",
          shape: "one",
          required: true,
        },
        {
          id: "incoming::plug-a",
          name: "Incoming #1",
          direction: "input",
          rowOffset: 4,
          artifactTypeId: "scalar.text",
          shape: "many",
          required: false,
        },
        {
          id: "incoming::plug-b",
          name: "Incoming #2",
          direction: "input",
          rowOffset: 6,
          artifactTypeId: "scalar.text",
          shape: "many",
          required: false,
        },
        {
          id: "more::more-a",
          name: "more #1",
          direction: "input",
          rowOffset: 10,
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
        { id: "enabled", kind: "toggle", value: false, span: 1, denseRows: 1 },
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
          startRowOffset: 4,
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
          startRowOffset: 10,
          canAdd: true,
          plugs: [{ plugId: "more-a", label: "more #1", connected: true }],
        },
      ],
      appendix: { heightCells: 5 },
    });
    expect(collect).toMatchObject({
      id: "collection",
      title: "Collect",
      kind: "collection",
      col: 16,
      row: -3,
      widthCells: 11,
      heightCells: 8,
    });
    expect(collect?.ports.map((item) => [item.id, item.rowOffset])).toEqual([
      ["sequence", 2],
      ["items::library", 2],
      ["items::wired", 4],
      ["items::spare", 6],
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
      sparePlugId: "spare",
    });
    expect(agent).toMatchObject({
      id: "agent",
      kind: "agent",
      title: "Review",
      subtitle: "example-model",
      col: -6,
      row: 4,
      widthCells: 16,
      heightCells: 8,
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
      widthCells: 14,
      heightCells: 8,
    });

    expect(note).toMatchObject({
      id: "note",
      kind: "annotation",
      title: "Note",
      col: 6,
      row: -2,
      widthCells: 6,
      heightCells: 4,
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
      widthCells: 10,
      heightCells: 10,
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
        collectionMode: "direct",
        sourcePortLabel: "result",
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
        collectionMode: "direct",
        sourcePortLabel: "sequence",
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

  it("moves secret inputs off the config band and costs the card no rows", () => {
    const document = {
      ...authoredGraphDocument(savedDocument()),
      nodes: [{ ...source, layout: null }],
    };
    const withoutSecret = cellGraphFromAuthoredDocument(document, registry);
    const withSecret = cellGraphFromAuthoredDocument(document, {
      ...registry,
      nodes: [{ ...baseSpec, secret_inputs: [apiKeyInput] }],
    });
    const baseline = withoutSecret.surfaceById.source;
    const operator = withSecret.surfaceById.source;
    const baselineCard = withoutSecret.graph.cards[0];
    assert(baseline?.kind === "operator" && baseline.configFields);
    assert(operator?.kind === "operator");
    assert(baselineCard);

    expect(operator.configFields).toStrictEqual(baseline.configFields);
    expect(operator.secretInputs).toStrictEqual([
      {
        name: "api_key",
        title: "API key",
        description: apiKeyInput.description,
        state: "unknown",
        // Never saved, so a key has nothing to be bound to yet.
        ready: false,
        revision: 'unsaved:[["base_url",null]]',
      },
    ]);
    expect(baseline.secretInputs).toBeUndefined();
    expect(withSecret.graph.cards[0]?.heightCells).toBe(
      baselineCard.heightCells,
    );
  });

  it("keeps the schema config fields when the operator declares no secret inputs", () => {
    const document = authoredGraphDocument(savedDocument());
    const { surfaceById } = cellGraphFromAuthoredDocument(document, registry);
    const operator = surfaceById.source;
    assert(operator?.kind === "operator");

    expect(operator.configFields?.map(({ id, kind }) => [id, kind])).toEqual([
      ["caption", "text"],
      ["mode", "select"],
      ["enabled", "toggle"],
      ["limit", "number"],
      ["body", "multiline"],
    ]);
  });

  it("never reads a secret out of saved config with the same name", () => {
    const document = {
      ...authoredGraphDocument(savedDocument()),
      nodes: [
        { ...source, config: { ...source.config, api_key: "saved value" } },
      ],
    };
    const { surfaceById } = cellGraphFromAuthoredDocument(document, {
      ...registry,
      nodes: [
        {
          ...baseSpec,
          secret_inputs: [{ ...apiKeyInput, title: "", description: null }],
        },
      ],
    });
    const operator = surfaceById.source;
    assert(operator?.kind === "operator");

    expect(operator.secretInputs).toStrictEqual([
      {
        name: "api_key",
        title: "api key",
        state: "unknown",
        ready: false,
        revision: 'unsaved:[["base_url",null]]',
      },
    ]);
    expect(JSON.stringify(operator.secretInputs)).not.toContain("saved value");
    expect(operator.configFields?.map(({ id }) => id)).not.toContain("api_key");
  });

  it("describes an operator in plain words, falling back to its id", () => {
    const document = authoredGraphDocument(savedDocument());
    const described = cellGraphFromAuthoredDocument(document, {
      ...registry,
      nodes: [{ ...baseSpec, description: "Reads rows from a source." }],
    });
    expect(described.graph.cards[0]?.subtitle).toBe(
      "Reads rows from a source.",
    );
    const bare = cellGraphFromAuthoredDocument(document, registry);
    expect(bare.graph.cards[0]?.subtitle).toBe("test.source");
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
      widthCells: 11,
      heightCells: 26,
    });
    expect(
      result.graph.cards[0]?.ports.find(({ id }) => id === "incoming::plug-a"),
    ).toMatchObject({ artifactTypeId: "T" });
    expect(result.surfaceById.source).toMatchObject({
      appendix: { heightCells: 4 },
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
      widthCells: 11,
    });
    expect(result.surfaceById.collection).toMatchObject({
      kind: "collection",
      showSparePlug: true,
      sparePlugId: "spare",
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
          { node_id: "source", x: -50, y: 100 },
          { node_id: "collection", x: 150, y: 75 },
        ],
      },
    ]);
    const resize = graphCommandsFromCellResize(
      { cardId: "source", widthCells: 20, heightCells: 24 },
      source.layout,
    );
    expect(resize).toEqual([
      {
        kind: "update_node_layout",
        node_id: "source",
        layout: { width: 500, body_height: 600, appendix_height: 120 },
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
      widthCells: 20,
      heightCells: 29,
    });
    expect(graph.cards[1]).toMatchObject({ col: 6, row: 3 });
    const withoutAppendix = graphCommandsFromCellResize({
      cardId: "collection",
      widthCells: 10,
      heightCells: 12,
    });
    expect(
      withoutAppendix.reduce(applyGraphCommandNormalized, updated).nodes[1]
        ?.layout,
    ).toEqual({
      width: 260,
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

  it("applies live nodeRunState, collapsedAppendices, and presentation viewers + links", () => {
    const document = authoredGraphDocument(savedDocument());
    const result = cellGraphFromAuthoredDocument(document, registry, {
      nodeRunState: {
        source: {
          status: "done",
          statusLabel: "42 ms",
          runDisabled: true,
          runDisabledReason:
            "Waiting for recent edits to finish saving before running.",
          appendix: {
            title: "Run output",
            kindBadge: "Text",
            heightCells: 5,
            summaryText: "1 item",
          },
        },
      },
      collapsedAppendices: new Set(["source"]),
      presentation: {
        ...presentation,
        viewers: [
          {
            id: "viewer-1",
            position: { x: 500, y: 50 },
            layout: { width: 200, body_height: 150, appendix_height: null },
            mode: "artifact",
            artifact_ref: {
              artifact_id: "art-1",
              artifact_type: "image.raster",
              schema_version: 1,
            },
          },
        ],
        links: [
          {
            id: "link-1",
            source_node_id: "source",
            source_port_name: "result",
            target_viewer_id: "viewer-1",
            projection: { path: ["preview"] },
            route_offset: null,
          },
        ],
      },
    });

    const sourceCard = result.graph.cards.find((c) => c.id === "source");
    expect(sourceCard?.status).toBe("done");
    expect(result.surfaceById.source).toMatchObject({
      kind: "operator",
      statusLabel: "42 ms",
      runDisabled: true,
      runDisabledReason:
        "Waiting for recent edits to finish saving before running.",
      appendix: { collapsed: true, title: "Run output" },
    });

    const viewerCard = result.graph.cards.find((c) => c.id === "viewer-1");
    expect(viewerCard).toMatchObject({
      id: "viewer-1",
      kind: "artifact",
      col: 20,
      row: 2,
      widthCells: 8,
      heightCells: 6,
    });
    expect(viewerCard?.ports.map((p) => p.id)).toEqual([
      "artifact-viewer-input",
      "artifact-card-output",
    ]);
    expect(result.surfaceById["viewer-1"]).toMatchObject({
      kind: "artifact",
      previewKind: "image",
      artifactTypeId: "image.raster",
    });
    expect(result.graph.pipes.find((p) => p.id === "link-1")).toEqual({
      id: "link-1",
      sourceCardId: "source",
      sourcePortId: "result",
      targetCardId: "viewer-1",
      targetPortId: "artifact-viewer-input",
      enabled: true,
      sourcePortLabel: "result",
      projectionLabel: "preview",
      conversionLabel: null,
    });
  });

  it("extracts service-contract ports, origin pipes, and following-card output ports", () => {
    const providerSpec: NodeSpec = {
      ...baseSpec,
      operator_id: "llm.provider",
      operator_version: 1,
      title: "LLM Provider",
      inputs: [],
      outputs: [
        port("chat_service", {
          title: "Chat",
          kind: "service",
          direction: "output",
          artifact_type: null,
          service_contracts: [{ id: "llm.chat", version: 1 }],
        }),
      ],
    };
    const consumerSpec: NodeSpec = {
      ...baseSpec,
      operator_id: "llm.ask",
      operator_version: 1,
      title: "Ask",
      inputs: [
        port("service", {
          title: "Service",
          kind: "service",
          direction: "input",
          artifact_type: null,
          service_contracts: [{ id: "llm.chat", version: 1 }],
        }),
      ],
      outputs: [],
    };
    const serviceRegistry: NodeRegistry = {
      ...registry,
      nodes: [baseSpec, providerSpec, consumerSpec],
      service_contracts: [
        {
          id: "llm.chat",
          version: 1,
          title: "Chat Model Service",
        },
      ],
    };
    const origin: AuthoredGraphOrigin = {
      id: "origin-1",
      to_node: "source",
      to_port: "incoming",
      to_plug: "plug-a",
      source_card_ids: ["viewer-src"],
      value: {
        artifact_id: "a1",
        artifact_type: textType.id,
        schema_version: textType.schema_version,
      },
      collection_mode: "map",
      conversion_path: [{ id: "conv.text", version: 1 }],
    };
    const doc: AuthoredGraphDocument = {
      name: "Services & Origins",
      nodes: [
        {
          ...source,
          position: { x: 200, y: 0 },
          layout: null,
          config: {},
          input_plugs: [{ port: "incoming", id: "plug-a" }],
        },
        {
          id: "provider",
          kind: "builtin",
          operator_id: "llm.provider",
          operator_version: 1,
          position: { x: 0, y: 200 },
          layout: null,
          config: {},
          input_plugs: [],
          artifact_type_bindings: [],
        },
        {
          id: "consumer",
          kind: "builtin",
          operator_id: "llm.ask",
          operator_version: 1,
          position: { x: 300, y: 200 },
          layout: null,
          config: {},
          input_plugs: [],
          artifact_type_bindings: [],
        },
      ],
      edges: [
        {
          id: "svc-edge",
          from_node: "provider",
          from_port: "chat_service",
          to_node: "consumer",
          to_port: "service",
          to_plug: null,
          enabled: true,
          collection_mode: "direct",
          conversion_path: [],
        },
      ],
      origins: [origin],
      agents: [],
    };
    const docPresentation: SavedGraphDocument["presentation"] = {
      annotations: [],
      viewers: [
        {
          id: "viewer-src",
          position: { x: 0, y: 0 },
          artifact_ref: {
            artifact_id: "a1",
            artifact_type: textType.id,
            schema_version: textType.schema_version,
          },
          mode: "artifact",
        },
        {
          id: "viewer-follow",
          position: { x: 0, y: 400 },
          artifact_ref: null,
          mode: "artifact",
        },
      ],
      links: [
        {
          id: "follow-link",
          source_node_id: "source",
          source_port_name: "result",
          target_viewer_id: "viewer-follow",
        },
      ],
      bindings: [],
    };

    const fallbackScene = cellGraphFromAuthoredDocument(doc, serviceRegistry, {
      presentation: docPresentation,
      viewerOutputValues: new Map([
        ["viewer-follow", { artifactTypeId: "scalar.text", shape: "many" }],
      ]),
    });

    const providerCard = fallbackScene.graph.cards.find(
      (c) => c.id === "provider",
    );
    expect(providerCard?.ports).toMatchObject([
      {
        id: "chat_service",
        kind: "service",
        serviceContractLabel: "Chat Model Service",
        artifactTypeId: "llm.chat",
      },
    ]);
    const mappedSourceCard = fallbackScene.graph.cards.find(
      (c) => c.id === "source",
    );
    expect(
      mappedSourceCard?.ports.find((p) => p.id === "result"),
    ).toMatchObject({
      id: "result",
      direction: "output",
      shape: "many",
    });
    const followCard = fallbackScene.graph.cards.find(
      (c) => c.id === "viewer-follow",
    );
    expect(followCard?.ports.map((p) => p.id)).toEqual([
      "artifact-viewer-input",
      "artifact-card-output",
    ]);
    expect(followCard?.ports[1]).toMatchObject({
      id: "artifact-card-output",
      artifactTypeId: "scalar.text",
      shape: "many",
    });
    expect(
      fallbackScene.graph.pipes.find(
        (p) => p.id === "artifact-origin:origin-1:viewer-src",
      ),
    ).toEqual({
      id: "artifact-origin:origin-1:viewer-src",
      sourceCardId: "viewer-src",
      sourcePortId: "artifact-card-output",
      targetCardId: "source",
      targetPortId: "incoming::plug-a",
      enabled: true,
      collectionMode: "map",
      sourcePortLabel: "artifact",
      projectionLabel: null,
      conversionLabel: "1 conv",
    });

    const explicitScene = cellGraphFromAuthoredDocument(doc, serviceRegistry, {
      presentation: docPresentation,
      originLinks: [
        {
          id: "explicit-origin-edge",
          originId: "origin-1",
          sourceCardId: "viewer-src",
          targetCardId: "source",
          targetPortId: "incoming::plug-a",
          collectionMode: "direct",
          conversionCount: 2,
        },
      ],
      pipeMetadataById: new Map([
        [
          "svc-edge",
          {
            sourcePortLabel: "Chat",
            incompatible: true,
          },
        ],
      ]),
    });
    expect(
      explicitScene.graph.pipes.find((p) => p.id === "explicit-origin-edge"),
    ).toMatchObject({
      collectionMode: "direct",
      conversionLabel: "2 conv",
    });
    expect(
      explicitScene.graph.pipes.find((p) => p.id === "svc-edge"),
    ).toMatchObject({
      sourcePortLabel: "Chat",
      incompatible: true,
    });
  });

  it("builds normalized commands for config, plugs, agents, and color hexes", () => {
    const document = authoredGraphDocument(savedDocument());

    expect(annotationHexFromToken("blue")).toBe("#0369a1");
    expect(annotationHexFromToken("amber")).toBe("#b45309");
    expect(annotationHexFromToken("slate")).toBe("#475569");

    const cfgCmds = graphCommandsFromCellConfigChange("source", "mode", "fast");
    expect(cfgCmds).toEqual([
      {
        kind: "update_node_configuration",
        node_id: "source",
        field: "mode",
        value: "fast",
      },
    ]);
    const afterCfg = cfgCmds.reduce(applyGraphCommandNormalized, document);
    expect(afterCfg.nodes[0]?.config?.mode).toBe("fast");

    const addPlugCmds = graphCommandsFromCellAddPlug(
      "source",
      "incoming",
      source.input_plugs,
    );
    expect(addPlugCmds).toEqual([
      {
        kind: "add_input_plug",
        node_id: "source",
        plug: { id: "incoming-plug-3", port: "incoming" },
      },
    ]);
    const afterAddPlug = addPlugCmds.reduce(
      applyGraphCommandNormalized,
      afterCfg,
    );
    expect(afterAddPlug.nodes[0]?.input_plugs).toContainEqual({
      id: "incoming-plug-3",
      port: "incoming",
    });

    const removePlugCmds = graphCommandsFromCellRemovePlug(
      "source",
      "incoming",
      "incoming::plug-a",
    );
    expect(removePlugCmds).toEqual([
      {
        kind: "remove_input_plug",
        node_id: "source",
        plug_id: "plug-a",
      },
    ]);

    const docMoves = graphCommandsFromCellMovesForDocument(document, [
      { cardId: "source", col: 2, row: 1 },
      { cardId: "agent", col: -4, row: 5 },
    ]);
    expect(docMoves).toHaveLength(2);
    const afterMove = docMoves.reduce(applyGraphCommandNormalized, document);
    expect(afterMove.nodes.find((n) => n.id === "source")?.position).toEqual({
      x: 50,
      y: 25,
    });
    expect(afterMove.agents.find((a) => a.id === "agent")?.position).toEqual({
      x: -100,
      y: 125,
    });

    const agentResize = graphCommandsFromCellResizeForDocument(document, {
      cardId: "agent",
      widthCells: 18,
      heightCells: 10,
    });
    const afterResize = agentResize.reduce(
      applyGraphCommandNormalized,
      document,
    );
    expect(afterResize.agents.find((a) => a.id === "agent")).toMatchObject({
      width: 450,
      height: 250,
    });

    const delCmds = graphCommandsFromCellDeleteForDocument(
      document,
      ["collection", "agent"],
      ["edge"],
    );
    const afterDel = delCmds.reduce(applyGraphCommandNormalized, document);
    expect(afterDel.nodes.map((n) => n.id)).toEqual(["source"]);
    expect(afterDel.agents.map((a) => a.id)).toEqual(["default-agent"]);
    expect(afterDel.edges).toEqual([]);
  });
});

describe("artifact card pictures and output corner", () => {
  const ref = (id: string, type = "file.png") => ({
    artifact_id: id,
    artifact_type: type,
    schema_version: 1,
  });
  function viewerScene(
    artifactRef: NonNullable<
      SavedGraphDocument["presentation"]
    >["viewers"][number]["artifact_ref"],
    options: Omit<
      NonNullable<Parameters<typeof cellGraphFromAuthoredDocument>[2]>,
      "presentation"
    > = {},
    bodyHeight: number | null = 150,
  ) {
    return cellGraphFromAuthoredDocument(
      authoredGraphDocument(savedDocument()),
      registry,
      {
        ...options,
        presentation: {
          ...presentation,
          viewers: [
            {
              id: "card",
              position: { x: 0, y: 0 },
              layout:
                bodyHeight === null
                  ? null
                  : {
                      width: 250,
                      body_height: bodyHeight,
                      appendix_height: null,
                    },
              mode: "artifact",
              artifact_ref: artifactRef,
            },
          ],
        },
      },
    );
  }

  it("reads PNG and JPEG files as pictures and a TIFF as a scan", () => {
    for (const type of ["file.png", "file.jpeg", "file.jpg"]) {
      expect(viewerScene(ref("a", type)).surfaceById.card).toMatchObject({
        previewKind: "image",
      });
    }
    expect(viewerScene(ref("a", "file.tiff")).surfaceById.card).toMatchObject({
      previewKind: "tiff",
    });
  });

  it("puts the output on the bottom-right row, one row clear of the edge", () => {
    const small = viewerScene(ref("a")).graph.cards.find(
      (c) => c.id === "card",
    );
    expect(small?.heightCells).toBe(6);
    expect(small?.ports).toEqual([
      expect.objectContaining({ id: "artifact-card-output", rowOffset: 4 }),
    ]);
    const tall = viewerScene(ref("a"), {}, 300).graph.cards.find(
      (c) => c.id === "card",
    );
    expect(tall?.heightCells).toBe(12);
    expect(tall?.ports[0]).toMatchObject({ rowOffset: 10 });
  });

  it("takes the resolved picture and a sequence's next two from the caller", () => {
    const single = viewerScene(ref("a"), {
      viewerImages: new Map([
        ["card", { imageUrl: "/a", stackImageUrls: [], itemCount: 1 }],
      ]),
    });
    expect(single.surfaceById.card).toMatchObject({ imageUrl: "/a" });
    expect(single.surfaceById.card).not.toHaveProperty("stackImageUrls");
    expect(single.surfaceById.card).not.toHaveProperty("itemCount");

    const sequence = viewerScene(
      {
        artifact_type: "file.png",
        schema_version: 1,
        index_key: "order_index",
        ordered: true,
        item_refs: [ref("a"), ref("b"), ref("c"), ref("d")],
      },
      {
        viewerImages: new Map([
          [
            "card",
            { imageUrl: "/a", stackImageUrls: ["/b", "/c"], itemCount: 4 },
          ],
        ]),
      },
    );
    expect(sequence.surfaceById.card).toMatchObject({
      imageUrl: "/a",
      stackImageUrls: ["/b", "/c"],
      itemCount: 4,
      dimensionsLabel: "4 items",
    });
  });

  it("leaves a picture without a resolved URL on its placeholder", () => {
    const tiff = viewerScene(ref("t", "file.tiff"), {
      viewerImages: new Map([
        ["card", { imageUrl: null, stackImageUrls: [], itemCount: 1 }],
      ]),
    });
    expect(tiff.surfaceById.card).toMatchObject({
      previewKind: "tiff",
      imageUrl: null,
    });
  });

  it("fits unsized image cards to their natural aspect ratio on the cell grid while honouring saved layout", () => {
    // 16:9 landscape, 3:4 portrait, 9:16 tall portrait, and unknown size.
    expect(cellArtifactImageCells({ width: 1920, height: 1080 })).toEqual({
      widthCells: 10,
      heightCells: 7,
    });
    expect(cellArtifactImageCells({ width: 1200, height: 1600 })).toEqual({
      widthCells: 10,
      heightCells: 14,
    });
    expect(cellArtifactImageCells({ width: 1080, height: 1920 })).toEqual({
      widthCells: 8,
      heightCells: 14,
    });
    expect(cellArtifactImageCells(null)).toEqual({
      widthCells: 10,
      heightCells: 6,
    });
    // Explicit saved width and height always win over natural size.
    expect(
      cellArtifactImageCells(
        { width: 1200, height: 1600 },
        { width: 350, body_height: 200 },
      ),
    ).toEqual({ widthCells: 14, heightCells: 8 });
    // Partial saved width derives height from natural aspect.
    expect(
      cellArtifactImageCells({ width: 1200, height: 1600 }, { width: 350 }),
    ).toEqual({ widthCells: 14, heightCells: 19 });

    // End-to-end through the adapter: unsized portrait photo adjusts heightCells and its output port row.
    const portrait = viewerScene(
      ref("p", "file.png"),
      {
        viewerImages: new Map([
          [
            "card",
            {
              imageUrl: "/p",
              stackImageUrls: [],
              itemCount: 1,
              naturalSize: { width: 1200, height: 1600 },
            },
          ],
        ]),
      },
      null,
    );
    const card = portrait.graph.cards.find((c) => c.id === "card")!;
    expect(card.widthCells).toBe(10);
    expect(card.heightCells).toBe(14);
    expect(card.ports[0]?.rowOffset).toBe(12);
    expect(card.resizeBounds).toEqual({
      minWidthCells: 6,
      maxWidthCells: 48,
      minHeightCells: 3,
      maxHeightCells: 48,
    });

    // Saved compact (6×3) and oversized (>48×48) artifact layouts clamp cleanly to the shared bounds.
    expect(
      cellArtifactImageCells(
        { width: 1200, height: 1600 },
        { width: 150, body_height: 75 },
      ),
    ).toEqual({ widthCells: 6, heightCells: 3 });
    expect(
      cellArtifactImageCells(
        { width: 1200, height: 1600 },
        { width: 3000, body_height: 3000 },
      ),
    ).toEqual({ widthCells: 48, heightCells: 48 });
  });
});
