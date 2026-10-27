import { describe, expect, it } from "vitest";

import type { NodeRegistry, NodeSpec, SavedGraph } from "@/lib/api";
import { addNodeCommand } from "./graph-document-adapter";
import { hydrateSavedGraph } from "./saved-graph";
import { createWorkflowNodeData, serializeRunNode } from "./types";
import { createSavedGraphRequest } from "../model/graph-document";
import { catalogNodeSpecs } from "../model/node-catalog";
import { toRoomGraphCommand } from "../room/room-command-bridge";

const raster: NodeSpec = {
  operator_id: "gis.raster.import",
  operator_version: 1,
  plugin_slug: "external.gis",
  origin: "builtin",
  title: "Import raster",
  description: "Import a georeferenced raster.",
  catalog_visible: true,
  runnable: true,
  config_schema: { type: "object", properties: { max_zoom: { default: 12 } } },
  input_schema: {},
  output_schema: {},
  inputs: [],
  outputs: [],
};
const registry: NodeRegistry = {
  plugins: [],
  artifact_types: [],
  artifact_conversions: [],
  nodes: [raster],
};

function savedGraph(operatorId = raster.operator_id): SavedGraph {
  return {
    id: "00000000-0000-4000-8000-000000000001",
    name: "Historical GIS graph",
    revision: 1,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
    document: {
      schema_version: 7,
      nodes: [
        {
          id: "import-1",
          kind: "builtin",
          operator_id: operatorId,
          operator_version: 1,
          config: {
            max_zoom: 9,
            code: "historical code",
            preset_id: "split-text",
          },
          input_plugs: [],
          artifact_type_bindings: [],
          position: { x: 25, y: 45 },
        },
      ],
      edges: [],
      origins: [],
    },
  };
}

describe("in-process family authoring", () => {
  it("inserts, saves, submits and executes GIS nodes without a release selection", () => {
    expect(catalogNodeSpecs(registry, null)).toEqual([raster]);
    const data = createWorkflowNodeData(raster);
    const command = addNodeCommand("raster-1", data, { x: 80, y: 120 });
    expect(command.node).toMatchObject({
      kind: "builtin",
      config: { max_zoom: 12 },
    });
    const document = {
      name: "Raster graph",
      nodes: [command.node],
      edges: [],
      origins: [],
    };
    const saved = createSavedGraphRequest(document);
    const room = toRoomGraphCommand(command, document);
    const run = serializeRunNode("raster-1", data);
    for (const node of [command.node, saved.document.nodes[0], run]) {
      expect(node).toHaveProperty("kind", "builtin");
      expect(node).not.toHaveProperty("plugin_release");
      expect(node).not.toHaveProperty("plugin_release_pin");
    }
    expect(room).toEqual(command);
    expect(saved.document.schema_version).toBe(7);
  });

  it("matches a historical family node to its deployed operator without rewriting its input", () => {
    const saved = savedGraph();
    const before = structuredClone(saved);
    const hydrated = hydrateSavedGraph(saved, registry);
    expect(hydrated.nodes[0]?.data.compatibility).toEqual({
      status: "supported",
    });
    expect(hydrated.nodes[0]?.data.config).toEqual(
      saved.document.nodes[0]?.config,
    );
    expect(saved).toEqual(before);
  });

  it.each(["python.transform", "python.inspect"])(
    "preserves %s as inert historical data",
    (operatorId) => {
      const saved = savedGraph(operatorId);
      const before = structuredClone(saved);
      const hydrated = hydrateSavedGraph(saved, registry);
      const node = hydrated.nodes[0];
      expect(node?.data.compatibility).toMatchObject({
        status: "unsupported",
        issues: [
          `Operator ${operatorId}@1 is unavailable. This saved node is preserved but cannot run.`,
        ],
        persistedNode: saved.document.nodes[0],
      });
      expect(node?.data.config).toEqual(saved.document.nodes[0]?.config);
      if (!node) throw new Error("Expected preserved Python node");
      expect(() => serializeRunNode(node.id, node.data)).toThrow(
        `unsupported node import-1 (${operatorId}@1)`,
      );
      expect(saved).toEqual(before);
    },
  );
});
