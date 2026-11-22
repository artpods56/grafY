/**
 * Two operators shaped like the real ones whose config cards these tests
 * guard: the GIS plugin's `Vector map layer` (a slider, a switch, a segmented
 * choice, two advanced zooms and a `Style` union whose categorized branch is
 * a list of items) and the LLM plugin's `Ask a model` (fields that only show
 * once `Answer format` is wired, and a write-only API key).
 */
import type { NodeRegistry, NodeSpec, Port } from "@/lib/api";

import type {
  AuthoredGraphDocument,
  AuthoredGraphNode,
} from "../authoring/graph-document";

const textType = { id: "scalar.text", schema_version: 1 };
const featuresType = { id: "geo.features", schema_version: 1 };
const schemaType = { id: "json.schema", schema_version: 1 };

export function fixturePort(name: string, overrides: Partial<Port> = {}): Port {
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

function spec(overrides: Partial<NodeSpec>): NodeSpec {
  return {
    operator_id: "test.op",
    operator_version: 1,
    title: "Op",
    description: "",
    plugin_slug: "test",
    catalog_visible: true,
    origin: "builtin",
    runnable: true,
    input_schema: {},
    output_schema: {},
    inputs: [],
    outputs: [],
    config_schema: {},
    ...overrides,
  };
}

export const vectorLayerSpec = spec({
  operator_id: "gis.vector_layer",
  title: "Vector map layer",
  inputs: [fixturePort("features", { artifact_type: featuresType })],
  outputs: [
    fixturePort("layer", { direction: "output", artifact_type: featuresType }),
  ],
  config_schema: {
    $defs: {
      GeoVectorStyle: {
        type: "object",
        title: "Simple",
        properties: {
          kind: { const: "simple", type: "string" },
          fill: {
            type: "string",
            title: "Fill",
            default: "#3366ff",
            "x-grafy-widget": "color",
          },
          stroke_width: {
            type: "number",
            title: "Stroke width",
            default: 1,
            minimum: 0,
            maximum: 10,
            "x-grafy-widget": "slider",
          },
        },
        required: ["kind"],
      },
      GeoCategorizedPointStyle: {
        type: "object",
        title: "By category",
        properties: {
          kind: { const: "categorized_points", type: "string" },
          categories: {
            type: "array",
            title: "Categories",
            items: { $ref: "#/$defs/GeoPointCategory" },
            minItems: 1,
          },
        },
        required: ["kind", "categories"],
      },
      GeoPointCategory: {
        type: "object",
        title: "GeoPointCategory",
        properties: {
          id: { type: "string", "x-grafy-auto-id": true },
          title: { type: "string", title: "Title", minLength: 1 },
          color: {
            type: "string",
            title: "Color",
            default: "#ff8800",
            "x-grafy-widget": "color",
          },
        },
        required: ["id", "title", "color"],
      },
      GeoFeatureStyle: {
        discriminator: { propertyName: "kind" },
        oneOf: [
          { $ref: "#/$defs/GeoVectorStyle" },
          { $ref: "#/$defs/GeoCategorizedPointStyle" },
        ],
      },
    },
    type: "object",
    properties: {
      title: { type: "string", title: "Title", minLength: 1 },
      visible: {
        type: "boolean",
        title: "Visible",
        default: true,
        "x-grafy-widget": "switch",
      },
      opacity: {
        type: "number",
        title: "Opacity",
        default: 1,
        minimum: 0,
        maximum: 1,
        "x-grafy-widget": "slider",
      },
      blend: {
        type: "string",
        title: "Blend",
        enum: ["normal", "multiply"],
        default: "normal",
        "x-grafy-widget": "segmented",
        "x-grafy-enum-labels": { normal: "Normal", multiply: "Multiply" },
      },
      min_zoom: {
        type: "integer",
        title: "Min zoom",
        default: 0,
        minimum: 0,
        maximum: 24,
        "x-grafy-advanced": true,
      },
      max_zoom: {
        type: "integer",
        title: "Max zoom",
        default: 22,
        minimum: 0,
        maximum: 24,
        "x-grafy-advanced": true,
      },
      style: { $ref: "#/$defs/GeoFeatureStyle", title: "Style" },
    },
    required: ["title", "style"],
  },
});

export const askModelSpec = spec({
  operator_id: "llm.ask",
  title: "Ask a model",
  inputs: [
    fixturePort("prompt"),
    fixturePort("answer_format", {
      title: "Answer format",
      required: false,
      artifact_type: schemaType,
    }),
  ],
  outputs: [fixturePort("answer", { direction: "output" })],
  config_schema: {
    type: "object",
    properties: {
      base_url: { type: "string", title: "Base URL" },
      model: { type: "string", title: "Model" },
      schema_name: {
        type: "string",
        title: "Schema Name",
        "x-grafy-visible-when": { portConnected: "answer_format" },
      },
      strict: {
        type: "boolean",
        title: "Strict",
        default: true,
        "x-grafy-visible-when": { portConnected: "answer_format" },
      },
    },
  },
  secret_inputs: [
    {
      name: "api_key",
      title: "API key",
      description: "Bearer key for the configured base URL.",
      config_dependencies: ["base_url"],
      provider_kind: "openai_compatible",
      supports_verification: true,
    },
  ],
});

/** Sends a JSON schema, for wiring `Answer format`. */
export const schemaSourceSpec = spec({
  operator_id: "json.schema_source",
  title: "Schema",
  outputs: [
    fixturePort("schema", { direction: "output", artifact_type: schemaType }),
  ],
});

export const richRegistry: NodeRegistry = {
  nodes: [vectorLayerSpec, askModelSpec, schemaSourceSpec],
  artifact_types: [],
  artifact_conversions: [],
  plugins: [],
};

export function fixtureNode(
  id: string,
  nodeSpec: NodeSpec,
  config: Record<string, unknown> = {},
): AuthoredGraphNode {
  return {
    id,
    kind: "builtin",
    operator_id: nodeSpec.operator_id,
    operator_version: nodeSpec.operator_version,
    position: { x: 0, y: 0 },
    layout: null,
    artifact_type_bindings: [],
    input_plugs: [],
    config,
  };
}

export function fixtureDocument(
  nodes: readonly AuthoredGraphNode[],
  edges: AuthoredGraphDocument["edges"] = [],
): AuthoredGraphDocument {
  return { name: "Fixture", nodes, edges, origins: [], agents: [] };
}

/** `Schema` → `Ask a model`'s `Answer format`. */
export function answerFormatEdge(
  enabled = true,
): AuthoredGraphDocument["edges"][number] {
  return {
    id: "schema-to-ask",
    from_node: "schema",
    from_port: "schema",
    to_node: "ask",
    to_port: "answer_format",
    collection_mode: "direct",
    conversion_path: [],
    enabled,
  };
}
