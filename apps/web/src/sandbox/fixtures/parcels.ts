import type { NodeRegistry, NodeSpec, Port } from "@/lib/api";
import type { SchemaField } from "@/features/workbench/canvas/config-schema";

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
): NodeRegistry["artifact_types"][number] {
  return {
    key: { id, schema_version: 1 },
    title,
    bundle: { format: "inline-json", version: 1 },
    payload_schema: {},
    field_projections: [],
  };
}

export const ROWS_PORT = port("rows", "output", "table.data", {
  title: "rows",
  description: "Parcel table.",
});

export const MAP_PORT = port("map", "output", "geo.map_document", {
  title: "map",
  description: "Parcel map.",
});

export const NOTES_PORT = port("notes", "output", "text.markdown", {
  title: "notes",
  description: "Survey notes.",
});

export const QUERY_PARCELS_SPEC: NodeSpec = {
  operator_id: "sandbox.query_parcels",
  operator_version: 1,
  plugin_slug: "sandbox.geo",
  origin: "builtin",
  title: "Query parcels",
  description: "Returns the parcel table for the active survey.",
  config_schema: {},
  input_schema: {},
  output_schema: {},
  inputs: [],
  outputs: [ROWS_PORT],
  catalog_visible: true,
  runnable: true,
};

export const MAP_DOCUMENT_SPEC: NodeSpec = {
  operator_id: "sandbox.map_document",
  operator_version: 1,
  plugin_slug: "sandbox.geo",
  origin: "builtin",
  title: "Map document",
  description: "Assembles a map document from parcel geometry.",
  config_schema: {},
  input_schema: {},
  output_schema: {},
  inputs: [],
  outputs: [MAP_PORT],
  catalog_visible: true,
  runnable: true,
};

export const SURVEY_NOTES_SPEC: NodeSpec = {
  operator_id: "sandbox.survey_notes",
  operator_version: 1,
  plugin_slug: "sandbox.geo",
  origin: "builtin",
  title: "Survey notes",
  description: "Markdown notes for the survey.",
  config_schema: {},
  input_schema: {},
  output_schema: {},
  inputs: [],
  outputs: [NOTES_PORT],
  catalog_visible: true,
  runnable: true,
};

export const QUERY_PARCELS_FIELDS: readonly SchemaField[] = [
  {
    name: "survey_id",
    title: "Survey",
    type: "string",
    required: true,
    nullable: false,
  },
];

export const PARCELS_REGISTRY: NodeRegistry = {
  plugins: [
    {
      slug: "sandbox.geo",
      title: "Geo",
      origin: "builtin",
      entry_kind: "plugin",
    },
  ],
  artifact_types: [
    artifact("table.data", "Table"),
    artifact("geo.map_document", "Map document"),
    artifact("text.markdown", "Markdown"),
  ],
  artifact_conversions: [],
  nodes: [QUERY_PARCELS_SPEC, MAP_DOCUMENT_SPEC, SURVEY_NOTES_SPEC],
};

export const PARCEL_ROWS = [
  { id: "12", block: "41", facing: "north", use: "lot" },
  { id: "14", block: "44", facing: "east", use: "lot" },
  { id: "18", block: "02", facing: "west", use: "road" },
  { id: "21", block: "08", facing: "south", use: "lot" },
] as const;
