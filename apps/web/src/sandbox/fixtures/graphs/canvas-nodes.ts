import { DEFAULT_NODE_WIDTH } from "@/features/workbench/authoring/node-layout";
import { defaultNodeConfig } from "@/features/workbench/authoring/types";
import { CELL_SIZE } from "@/features/workbench/cell-canvas/cell-model";
import type { NodeRegistry } from "@/lib/api";
import { askAModelRegistry } from "../ask-a-model-registry";
import { canvasNodeRegistry } from "../canvas-node-registry";
import { askAModelDocument, ASK_A_MODEL_CARD_ID } from "./ask-a-model";

export const nodeFixtures = [
  { id: ASK_A_MODEL_CARD_ID, title: "Ask a model" },
  { id: "schema-builder", title: "Schema Builder" },
  { id: "text-input", title: "Text input" },
] as const;

export const nodeFixtureRegistry: NodeRegistry = {
  ...askAModelRegistry,
  nodes: [...askAModelRegistry.nodes, ...canvasNodeRegistry.nodes],
  plugins: [...askAModelRegistry.plugins, ...canvasNodeRegistry.plugins],
  artifact_types: [
    ...askAModelRegistry.artifact_types,
    ...canvasNodeRegistry.artifact_types,
  ],
};

export function readNodeIds(value: string | null): string[] {
  const ids = new Set((value ?? ASK_A_MODEL_CARD_ID).split(","));
  return nodeFixtures.filter(({ id }) => ids.has(id)).map(({ id }) => id);
}

function fixtureNode(id: string, operator: string) {
  const spec = canvasNodeRegistry.nodes.find(
    (node) => node.operator_id === operator,
  );
  if (!spec) throw new Error(`Missing catalog fixture for ${operator}`);
  return {
    id,
    kind: "builtin" as const,
    operator_id: spec.operator_id,
    operator_version: spec.operator_version,
    position: { x: 0, y: 0 },
    layout: null,
    config: defaultNodeConfig(spec),
    input_plugs: [],
    artifact_type_bindings: [],
  };
}

const allNodes = [
  fixtureNode("schema-builder", "schema.builder"),
  ...askAModelDocument.nodes,
  fixtureNode("text-input", "text.input"),
];

export function canvasNodesDocument(
  ids: readonly string[],
): typeof askAModelDocument {
  const nodes = allNodes
    .filter(({ id }) => ids.includes(id))
    .map((node, index) => ({
      ...node,
      position: {
        x: index * (DEFAULT_NODE_WIDTH + 5 * CELL_SIZE),
        y: 0,
      },
    }));
  return {
    ...askAModelDocument,
    nodes,
    edges:
      ids.includes("schema-builder") && ids.includes(ASK_A_MODEL_CARD_ID)
        ? [
            {
              id: "schema-to-model",
              from_node: "schema-builder",
              from_port: "json_schema",
              to_node: ASK_A_MODEL_CARD_ID,
              to_port: "json_schema",
              to_plug: null,
              enabled: true,
              collection_mode: "direct",
              projection: null,
              conversion_path: [],
              route_offset: null,
            },
          ]
        : [],
  };
}
