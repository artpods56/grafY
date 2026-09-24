import type { NodeRegistry, NodeSpec, Port } from "@/lib/api";
import type { SchemaField } from "@/features/workbench/canvas/config-schema";

import geoMapLayerSchema from "./geo-map-layer.schema.json";

function port(
  name: string,
  direction: Port["direction"],
  artifactTypeId: string,
  options: Partial<Port> = {},
): Port {
  return {
    name,
    title: options.title ?? name,
    description: options.description ?? null,
    direction,
    artifact_type: { id: artifactTypeId, schema_version: 1 },
    artifact_type_variable: null,
    shape: options.shape ?? "one",
    accepted_shapes: options.accepted_shapes ?? [options.shape ?? "one"],
    instance_plugs: false,
    variadic: false,
    required: options.required ?? true,
  };
}

function artifact(
  id: string,
  title: string,
  payload_schema: Record<string, unknown> = {},
): NodeRegistry["artifact_types"][number] {
  return {
    key: { id, schema_version: 1 },
    title,
    bundle: { format: "inline-json", version: 1 },
    payload_schema,
    field_projections: [],
  };
}

const features = port("features", "input", "geo.feature_collection", {
  title: "features",
  description: "Exact feature collection artifact reference.",
});

export const LAYER_PORT = port("layer", "output", "geo.map_layer", {
  title: "layer",
  description: "Lightweight map layer.",
});

export const VECTOR_LAYER_SPEC: NodeSpec = {
  operator_id: "gis.map.vector_layer",
  operator_version: 1,
  plugin_slug: "gis",
  origin: "plugin",
  title: "Vector map layer",
  description: "Turn a feature collection into a styled vector map layer.",
  config_schema: {},
  input_schema: {},
  output_schema: {},
  inputs: [features],
  outputs: [LAYER_PORT],
  catalog_visible: true,
  runnable: true,
};

export const VECTOR_LAYER_FIELDS: readonly SchemaField[] = [
  {
    name: "title",
    title: "Title",
    type: "string",
    required: true,
    nullable: false,
  },
  {
    name: "visible",
    title: "Visible",
    type: "boolean",
    required: true,
    nullable: false,
  },
  {
    name: "opacity",
    title: "Opacity",
    type: "number",
    required: true,
    nullable: false,
  },
  {
    name: "min_zoom",
    title: "Min zoom",
    type: "integer",
    required: true,
    nullable: false,
  },
];

export const GEO_MAP_LAYER_SCHEMA = geoMapLayerSchema as Record<
  string,
  unknown
>;

export const VECTOR_LAYER_REGISTRY: NodeRegistry = {
  plugins: [
    {
      slug: "gis",
      title: "GIS",
      origin: "plugin",
      entry_kind: "plugin",
      scope: "system",
      revision: 1,
      plugin_release: { scope: "system", slug: "gis", revision: 1 },
      runnable: true,
    },
  ],
  artifact_types: [
    artifact("geo.feature_collection", "GeoJSON feature collection"),
    artifact("geo.map_layer", "Map layer", GEO_MAP_LAYER_SCHEMA),
  ],
  artifact_conversions: [],
  nodes: [VECTOR_LAYER_SPEC],
};
