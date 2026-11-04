import type {
  ArtifactTypeKey,
  GraphDefinition,
  NodeRegistry,
  NodeSpec,
  PluginSpec,
  Port,
  SavedGraphNode,
} from "@/lib/api";

/**
 * The rules a Project's Graphs follow among themselves (ADR 0020).
 *
 * A Graph declares its **interface** with boundary nodes and places a sibling
 * Graph on its canvas with a **call node** whose ports are that interface. The
 * call relation must stay acyclic and a Graph with callers cannot go away. This
 * module reads those rules out of the saved document and builds the catalog
 * entries the canvas needs to offer them; it holds no state of its own, so the
 * same functions answer for a head replayed from the room and for a draft.
 */

/** The operator a boundary input node runs: it contributes one Graph input. */
export const GRAPH_INPUT_OPERATOR_ID = "graph.input";
/** The operator a boundary output node runs: it carries one Graph output. */
export const GRAPH_OUTPUT_OPERATOR_ID = "graph.output";
/** The only boundary operator version a document may name. */
export const GRAPH_BOUNDARY_OPERATOR_VERSION = 1;
/** The single port a boundary node reads or writes inside its own Graph. */
export const GRAPH_BOUNDARY_PORT = "value";
/** The artifact type binding variable that types a boundary node. */
export const GRAPH_ARTIFACT_TYPE_VARIABLE = "T";
/** The only operator version a call node may name; it is the callee Graph itself. */
export const CALL_NODE_OPERATOR_VERSION = 1;
/** Slug of the synthetic plugin entry that owns boundary and call node specs. */
export const PROJECT_GRAPHS_PLUGIN_SLUG = "project-graphs";

/** One declared input or output of a Graph. */
export interface InterfacePort {
  /** How callers address it: the boundary node's `config.public_name`. */
  readonly name: string;
  /** The type bound to the boundary node, or null when it binds nothing. */
  readonly artifactType: { id: string; schema_version: number } | null;
  /** Inputs default to required; an output always is one. */
  readonly required: boolean;
  readonly description: string | null;
}

/** The ports a Graph offers its call sites, in document order. */
export interface GraphInterface {
  readonly inputs: readonly InterfacePort[];
  readonly outputs: readonly InterfacePort[];
}

/** Where a call node sits: the Graph that holds it and the node itself. */
export interface CallSite {
  readonly graphId: string;
  readonly nodeId: string;
}

function configText(
  node: SavedGraphNode,
  key: "public_name" | "description",
): string | null {
  const value = node.config?.[key];
  return typeof value === "string" ? value : null;
}

/** A node that declares one input or one output of its own Graph. */
function isBoundaryNode(node: SavedGraphNode): boolean {
  return (
    node.operator_id === GRAPH_INPUT_OPERATOR_ID ||
    node.operator_id === GRAPH_OUTPUT_OPERATOR_ID
  );
}

/** A node that places a sibling Graph — whatever its callee id is. */
function isCallNode(node: SavedGraphNode): boolean {
  return node.kind === "call";
}

/** The interface a Graph's boundary nodes declare, in document order. */
export function graphInterface(graph: GraphDefinition): GraphInterface {
  const inputs: InterfacePort[] = [];
  const outputs: InterfacePort[] = [];
  for (const node of graph.document.nodes) {
    if (!isBoundaryNode(node)) continue;
    let artifactType: ArtifactTypeKey | null = null;
    for (const binding of node.artifact_type_bindings) {
      if (binding.variable === GRAPH_ARTIFACT_TYPE_VARIABLE) {
        artifactType = binding.artifact_type;
      }
    }
    const description = configText(node, "description");
    const name = configText(node, "public_name") ?? "";
    if (node.operator_id === GRAPH_INPUT_OPERATOR_ID) {
      const required = node.config?.required;
      inputs.push({
        name,
        artifactType,
        required: typeof required === "boolean" ? required : true,
        description,
      });
    } else {
      outputs.push({ name, artifactType, required: true, description });
    }
  }
  return { inputs, outputs };
}

/** Every call node in `graphs` that calls `graphId`, in graph order then node order. */
export function graphCallers(
  graphs: readonly GraphDefinition[],
  graphId: string,
): CallSite[] {
  const sites: CallSite[] = [];
  for (const graph of graphs) {
    for (const node of graph.document.nodes) {
      if (isCallNode(node) && node.operator_id === graphId) {
        sites.push({ graphId: graph.id, nodeId: node.id });
      }
    }
  }
  return sites;
}

/** The distinct sibling Graph ids each Graph of `graphs` calls. */
function calleeMap(graphs: readonly GraphDefinition[]): Map<string, string[]> {
  const held = new Set(graphs.map((graph) => graph.id));
  const callees = new Map<string, string[]>();
  for (const graph of graphs) {
    const called: string[] = [];
    for (const node of graph.document.nodes) {
      // A call to a Graph this Project does not hold is a broken document, not
      // an edge in the call relation.
      if (!isCallNode(node) || !held.has(node.operator_id)) continue;
      if (!called.includes(node.operator_id)) called.push(node.operator_id);
    }
    callees.set(graph.id, called);
  }
  return callees;
}

/**
 * True when adding a call from `callerId` to `calleeId` would break acyclicity.
 *
 * A Graph never calls itself, and a Graph cannot call one that already reaches
 * it: walking the existing calls out from `calleeId` has to come back to
 * `callerId` for the new edge to close a cycle.
 */
export function wouldCreateCycle(
  graphs: readonly GraphDefinition[],
  callerId: string,
  calleeId: string,
): boolean {
  if (callerId === calleeId) return true;
  const callees = calleeMap(graphs);
  const seen = new Set<string>([calleeId]);
  const pending = [calleeId];
  while (pending.length > 0) {
    const current = pending.shift() as string;
    if (current === callerId) return true;
    for (const callee of callees.get(current) ?? []) {
      if (seen.has(callee)) continue;
      seen.add(callee);
      pending.push(callee);
    }
  }
  return false;
}

/** The sibling Graphs `callerId` may call, in graph order. */
export function callableGraphs(
  graphs: readonly GraphDefinition[],
  callerId: string,
): GraphDefinition[] {
  const allowed: GraphDefinition[] = [];
  for (const graph of graphs) {
    if (graph.id === callerId) continue;
    if (wouldCreateCycle(graphs, callerId, graph.id)) continue;
    allowed.push(graph);
  }
  return allowed;
}

/**
 * Why `graphId` cannot be deleted, or null when it can.
 *
 * The way back from a deletion is checkpoint restore, so a Graph with callers
 * is refused rather than silently detached: the caller has to drop its call
 * nodes first.
 */
export function graphDeleteRefusal(
  graphs: readonly GraphDefinition[],
  graphId: string,
): string | null {
  const graph = graphs.find((candidate) => candidate.id === graphId);
  if (!graph) return null;
  const callers: string[] = [];
  for (const site of graphCallers(graphs, graphId)) {
    // A call node inside the Graph itself cannot exist; it is not a caller.
    if (site.graphId === graphId) continue;
    if (callers.includes(site.graphId)) continue;
    callers.push(site.graphId);
  }
  if (callers.length === 0) return null;
  const named = callers
    .map((callerId) => {
      const caller = graphs.find((candidate) => candidate.id === callerId);
      return `“${caller?.name ?? callerId}”`;
    })
    .join(", ");
  return `“${graph.name}” is still called from ${named}. Remove those call nodes first.`;
}

/**
 * A boundary name this Graph does not use yet for that direction:
 * `input` / `output`, then `input_2`, `input_3`, …
 */
export function nextBoundaryName(
  graph: GraphDefinition,
  direction: "input" | "output",
): string {
  const operatorId =
    direction === "input" ? GRAPH_INPUT_OPERATOR_ID : GRAPH_OUTPUT_OPERATOR_ID;
  const taken = new Set<string>();
  for (const node of graph.document.nodes) {
    if (!isBoundaryNode(node) || node.operator_id !== operatorId) continue;
    taken.add(configText(node, "public_name") ?? "");
  }
  if (!taken.has(direction)) return direction;
  for (let suffix = 2; ; suffix += 1) {
    const candidate = `${direction}_${suffix}`;
    if (!taken.has(candidate)) return candidate;
  }
}

/** The single `value` port of a boundary node, typed by the config's binding. */
function boundaryPort(direction: Port["direction"]): Port {
  return {
    name: GRAPH_BOUNDARY_PORT,
    title: "Value",
    description: null,
    direction,
    artifact_type: null,
    artifact_type_variable: GRAPH_ARTIFACT_TYPE_VARIABLE,
    shape: "one",
    accepted_shapes: ["one"],
    instance_plugs: false,
    variadic: false,
    required: true,
  };
}

/** The config a boundary node carries: its public name and its description. */
function boundaryConfigSchema(
  withRequired: boolean,
): NodeSpec["config_schema"] {
  const properties: Record<string, unknown> = {
    public_name: {
      type: "string",
      title: "Name",
      description: "How callers address this input.",
      pattern: "^[a-z][a-z0-9_]*$",
    },
  };
  if (withRequired) {
    properties.required = { type: "boolean", title: "Required", default: true };
  }
  properties.description = { type: "string", title: "Description" };
  return { type: "object", required: ["public_name"], properties };
}

/** Catalog specs for the two boundary operators. */
export function boundaryNodeSpecs(): NodeSpec[] {
  return [
    {
      operator_id: GRAPH_INPUT_OPERATOR_ID,
      operator_version: GRAPH_BOUNDARY_OPERATOR_VERSION,
      plugin_slug: PROJECT_GRAPHS_PLUGIN_SLUG,
      origin: "builtin",
      title: "Graph input",
      description: "A value this Graph receives from whoever calls it.",
      inputs: [],
      outputs: [boundaryPort("output")],
      config_schema: boundaryConfigSchema(true),
      input_schema: {},
      output_schema: {},
      runnable: true,
      catalog_visible: true,
    },
    {
      operator_id: GRAPH_OUTPUT_OPERATOR_ID,
      operator_version: GRAPH_BOUNDARY_OPERATOR_VERSION,
      plugin_slug: PROJECT_GRAPHS_PLUGIN_SLUG,
      origin: "builtin",
      title: "Graph output",
      description: "A value this Graph hands back to whoever calls it.",
      inputs: [boundaryPort("input")],
      outputs: [],
      config_schema: boundaryConfigSchema(false),
      input_schema: {},
      output_schema: {},
      runnable: true,
      catalog_visible: true,
    },
  ];
}

/** The spec a call node to `graph` shows: its interface as ports. */
export function callNodeSpec(
  graph: GraphDefinition,
  catalogVisible: boolean,
): NodeSpec {
  const face = graphInterface(graph);
  const inputs: Port[] = face.inputs.map((port) => ({
    name: port.name,
    title: port.name,
    description: port.description,
    direction: "input",
    artifact_type: port.artifactType,
    artifact_type_variable: null,
    shape: "one",
    accepted_shapes: ["one"],
    instance_plugs: false,
    variadic: false,
    required: port.required,
  }));
  const outputs: Port[] = face.outputs.map((port) => ({
    name: port.name,
    title: port.name,
    description: port.description,
    direction: "output",
    artifact_type: port.artifactType,
    artifact_type_variable: null,
    shape: "one",
    accepted_shapes: ["one"],
    instance_plugs: false,
    variadic: false,
    required: true,
  }));
  return {
    operator_id: graph.id,
    operator_version: CALL_NODE_OPERATOR_VERSION,
    plugin_slug: PROJECT_GRAPHS_PLUGIN_SLUG,
    origin: "builtin",
    title: graph.name,
    description: `Runs the Graph “${graph.name}” as one step.`,
    config_schema: {},
    input_schema: {},
    output_schema: {},
    runnable: true,
    catalog_visible: catalogVisible,
    inputs,
    outputs,
  };
}

/**
 * `registry` extended with the Graphs of this Project as catalog entries.
 *
 * Boundary operators are always offered; a call node is offered for every other
 * Graph, and only for those that may be called without making a cycle. A Graph
 * that is not visible still gets a spec so a saved call node in the document
 * finds its ports — with `openGraphId` null nothing is offered, but every Graph
 * is still described.
 */
export function registryWithProjectGraphs(
  registry: NodeRegistry,
  graphs: readonly GraphDefinition[],
  openGraphId: string | null,
): NodeRegistry {
  const callable = new Set<string>();
  if (openGraphId !== null) {
    for (const graph of callableGraphs(graphs, openGraphId)) {
      callable.add(graph.id);
    }
  }
  const specs = boundaryNodeSpecs();
  for (const graph of graphs) {
    if (graph.id === openGraphId) continue;
    specs.push(callNodeSpec(graph, callable.has(graph.id)));
  }
  const hasPlugin = registry.plugins.some(
    (plugin: PluginSpec) => plugin.slug === PROJECT_GRAPHS_PLUGIN_SLUG,
  );
  const plugins: PluginSpec[] = hasPlugin
    ? [...registry.plugins]
    : [
        ...registry.plugins,
        {
          entry_kind: "plugin",
          origin: "builtin",
          slug: PROJECT_GRAPHS_PLUGIN_SLUG,
          title: "Graphs in this Project",
        },
      ];
  return { ...registry, plugins, nodes: [...registry.nodes, ...specs] };
}
