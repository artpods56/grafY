import type {
  ArtifactConversionSpec,
  ArtifactTypeKey,
  Port,
  SavedGraphOrigin,
} from "@/lib/api";
import {
  artifactTypeKey,
  decodeHandleId,
  shortestConversionPathsToAny,
} from "../canvas/handles";
import {
  acceptedPortShapes,
  resolvedPortArtifactType,
  type WorkflowEdge,
} from "../canvas/types";
import type { GraphCommand } from "./graph-document";
import { createUuid } from "./uuid";

export const ARTIFACT_DROP_DATA_TYPE = "application/x-grafy-artifact";

export type ArtifactDropValue = SavedGraphOrigin["value"];

export interface ArtifactDropPayload {
  readonly value: ArtifactDropValue;
  readonly shape: "one" | "many";
}

export interface ArtifactDropTarget {
  readonly nodeId: string;
  readonly portName: string;
  readonly plugId: string | null;
}

export interface ArtifactDropResolution {
  readonly conversionPath: readonly { id: string; version: number }[];
}

export interface ArtifactDropGraphState {
  readonly edges: readonly WorkflowEdge[];
  readonly origins: readonly SavedGraphOrigin[];
  readonly conversions: readonly ArtifactConversionSpec[];
}

export function artifactDropPayload(
  value: ArtifactDropValue,
): ArtifactDropPayload {
  return {
    value,
    shape: "item_refs" in value ? "many" : "one",
  };
}

export function writeArtifactDrop(
  dataTransfer: DataTransfer,
  value: ArtifactDropValue,
): void {
  dataTransfer.setData(
    ARTIFACT_DROP_DATA_TYPE,
    JSON.stringify(artifactDropPayload(value)),
  );
  dataTransfer.effectAllowed = "copy";
}

/** Whether one drag carries a Grafy artifact rather than page text or a file. */
export function isArtifactDrop(dataTransfer: DataTransfer): boolean {
  return Array.from(dataTransfer.types ?? []).includes(ARTIFACT_DROP_DATA_TYPE);
}

export function readArtifactDrop(
  dataTransfer: DataTransfer,
): ArtifactDropPayload | null {
  const raw = dataTransfer.getData(ARTIFACT_DROP_DATA_TYPE);
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return null;
    if (!("value" in parsed) || !("shape" in parsed)) return null;
    const value = parsed.value;
    const shape = parsed.shape;
    if (!value || typeof value !== "object") return null;
    if (shape !== "one" && shape !== "many") return null;
    if (shape === "many" && !("item_refs" in value)) return null;
    if (shape === "one" && "item_refs" in value) return null;
    return { value: value as ArtifactDropValue, shape };
  } catch {
    return null;
  }
}

/**
 * Read the drop target's live identity off its own row element. React Flow
 * writes `data-handleid` once at mount, so a handle attribute reports the row's
 * previous plug; the row carries the identity that is current at drop time.
 */
export function artifactDropTargetFromRow(
  row: HTMLElement,
): ArtifactDropTarget | null {
  const nodeId = row.dataset.inputNodeId;
  const portName = row.dataset.inputPortName ?? row.dataset.inputPlugPort;
  if (!nodeId || !portName) return null;
  return { nodeId, portName, plugId: row.dataset.inputPlugId ?? null };
}

function artifactTypeForValue(value: ArtifactDropValue): ArtifactTypeKey {
  return {
    id: value.artifact_type,
    schema_version: value.schema_version,
  };
}

export function resolveArtifactDrop(
  payload: ArtifactDropPayload,
  port: Port,
  bindings: Readonly<Record<string, ArtifactTypeKey>>,
  conversions: readonly ArtifactConversionSpec[],
): ArtifactDropResolution | null {
  if (port.direction !== "input") return null;
  if (!acceptedPortShapes(port).includes(payload.shape)) return null;
  const source = artifactTypeForValue(payload.value);
  const accepted = [
    resolvedPortArtifactType(port, bindings),
    ...(port.also_accepts ?? []),
  ].filter((candidate): candidate is ArtifactTypeKey => candidate !== null);
  if (!accepted.length) return null;
  if (
    accepted.some(
      (candidate) => artifactTypeKey(candidate) === artifactTypeKey(source),
    )
  ) {
    return { conversionPath: [] };
  }
  const paths = shortestConversionPathsToAny(source, accepted, conversions);
  if (!paths || paths.length !== 1) return null;
  return {
    conversionPath: paths[0].map(({ key }) => ({
      id: key.id,
      version: key.version,
    })),
  };
}

/**
 * A `many` input groups same-type drops into one ordered sequence. A dropped
 * sequence, a converted value, and a value of another artifact type each
 * replace the slot instead, because one origin value cannot hold two artifact
 * types and a conversion path describes one source contract.
 */
function collectedOriginValue(
  payload: ArtifactDropPayload,
  port: Port,
  existing: SavedGraphOrigin | undefined,
  conversionPath: ArtifactDropResolution["conversionPath"],
): ArtifactDropValue {
  const dropped = payload.value;
  if (
    payload.shape === "many" ||
    conversionPath.length ||
    !acceptedPortShapes(port).includes("many")
  ) {
    return dropped;
  }
  const prior = existing?.value;
  if (
    !("artifact_id" in dropped) ||
    !prior ||
    prior.artifact_type !== dropped.artifact_type ||
    prior.schema_version !== dropped.schema_version
  ) {
    return dropped;
  }
  if ("item_refs" in prior) {
    return {
      artifact_type: prior.artifact_type,
      schema_version: prior.schema_version,
      item_refs: [...prior.item_refs, dropped],
      ordered: prior.ordered,
      index_key: prior.index_key,
      sequence_id: prior.sequence_id ?? createUuid(),
      ...(prior.metadata ? { metadata: prior.metadata } : {}),
    };
  }
  return {
    artifact_type: dropped.artifact_type,
    schema_version: dropped.schema_version,
    item_refs: [prior, dropped],
    ordered: true,
    index_key: "order_index",
    sequence_id: createUuid(),
  };
}

/**
 * Commands one deliberate drop means, or null when the port refuses it.
 *
 * Acceptance uses the port's declared accepted set and a unique shortest
 * declared conversion, exactly like an edge. A projection is never selected,
 * because it is a titled choice among several nested fields and a drop is a
 * single gesture. A refused or ambiguous drop returns null, so the caller
 * writes nothing and the input keeps the state it had.
 */
export function artifactDropCommands(
  payload: ArtifactDropPayload,
  target: ArtifactDropTarget,
  port: Port,
  bindings: Readonly<Record<string, ArtifactTypeKey>>,
  state: ArtifactDropGraphState,
): GraphCommand[] | null {
  const resolution = resolveArtifactDrop(
    payload,
    port,
    bindings,
    state.conversions,
  );
  if (!resolution) return null;

  const existing = state.origins.find(
    (origin) =>
      origin.to_node === target.nodeId &&
      origin.to_port === target.portName &&
      (origin.to_plug ?? null) === target.plugId,
  );
  const value = collectedOriginValue(
    payload,
    port,
    existing,
    resolution.conversionPath,
  );
  // An origin and an enabled edge never satisfy one input, so a deliberate
  // drop over a wired input removes that edge. A disabled edge may wait beside
  // the origin and is left alone.
  const enabledEdgeIds = state.edges
    .filter((edge) => {
      if (edge.data?.enabled === false || edge.target !== target.nodeId) {
        return false;
      }
      const handle = decodeHandleId(edge.targetHandle);
      return (
        handle?.portName === target.portName &&
        (handle.plugId ?? null) === target.plugId
      );
    })
    .map((edge) => edge.id);
  const commands: GraphCommand[] = [];
  if (enabledEdgeIds.length) {
    commands.push({ kind: "remove_edges", edge_ids: enabledEdgeIds });
  }
  if (existing) {
    commands.push({
      kind: "update_origin",
      origin_id: existing.id,
      update: {
        value,
        conversion_path: resolution.conversionPath,
      },
    });
    return commands;
  }
  commands.push({
    kind: "add_origin",
    origin: {
      id: `origin-${createUuid()}`,
      to_node: target.nodeId,
      to_port: target.portName,
      to_plug: target.plugId,
      value,
      conversion_path: resolution.conversionPath,
    },
  });
  return commands;
}
