import type {
  ArtifactConversionSpec,
  ArtifactTypeSpec,
  NodeSpec,
  SavedGraphEdge,
  SavedGraphNode,
  SavedGraphOrigin,
} from "@/lib/api";

import type { ArtifactCardValue } from "../artifacts/artifact-card";
import {
  artifactTypeKey,
  type ArtifactTypeIdentity,
} from "../artifacts/artifact-type-key";
import type {
  ConnectedInputPortInfo,
  ConnectedInputPortMap,
} from "./config-schema";
import type { WorkflowEdgeConversionPath } from "../authoring/types";

export type {
  ConnectedInputPortInfo,
  ConnectedInputPortMap,
} from "./config-schema";

function conversionTarget(
  path:
    WorkflowEdgeConversionPath | SavedGraphEdge["conversion_path"] | undefined,
  conversions: readonly ArtifactConversionSpec[],
): ArtifactTypeIdentity | undefined {
  const last = path?.at(-1);
  if (!last) return undefined;
  return conversions.find(
    ({ key }) => key.id === last.id && key.version === last.version,
  )?.target_artifact_type;
}

function refArtifactType(value: ArtifactCardValue): ArtifactTypeIdentity {
  return { id: value.artifact_type, schema_version: value.schema_version };
}

/** The field a projection reads out of `type`, or `type` when there is none. */
function projectedArtifactType(
  type: ArtifactTypeIdentity | null,
  path: readonly string[] | undefined,
  artifactTypes: readonly ArtifactTypeSpec[],
): ArtifactTypeIdentity | null {
  if (!type || !path) return type;

  const sourceSpec = artifactTypes.find(
    ({ key }) => artifactTypeKey(key) === artifactTypeKey(type),
  );
  const projection = sourceSpec?.field_projections.find(
    (candidate) =>
      candidate.path.length === path.length &&
      candidate.path.every((segment, index) => segment === path[index]),
  );
  return projection?.target_artifact_type ?? type;
}

interface DocumentConnectedInputPortsOptions {
  nodeId: string;
  spec: Pick<NodeSpec, "inputs">;
  edges: readonly SavedGraphEdge[];
  origins: readonly SavedGraphOrigin[];
  /** Spec and bindings of each source node, by id, to type what it sends. */
  sources: ReadonlyMap<
    string,
    {
      node: Pick<SavedGraphNode, "artifact_type_bindings">;
      spec: Pick<NodeSpec, "outputs"> | undefined;
    }
  >;
  conversions?: readonly ArtifactConversionSpec[];
  artifactTypes?: readonly ArtifactTypeSpec[];
}

/**
 * Report active inputs and the first known delivered artifact type for each
 * port on an authored graph document node: an enabled edge or an origin
 * connects a port, and the first typed delivery names what the port receives.
 */
export function connectedInputPortsForDocumentNode({
  nodeId,
  spec,
  edges,
  origins,
  sources,
  conversions = [],
  artifactTypes = [],
}: DocumentConnectedInputPortsOptions): ConnectedInputPortMap {
  const inputs = new Map<string, ConnectedInputPortInfo>(
    spec.inputs.map(({ name }) => [
      name,
      { connected: false, artifactTypeKey: null },
    ]),
  );

  function connect(port: string, type: ArtifactTypeIdentity | null) {
    const previous = inputs.get(port);
    if (!previous || previous.artifactTypeKey !== null) return;
    inputs.set(port, {
      connected: true,
      artifactTypeKey: type ? artifactTypeKey(type) : null,
    });
  }

  for (const edge of edges) {
    if (edge.to_node !== nodeId || edge.enabled === false) continue;
    const converted = conversionTarget(edge.conversion_path, conversions);
    if (converted) {
      connect(edge.to_port, converted);
      continue;
    }
    const source = sources.get(edge.from_node);
    const port = source?.spec?.outputs.find(
      ({ name }) => name === edge.from_port,
    );
    const variable = port?.artifact_type_variable;
    const bound = variable
      ? source?.node.artifact_type_bindings.find(
          (binding) => binding.variable === variable,
        )?.artifact_type
      : undefined;
    connect(
      edge.to_port,
      projectedArtifactType(
        bound ?? port?.artifact_type ?? null,
        edge.projection?.path,
        artifactTypes,
      ),
    );
  }

  for (const origin of origins) {
    if (origin.to_node !== nodeId) continue;
    const type =
      conversionTarget(origin.conversion_path, conversions) ??
      refArtifactType(origin.value);
    connect(origin.to_port, type);
  }

  return Object.fromEntries(inputs);
}
