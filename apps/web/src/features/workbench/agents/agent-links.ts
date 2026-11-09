import type {
  ArtifactTypeKey,
  NodeRegistry,
  NodeSpec,
  Port,
  SavedGraphAgent,
  SavedGraphEdge,
  SavedGraphNode,
  SavedGraphOrigin,
} from "@/lib/api";
import { artifactTypeKey } from "../canvas/artifact-type-key";
import { createUuid } from "../model/uuid";

/**
 * What is connected to an Agent, as pure edits of the Agent (ADR 0021).
 *
 * A tool link names a node of this Graph; the inputs the model fills are the node's *open*
 * inputs (nothing is wired or held there) of a type a model can write in a call, and an
 * input the operator hides by default is left to the Graph unless a person offers it. The
 * server applies the same rules when it builds the tool, so what this offers is what will be
 * callable; a link the server cannot honour is reported to the person as unavailable.
 */

/** The part of a Graph's document that says which inputs are open. */
export interface LinkableDocument {
  readonly nodes: readonly SavedGraphNode[];
  readonly edges: readonly SavedGraphEdge[];
  readonly origins?: readonly SavedGraphOrigin[];
}

export type AgentToolLink = SavedGraphAgent["tools"][number];
export type AgentContextLink = SavedGraphAgent["context"][number];

/** Artifact types a model can write as a bare value: text and integers. */
export function writableArtifactTypes(
  registry: NodeRegistry,
): ReadonlySet<string> {
  return new Set(
    registry.artifact_types
      .filter((spec) => spec.materialized_json_type != null)
      .map((spec) => artifactTypeKey(spec.key)),
  );
}

function portArtifactType(
  port: Port,
  node: SavedGraphNode,
): ArtifactTypeKey | null {
  if (port.artifact_type) return port.artifact_type;
  const variable = port.artifact_type_variable;
  if (!variable) return null;
  const binding = node.artifact_type_bindings.find(
    (candidate) => candidate.variable === variable,
  );
  return binding ? binding.artifact_type : null;
}

/** The inputs of `node` with nothing wired to them and no value held on them. */
export function openInputPorts(
  node: SavedGraphNode,
  spec: NodeSpec,
  document: LinkableDocument,
): string[] {
  const fed = new Set<string>();
  for (const edge of document.edges) {
    if (edge.enabled && edge.to_node === node.id) fed.add(edge.to_port);
  }
  for (const origin of document.origins ?? []) {
    if (origin.to_node === node.id) fed.add(origin.to_port);
  }
  return spec.inputs.map((port) => port.name).filter((name) => !fed.has(name));
}

export interface ToolInputChoice {
  readonly name: string;
  readonly title: string;
  /** Whether the model fills it in this link. */
  readonly filled: boolean;
  /** Whether it can be offered at all, and if not, why not. */
  readonly offerable: boolean;
  readonly reason: string | null;
}

export interface ToolOutputChoice {
  readonly name: string;
  readonly title: string;
  readonly returned: boolean;
}

/** One tool link's ports, each with what a person may choose about it. */
export function toolPortChoices(
  link: AgentToolLink,
  node: SavedGraphNode,
  spec: NodeSpec,
  document: LinkableDocument,
  registry: NodeRegistry,
): { inputs: ToolInputChoice[]; outputs: ToolOutputChoice[] } {
  const open = new Set(openInputPorts(node, spec, document));
  const writable = writableArtifactTypes(registry);
  const inputs = spec.inputs.map((port): ToolInputChoice => {
    const type = portArtifactType(port, node);
    let reason: string | null = null;
    if (!open.has(port.name)) reason = "Already fed by the Graph";
    else if (type === null || !writable.has(artifactTypeKey(type))) {
      reason = "A model can only write text or numbers";
    }
    return {
      name: port.name,
      title: port.title ?? port.name,
      filled: link.filled_ports.includes(port.name),
      offerable: reason === null,
      reason,
    };
  });
  const returnsAll = link.returned_ports.length === 0;
  const outputs = spec.outputs.map((port): ToolOutputChoice => ({
    name: port.name,
    title: port.title ?? port.name,
    returned: returnsAll || link.returned_ports.includes(port.name),
  }));
  return { inputs, outputs };
}

/** A name a model can call: lower-case words, unique among the Agent's tools. */
export function uniqueToolName(
  title: string,
  taken: readonly string[],
): string {
  const base =
    title
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      // A name starts with a letter and does not end on a separator.
      .replace(/^[^a-z]+/, "")
      .slice(0, 44)
      .replace(/_+$/, "") || "tool";
  if (!taken.includes(base)) return base;
  for (let suffix = 2; ; suffix += 1) {
    const candidate = `${base}_${suffix}`;
    if (!taken.includes(candidate)) return candidate;
  }
}

/**
 * The link a node starts with: every open input a model can write and the operator does
 * not hide, and every output returned.
 */
export function newToolLink(
  agent: SavedGraphAgent,
  node: SavedGraphNode,
  spec: NodeSpec,
  document: LinkableDocument,
  registry: NodeRegistry,
): AgentToolLink {
  const blank: AgentToolLink = {
    id: `tool-${createUuid()}`,
    node_id: node.id,
    name: uniqueToolName(
      spec.title,
      agent.tools.map((tool) => tool.name),
    ),
    description: "",
    filled_ports: [],
    returned_ports: [],
  };
  const { inputs } = toolPortChoices(blank, node, spec, document, registry);
  const hidden = new Set(
    spec.inputs
      .filter((port) => port.agent_default === "hidden")
      .map((port) => port.name),
  );
  return {
    ...blank,
    filled_ports: inputs
      .filter((input) => input.offerable && !hidden.has(input.name))
      .map((input) => input.name),
  };
}

export function withTool(
  agent: SavedGraphAgent,
  link: AgentToolLink,
): SavedGraphAgent {
  return { ...agent, tools: [...agent.tools, link] };
}

export function withoutTool(
  agent: SavedGraphAgent,
  toolId: string,
): SavedGraphAgent {
  return {
    ...agent,
    tools: agent.tools.filter((tool) => tool.id !== toolId),
  };
}

export function withUpdatedTool(
  agent: SavedGraphAgent,
  toolId: string,
  patch: Partial<Omit<AgentToolLink, "id" | "node_id">>,
): SavedGraphAgent {
  return {
    ...agent,
    tools: agent.tools.map((tool) =>
      tool.id === toolId ? { ...tool, ...patch } : tool,
    ),
  };
}

export function withContext(
  agent: SavedGraphAgent,
  link: AgentContextLink,
): SavedGraphAgent {
  return { ...agent, context: [...agent.context, link] };
}

export function withoutContext(
  agent: SavedGraphAgent,
  linkId: string,
): SavedGraphAgent {
  return {
    ...agent,
    context: agent.context.filter((link) => link.id !== linkId),
  };
}

export function nodeOutputContext(
  nodeId: string,
  port: string,
): AgentContextLink {
  return {
    id: `context-${createUuid()}`,
    kind: "node_output",
    node_id: nodeId,
    port,
  };
}

export function cardContext(cardId: string): AgentContextLink {
  return { id: `context-${createUuid()}`, kind: "card", card_id: cardId };
}

export function libraryItemContext(libraryItemId: string): AgentContextLink {
  return {
    id: `context-${createUuid()}`,
    kind: "library_item",
    library_item_id: libraryItemId,
  };
}
