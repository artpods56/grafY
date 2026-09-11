import type { NodeSpec, Port, Workspace } from "@/lib/api";
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

/** One input fed by an edge, plus a second input for a refusal. */
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
