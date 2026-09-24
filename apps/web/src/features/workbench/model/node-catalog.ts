import type {
  ArtifactTypeKey,
  ArtifactTypeSpec,
  NodeRegistry,
  NodeSpec,
  PluginReleasePin,
  Port,
} from "@/lib/api";

import {
  connectionRoutesFor,
  encodeHandleId,
  type ConnectionRoute,
  type HandleFeedIntent,
} from "../canvas/handles";
import { schemaFields } from "../canvas/config-schema";
import {
  acceptedPortShapes,
  portArtifactType,
  portArtifactTypeVariable,
  portHasInstancePlugs,
  portMetaForPort,
} from "../canvas/types";
import { routesForHandleFeed } from "./connection-feeds";

export type CatalogFilterKind =
  | "all"
  | "artifact"
  | "single"
  | "sequence"
  | "any-artifact"
  | "source"
  | "input-nodes"
  | "workspace-library";

export type CatalogFilterId =
  | "all"
  | "single"
  | "sequence"
  | "any-artifact"
  | "input-nodes"
  | "workspace-library"
  | `artifact:${string}@${number}`
  | `source:${string}`;

export interface CatalogFilter {
  id: CatalogFilterId;
  kind: CatalogFilterKind;
  title: string;
  artifactKey?: ArtifactTypeKey;
  /** Provider plugin slug, set for `source` filters. */
  sourceKey?: string;
}

export interface ContextualRouteChoice {
  /** Port on the candidate (new) node that participates in the edge. */
  candidatePort: Port;
  route: ConnectionRoute;
  collectionMode: "direct" | "map";
  /** True when the candidate node's input needs an ordered instance plug (downstream inserts). */
  usesInstancePlug: boolean;
}

export interface ContextualCandidate {
  spec: NodeSpec;
  choices: readonly ContextualRouteChoice[];
}

const MODULE_PLUGIN_SLUG = "graph.module";

export function catalogNodeKey(spec: NodeSpec): string {
  const operator = `${spec.operator_id}@${spec.operator_version}`;
  return spec.plugin_release
    ? `plugin-release:${spec.plugin_release.scope}:${spec.plugin_release.slug}:${operator}`
    : operator;
}

export function artifactTypeKeyId(key: ArtifactTypeKey): string {
  return `${key.id}@${key.schema_version}`;
}

export function artifactFilterId(key: ArtifactTypeKey): CatalogFilterId {
  return `artifact:${key.id}@${key.schema_version}`;
}

export function sourceFilterId(slug: string): CatalogFilterId {
  return `source:${slug}`;
}

/** Restricts results to nodes that take no inputs because they are inputs themselves. */
export const INPUT_NODES_FILTER: CatalogFilter = {
  id: "input-nodes",
  kind: "input-nodes",
  title: "Input nodes",
};

function pluginFor(
  registry: NodeRegistry,
  slug: string,
): NodeRegistry["plugins"][number] {
  const plugin = registry.plugins.find((candidate) => candidate.slug === slug);
  if (!plugin) {
    throw new Error(`Node registry is missing owner plugin "${slug}".`);
  }
  return plugin;
}

function portDeclaresArtifact(port: Port, key: ArtifactTypeKey): boolean {
  const artifactType = portArtifactType(port);
  return (
    artifactType?.id === key.id &&
    artifactType.schema_version === key.schema_version
  );
}

function portIsAnyArtifact(port: Port): boolean {
  return (
    portArtifactTypeVariable(port) != null && portArtifactType(port) == null
  );
}

function nodeDeclaresArtifact(spec: NodeSpec, key: ArtifactTypeKey): boolean {
  return [...spec.inputs, ...spec.outputs].some((port) =>
    portDeclaresArtifact(port, key),
  );
}

function nodeMatchesShapeFilter(spec: NodeSpec, shape: Port["shape"]): boolean {
  if (spec.outputs.some((port) => port.shape === shape)) return true;
  return spec.inputs.some((port) => acceptedPortShapes(port).includes(shape));
}

function nodeMatchesAnyArtifact(spec: NodeSpec): boolean {
  return [...spec.inputs, ...spec.outputs].some(portIsAnyArtifact);
}

function isWorkspaceLibraryNode(spec: NodeSpec): boolean {
  return Boolean(
    spec.module_graph_id || spec.plugin_slug === MODULE_PLUGIN_SLUG,
  );
}

function artifactTitle(registry: NodeRegistry, key: ArtifactTypeKey): string {
  return (
    registry.artifact_types.find(
      (artifact) =>
        artifact.key.id === key.id &&
        artifact.key.schema_version === key.schema_version,
    )?.title ?? key.id
  );
}

/** Build the source categories: every provider plugin that ships nodes, plus the workspace library. */
export function buildSourceFilters(
  registry: NodeRegistry,
): readonly CatalogFilter[] {
  const slugsWithNodes = new Set(
    registry.nodes.map((spec) => spec.plugin_slug),
  );
  const sources = registry.plugins
    .filter(
      (plugin) => plugin.origin !== "module" && slugsWithNodes.has(plugin.slug),
    )
    .slice()
    .sort(
      (left, right) =>
        left.title.localeCompare(right.title) ||
        left.slug.localeCompare(right.slug),
    );

  return [
    { id: "all", kind: "all", title: "All" },
    ...sources.map((plugin): CatalogFilter => ({
      id: sourceFilterId(plugin.slug),
      kind: "source",
      title: plugin.title || "System",
      sourceKey: plugin.slug,
    })),
    {
      id: "workspace-library",
      kind: "workspace-library",
      title: "Workspace library",
    },
  ];
}

/** Build browse filters from registered artifact types plus fixed shape/library filters. */
export function buildCatalogFilters(
  registry: NodeRegistry,
): readonly CatalogFilter[] {
  const titleCounts = new Map<string, number>();
  for (const artifact of registry.artifact_types) {
    titleCounts.set(artifact.title, (titleCounts.get(artifact.title) ?? 0) + 1);
  }

  const artifactFilters = [...registry.artifact_types]
    .slice()
    .sort((left, right) => {
      const byTitle = left.title.localeCompare(right.title);
      if (byTitle !== 0) return byTitle;
      return artifactTypeKeyId(left.key).localeCompare(
        artifactTypeKeyId(right.key),
      );
    })
    .map((artifact): CatalogFilter => {
      const showVersion = (titleCounts.get(artifact.title) ?? 0) > 1;
      return {
        id: artifactFilterId(artifact.key),
        kind: "artifact",
        title: showVersion
          ? `${artifact.title} · v${artifact.key.schema_version}`
          : artifact.title,
        artifactKey: artifact.key,
      };
    });

  return [
    { id: "all", kind: "all", title: "All nodes" },
    ...artifactFilters,
    { id: "single", kind: "single", title: "Single value" },
    { id: "sequence", kind: "sequence", title: "Sequence" },
    { id: "any-artifact", kind: "any-artifact", title: "Any artifact" },
    {
      id: "workspace-library",
      kind: "workspace-library",
      title: "Workspace library",
    },
  ];
}

export function catalogNodesForFilter(
  nodes: readonly NodeSpec[],
  filter: CatalogFilter,
): readonly NodeSpec[] {
  switch (filter.kind) {
    case "all":
      return nodes;
    case "artifact":
      return filter.artifactKey
        ? nodes.filter((spec) =>
            nodeDeclaresArtifact(spec, filter.artifactKey!),
          )
        : [];
    case "single":
      return nodes.filter((spec) => nodeMatchesShapeFilter(spec, "one"));
    case "sequence":
      return nodes.filter((spec) => nodeMatchesShapeFilter(spec, "many"));
    case "any-artifact":
      return nodes.filter(nodeMatchesAnyArtifact);
    case "source":
      return filter.sourceKey
        ? nodes.filter((spec) => spec.plugin_slug === filter.sourceKey)
        : [];
    case "input-nodes":
      return nodes.filter((spec) => spec.inputs.length === 0);
    case "workspace-library":
      return nodes.filter(isWorkspaceLibraryNode);
  }
}

export function sortCatalogNodes(nodes: readonly NodeSpec[]): NodeSpec[] {
  return nodes.slice().sort((left, right) => {
    const byTitle = left.title.localeCompare(right.title);
    if (byTitle !== 0) return byTitle;
    const byOperator = left.operator_id.localeCompare(right.operator_id);
    if (byOperator !== 0) return byOperator;
    return left.operator_version - right.operator_version;
  });
}

export function nodeCatalogSearchText(
  spec: NodeSpec,
  registry: NodeRegistry,
): string {
  const plugin = pluginFor(registry, spec.plugin_slug);
  const fields = schemaFields(spec.config_schema);
  return [
    spec.title,
    spec.operator_id,
    spec.description,
    spec.plugin_slug,
    plugin.title,
    plugin.entry_kind,
    plugin.origin,
    plugin.scope ?? "",
    ...spec.inputs.flatMap((port) => portSearchTerms(port, registry)),
    ...spec.outputs.flatMap((port) => portSearchTerms(port, registry)),
    ...fields.flatMap((field) => [
      field.name,
      field.title,
      field.description ?? "",
      ...(field.enumValues?.map(String) ?? []),
    ]),
  ]
    .join(" ")
    .toLowerCase();
}

function portSearchTerms(port: Port, registry: NodeRegistry): string[] {
  const artifactType = portArtifactType(port);
  return [
    port.name,
    port.title ?? "",
    port.description ?? "",
    artifactType ? artifactTitle(registry, artifactType) : "any artifact",
    artifactType?.id ?? "any artifact generic",
    portArtifactTypeVariable(port) ?? "",
    port.instance_plugs ? "collect ordered input plugs" : "",
    ...(port.accepted_shapes ?? []).map((shape) =>
      shape === "many" ? "sequence" : "single",
    ),
  ];
}

export function searchCatalogNodes(
  nodes: readonly NodeSpec[],
  query: string,
  registry: NodeRegistry,
): readonly NodeSpec[] {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return nodes;
  return nodes.filter((spec) =>
    nodeCatalogSearchText(spec, registry).includes(normalized),
  );
}

export function filterAndSearchCatalogNodes(
  nodes: readonly NodeSpec[],
  filters: readonly CatalogFilter[],
  query: string,
  registry: NodeRegistry,
): readonly NodeSpec[] {
  const filtered = filters.reduce(
    (acc, filter) =>
      filter.kind === "all" ? acc : catalogNodesForFilter(acc, filter),
    nodes,
  );
  return sortCatalogNodes(searchCatalogNodes(filtered, query, registry));
}

export function catalogNodeSpecs(
  registry: NodeRegistry,
  activeGraphId: string | null,
): readonly NodeSpec[] {
  return registry.nodes.filter(
    (spec) =>
      spec.catalog_visible !== false &&
      (activeGraphId === null || spec.module_graph_id !== activeGraphId),
  );
}

/** Compact purpose-oriented port summary for result rows. */
export function catalogNodePortSummary(
  spec: NodeSpec,
  registry: NodeRegistry,
): string {
  const inputLabels = spec.inputs.map((port) => portLabel(port, registry));
  const outputLabels = spec.outputs.map((port) => portLabel(port, registry));
  const inputs =
    inputLabels.length === 0
      ? "—"
      : inputLabels.length <= 2
        ? inputLabels.join(", ")
        : `${inputLabels.slice(0, 2).join(", ")} +${inputLabels.length - 2}`;
  const outputs =
    outputLabels.length === 0
      ? "—"
      : outputLabels.length <= 2
        ? outputLabels.join(", ")
        : `${outputLabels.slice(0, 2).join(", ")} +${outputLabels.length - 2}`;
  return `${inputs} → ${outputs}`;
}

function portLabel(port: Port, registry: NodeRegistry): string {
  const artifactType = portArtifactType(port);
  if (!artifactType) return "Any";
  return artifactTitle(registry, artifactType);
}

export function catalogNodeProviderLabel(
  spec: NodeSpec,
  registry: NodeRegistry,
): string {
  const plugin = pluginFor(registry, spec.plugin_slug);
  if (plugin.origin === "module" || plugin.entry_kind === "module") {
    const state = spec.publication_state ?? "published";
    return `Module · release ${spec.module_graph_revision} · ${state}`;
  }
  if (plugin.origin === "builtin") return plugin.title || "Built-in";
  if (plugin.scope === "workspace") return `${plugin.title} · Workspace`;
  return plugin.title || "Plugin";
}

/** All published releases for a module (including non-current). */
export function moduleReleaseSpecs(
  registry: NodeRegistry,
  moduleId: string | null | undefined,
  moduleGraphId: string | null | undefined,
): readonly NodeSpec[] {
  return registry.nodes
    .filter((spec) => {
      if (moduleId && spec.module_id === moduleId) return true;
      if (
        !moduleId &&
        moduleGraphId &&
        spec.module_graph_id === moduleGraphId
      ) {
        return true;
      }
      return false;
    })
    .slice()
    .sort(
      (left, right) =>
        (right.module_graph_revision ?? 0) - (left.module_graph_revision ?? 0),
    );
}

/** Current library release when the pinned call is behind it; otherwise null. */
export function moduleCallUpgradeTarget(
  registry: NodeRegistry,
  pinned: NodeSpec,
): NodeSpec | null {
  if (!pinned.module_graph_id) return null;
  const current = moduleReleaseSpecs(
    registry,
    pinned.module_id,
    pinned.module_graph_id,
  ).find((release) => release.is_current_library_release);
  if (!current) return null;
  if (
    current.operator_id === pinned.operator_id &&
    current.operator_version === pinned.operator_version
  ) {
    return null;
  }
  return current;
}

/** Current exact release when it advances the same scoped Plugin identity. */
export function pluginReleaseUpgradeTarget(
  current: NodeSpec,
  pinned: PluginReleasePin | null,
): PluginReleasePin | null {
  const release = current.plugin_release;
  if (
    !release ||
    !pinned ||
    release.scope !== pinned.scope ||
    release.slug !== pinned.slug ||
    release.revision <= pinned.revision
  ) {
    return null;
  }
  return {
    scope: release.scope,
    slug: release.slug,
    revision: release.revision,
  };
}

function shapesAreCompatible(source: Port, target: Port): boolean {
  const acceptedShapes = acceptedPortShapes(target);
  return (
    acceptedShapes.includes(source.shape) ||
    (!portHasInstancePlugs(target) &&
      source.shape === "many" &&
      acceptedShapes.includes("one"))
  );
}

function collectionModeForPorts(
  source: Port,
  target: Port,
): "direct" | "map" | null {
  const acceptedShapes = acceptedPortShapes(target);
  if (acceptedShapes.includes(source.shape)) return "direct";
  if (
    !portHasInstancePlugs(target) &&
    source.shape === "many" &&
    acceptedShapes.includes("one")
  ) {
    return "map";
  }
  return null;
}

const DISCOVERY_INSTANCE_PLUG_ID = "discovery-instance-plug";

function targetHandleForRoute(
  target: Port,
  plugId: string | undefined,
): string {
  return encodeHandleId(portMetaForPort(target, target.shape, plugId));
}

/**
 * Downstream nodes with at least one valid typed route from an exact source
 * output handle. Uses existing connection route calculation.
 */
export function downstreamCandidatesFromOutput(options: {
  sourcePort: Port & { readonly direction: "output" };
  sourceHandle: string;
  sourceFeed?: HandleFeedIntent | null;
  registry: NodeRegistry;
  nodes: readonly NodeSpec[];
  artifactTypes?: readonly ArtifactTypeSpec[];
}): ContextualCandidate[] {
  const {
    sourcePort,
    sourceHandle,
    sourceFeed = null,
    registry,
    nodes,
  } = options;
  const artifactTypes = options.artifactTypes ?? registry.artifact_types;
  const conversions = registry.artifact_conversions;
  const candidates: ContextualCandidate[] = [];

  for (const spec of sortCatalogNodes(nodes)) {
    const choices: ContextualRouteChoice[] = [];

    for (const input of spec.inputs) {
      if (input.direction !== "input") continue;
      if (!shapesAreCompatible(sourcePort, input)) continue;

      const collectionMode = collectionModeForPorts(sourcePort, input);
      if (!collectionMode) continue;

      const usesInstancePlug = portHasInstancePlugs(input);
      // Optional instance-plug inputs get no initial plug on a newly created node.
      if (usesInstancePlug && !input.required) continue;

      const allRoutes = connectionRoutesFor(
        {
          sourceHandle,
          targetHandle: targetHandleForRoute(
            input,
            usesInstancePlug ? DISCOVERY_INSTANCE_PLUG_ID : undefined,
          ),
        },
        artifactTypes,
        conversions,
      );
      const routes = routesForHandleFeed(allRoutes, sourceFeed ?? undefined);
      for (const route of routes) {
        choices.push({
          candidatePort: input as Port & { readonly direction: "input" },
          route,
          collectionMode,
          usesInstancePlug,
        });
      }
    }

    if (choices.length) {
      candidates.push({ spec, choices });
    }
  }

  return candidates;
}

/**
 * Upstream nodes with at least one valid typed route into an exact input
 * handle. Mirrors {@link downstreamCandidatesFromOutput} for the reverse
 * direction: drag from an input port and drop on the canvas.
 */
export function upstreamCandidatesFromInput(options: {
  targetPort: Port & { readonly direction: "input" };
  targetHandle: string;
  registry: NodeRegistry;
  nodes: readonly NodeSpec[];
}): ContextualCandidate[] {
  const { targetPort, targetHandle, registry, nodes } = options;
  const artifactTypes = registry.artifact_types;
  const conversions = registry.artifact_conversions;
  const candidates: ContextualCandidate[] = [];

  for (const spec of sortCatalogNodes(nodes)) {
    const choices: ContextualRouteChoice[] = [];

    for (const output of spec.outputs) {
      if (output.direction !== "output") continue;
      if (!shapesAreCompatible(output, targetPort)) continue;

      const collectionMode = collectionModeForPorts(output, targetPort);
      if (!collectionMode) continue;

      const allRoutes = connectionRoutesFor(
        {
          sourceHandle: encodeHandleId(portMetaForPort(output)),
          targetHandle,
        },
        artifactTypes,
        conversions,
      );
      for (const route of allRoutes) {
        choices.push({
          candidatePort: output as Port & { readonly direction: "output" },
          route,
          collectionMode,
          usesInstancePlug: false,
        });
      }
    }

    if (choices.length) {
      candidates.push({ spec, choices });
    }
  }

  return candidates;
}

export function nodesCompatibleWithPort(
  nodes: readonly NodeSpec[],
  compatibility: {
    direction: "upstream" | "downstream";
    port: Port;
  },
  registry: NodeRegistry,
): readonly NodeSpec[] {
  return nodes.filter((spec) => {
    if (compatibility.direction === "upstream") {
      return spec.outputs.some((output) =>
        portsCanConnect(output, compatibility.port, registry),
      );
    }
    return spec.inputs.some((input) =>
      portsCanConnect(compatibility.port, input, registry),
    );
  });
}

function portsCanConnect(
  source: Port,
  target: Port,
  registry: NodeRegistry,
): boolean {
  if (!shapesAreCompatible(source, target)) return false;
  if (portHasInstancePlugs(target) && !target.required) return false;
  const plugId = portHasInstancePlugs(target) ? "discovery-plug" : undefined;
  return (
    connectionRoutesFor(
      {
        sourceHandle: encodeHandleId(portMetaForPort(source)),
        targetHandle: encodeHandleId(
          portMetaForPort(target, target.shape, plugId),
        ),
      },
      registry.artifact_types,
      registry.artifact_conversions,
    ).length > 0
  );
}
