import type { NodeRegistry, NodeSpec, Port, Workspace } from "@/lib/api";
import type { WorkspaceContextValue } from "@/features/workspaces/WorkspaceLayout";

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
 * One artifact in either drawer. Identity is the exact reference the product
 * uses, plus the run revision it came from, so the same artifact can appear in
 * the library and in a run without ever being copied.
 */
export interface DrawerArtifact {
  id: string;
  label: string;
  artifactType: string;
  schemaVersion: number;
  revision: number;
}

/** A folder in the library tree. */
export interface LibraryFolder {
  name: string;
  open: boolean;
  artifacts: readonly DrawerArtifact[];
}

function artifact(
  id: string,
  label: string,
  artifactType: string,
  revision = 5,
): DrawerArtifact {
  return { id, label, artifactType, schemaVersion: 1, revision };
}

/**
 * The left drawer is the library. It belongs to the workspace, not to a graph,
 * and it outlives every graph that references it.
 */
export const LIBRARY_FOLDERS: readonly LibraryFolder[] = [
  {
    name: "images",
    open: true,
    artifacts: [
      artifact("art-boat", "boat.jpg", "file.png", 2),
      artifact("art-mountains", "mountains.png", "file.png", 2),
      artifact("art-diagram", "diagram.png", "file.png", 1),
      artifact("art-coast", "coast.jpg", "file.png", 3),
      artifact("art-sunset", "sunset.jpg", "file.png", 3),
    ],
  },
  {
    name: "tables",
    open: true,
    artifacts: [
      artifact("art-sales", "sales.csv", "table.data", 4),
      artifact("art-parcels-2026", "parcels_2026", "table.data", 5),
      artifact("art-parcel-lines", "parcel-lines.csv", "file.csv", 5),
    ],
  },
  {
    name: "text",
    open: false,
    artifacts: [
      artifact("art-notes", "notes.txt", "text.markdown", 1),
      artifact("art-prompt", "prompt.md", "text.markdown", 1),
    ],
  },
  {
    name: "models",
    open: true,
    artifacts: [artifact("art-basemap", "basemap.tiff", "image.raster", 2)],
  },
  {
    name: "other",
    open: false,
    artifacts: [artifact("art-spec", "specification.pdf", "file.pdf", 1)],
  },
];

export const LIBRARY_ARTIFACTS: readonly DrawerArtifact[] =
  LIBRARY_FOLDERS.flatMap((folder) => folder.artifacts);

/** One node in a run group of the right drawer. */
export interface RunGroup {
  node: string;
  time: string;
  artifacts: readonly DrawerArtifact[];
}

export interface RunBatch {
  heading: "Latest run" | "Previous runs";
  stamp: string;
  groups: readonly RunGroup[];
}

/**
 * The right drawer is the run queue: what this graph produced, newest first,
 * grouped by the node that made it. A kept artifact stays here as well, because
 * the run still produced it.
 */
export const RUN_BATCHES: readonly RunBatch[] = [
  {
    heading: "Latest run",
    stamp: "Today, 14:28",
    groups: [
      {
        node: "Summarize tables",
        time: "14:28",
        artifacts: [artifact("art-scan-0001", "scan-0001.png", "file.png", 5)],
      },
      {
        node: "Import table",
        time: "14:27",
        artifacts: [
          // Already in the library under the same identity, so the run row is
          // the promotion case: draggable, and already saved.
          artifact("art-parcels-2026", "parcels_2026", "table.data", 5),
          artifact("art-zoning-2026", "zoning_2026", "table.data", 5),
        ],
      },
    ],
  },
  {
    heading: "Previous runs",
    stamp: "Sep 10, 2026",
    groups: [
      {
        node: "Summarize tables",
        time: "16:20",
        artifacts: [
          artifact("art-zoning-2025", "zoning_2025", "table.data", 3),
        ],
      },
      {
        node: "Render page",
        time: "16:10",
        artifacts: [artifact("art-summary", "summary.md", "text.markdown", 4)],
      },
    ],
  },
];

export const RUN_ARTIFACTS: readonly DrawerArtifact[] = RUN_BATCHES.flatMap(
  (batch) => batch.groups.flatMap((group) => group.artifacts),
);

export const DRAWER_ARTIFACTS: readonly DrawerArtifact[] = [
  ...LIBRARY_ARTIFACTS,
  ...RUN_ARTIFACTS.filter(
    (run) => !LIBRARY_ARTIFACTS.some((library) => library.id === run.id),
  ),
];

/**
 * A stand-in workspace so a sandbox can render workspace-scoped components
 * with no API and no workspace route. See `WorkspaceContextScope`.
 */
export const SANDBOX_WORKSPACE: Workspace = {
  // Empty on purpose: the workspace id keys the registry fetch, and a sandbox
  // has no registry to fetch. An empty id leaves the type popover on its
  // "not declared in the current registry" path instead of calling the API.
  id: "",
  name: "Sandbox",
  slug: "sandbox",
  kind: "personal",
  role: "owner",
  capabilities: [],
};

export function sandboxWorkspaceContext(): WorkspaceContextValue {
  return {
    workspace: SANDBOX_WORKSPACE,
    workspaces: [SANDBOX_WORKSPACE],
    refreshWorkspaces: async () => undefined,
  };
}
