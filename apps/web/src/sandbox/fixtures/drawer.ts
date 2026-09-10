import type { NodeRegistry, NodeSpec, Port } from "@/lib/api";

function port(
  name: string,
  direction: Port["direction"],
  artifactTypeId: string,
  options: Partial<Port> = {},
): Port {
  const shape = options.shape ?? "one";
  return {
    name,
    title: options.title ?? name,
    description: options.description ?? null,
    direction,
    artifact_type: { id: artifactTypeId, schema_version: 1 },
    artifact_type_variable: null,
    shape,
    accepted_shapes: options.accepted_shapes ?? [shape],
    instance_plugs: options.instance_plugs ?? false,
    variadic: options.variadic ?? false,
    required: options.required ?? true,
  };
}

function artifactType(
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

/** One `one` input, so the drag target is a single row. */
export const IMPORT_TABLE_SPEC: NodeSpec = {
  operator_id: "sandbox.import_table",
  operator_version: 1,
  plugin_slug: "sandbox.geo",
  origin: "plugin",
  title: "Import table",
  description: "Reads one CSV file into a parcel table.",
  config_schema: {},
  input_schema: {},
  output_schema: {},
  inputs: [
    port("file", "input", "file.csv", {
      title: "file",
      description: "One CSV file.",
      instance_plugs: true,
    }),
  ],
  outputs: [
    port("table", "output", "table.data", {
      title: "table",
      description: "Imported rows.",
    }),
  ],
  catalog_visible: true,
  runnable: true,
};

/** A `many` input that also accepts a single artifact. */
export const SUMMARIZE_TABLES_SPEC: NodeSpec = {
  operator_id: "sandbox.summarize_tables",
  operator_version: 1,
  plugin_slug: "sandbox.geo",
  origin: "plugin",
  title: "Summarize tables",
  description: "Writes one report from any number of tables.",
  config_schema: {},
  input_schema: {},
  output_schema: {},
  inputs: [
    port("tables", "input", "table.data", {
      title: "tables",
      description: "Every table in the sequence, in order.",
      shape: "many",
      accepted_shapes: ["one", "many"],
      instance_plugs: true,
    }),
  ],
  outputs: [
    port("report", "output", "text.markdown", {
      title: "report",
      description: "Markdown report.",
    }),
  ],
  catalog_visible: true,
  runnable: true,
};

/** One input fed by an edge, one optional input for the image case. */
export const RENDER_PAGE_SPEC: NodeSpec = {
  operator_id: "sandbox.render_page",
  operator_version: 1,
  plugin_slug: "sandbox.geo",
  origin: "plugin",
  title: "Render page",
  description: "Renders a page from a report and an optional image.",
  config_schema: {},
  input_schema: {},
  output_schema: {},
  inputs: [
    port("body", "input", "text.markdown", {
      title: "body",
      description: "Page body.",
      instance_plugs: true,
    }),
    port("logo", "input", "image.raster", {
      title: "logo",
      description: "Optional page image.",
      required: false,
      instance_plugs: true,
    }),
  ],
  outputs: [],
  catalog_visible: true,
  runnable: true,
};

export const DRAWER_REGISTRY: NodeRegistry = {
  plugins: [
    {
      slug: "sandbox.geo",
      title: "Geo",
      origin: "plugin",
      entry_kind: "plugin",
      scope: "system",
      revision: 1,
      plugin_release: { scope: "system", slug: "sandbox.geo", revision: 1 },
      runnable: true,
    },
  ],
  artifact_types: [
    artifactType("file.csv", "CSV file"),
    artifactType("file.png", "PNG file"),
    artifactType("image.raster", "Raster image"),
    artifactType("table.data", "Table"),
    artifactType("text.markdown", "Markdown"),
  ],
  artifact_conversions: [],
  nodes: [IMPORT_TABLE_SPEC, SUMMARIZE_TABLES_SPEC, RENDER_PAGE_SPEC],
};

/**
 * A drawer artifact stands in for the real `ArtifactRef`: exact identity plus
 * the artifact type, with the run revision it came from.
 */
export interface DrawerArtifact {
  id: string;
  label: string;
  artifactType: string;
  schemaVersion: number;
  revision: number;
  stale?: boolean;
}

export const PRODUCED_ARTIFACTS: readonly DrawerArtifact[] = [
  {
    id: "art-scan-0001",
    label: "scan-0001.png",
    artifactType: "file.png",
    schemaVersion: 1,
    revision: 5,
  },
  {
    id: "art-parcel-lines",
    label: "parcel-lines.csv",
    artifactType: "file.csv",
    schemaVersion: 1,
    revision: 5,
  },
  {
    id: "art-parcels-2026",
    label: "parcels_2026",
    artifactType: "table.data",
    schemaVersion: 1,
    revision: 5,
  },
  {
    id: "art-zoning-2026",
    label: "zoning_2026",
    artifactType: "table.data",
    schemaVersion: 1,
    revision: 5,
  },
  {
    id: "art-roads-2026",
    label: "roads_2026",
    artifactType: "table.data",
    schemaVersion: 1,
    revision: 5,
  },
  {
    id: "art-summary",
    label: "summary.md",
    artifactType: "text.markdown",
    schemaVersion: 1,
    revision: 5,
  },
  {
    id: "art-zoning-old",
    label: "zoning_2025",
    artifactType: "table.data",
    schemaVersion: 1,
    revision: 3,
    stale: true,
  },
  {
    id: "art-basemap",
    label: "basemap.tiff",
    artifactType: "image.raster",
    schemaVersion: 1,
    revision: 2,
    stale: true,
  },
];

export const KEPT_ARTIFACTS: readonly DrawerArtifact[] = [
  {
    id: "art-scan-0001",
    label: "scan-0001.png",
    artifactType: "file.png",
    schemaVersion: 1,
    revision: 5,
  },
  {
    id: "art-parcels-2026",
    label: "parcels_2026",
    artifactType: "table.data",
    schemaVersion: 1,
    revision: 5,
  },
  {
    id: "art-basemap",
    label: "basemap.tiff",
    artifactType: "image.raster",
    schemaVersion: 1,
    revision: 2,
  },
];

export const DRAWER_ARTIFACTS: readonly DrawerArtifact[] = [
  ...PRODUCED_ARTIFACTS,
  ...KEPT_ARTIFACTS.filter(
    (kept) =>
      !PRODUCED_ARTIFACTS.some((produced) => produced.id === kept.id),
  ),
];
