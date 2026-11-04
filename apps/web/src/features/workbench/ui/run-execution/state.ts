import { getInstanceResult, listGraphInstances } from "@/lib/api";
import type {
  ArtifactOutputValue,
  ArtifactRefSequence,
  InstanceResult,
  InstanceState,
  InstanceStateName,
  RunNodeResult,
  RunPortArtifact,
  RunPortOutput,
} from "@/lib/api";
import type { NodeExecutionStatus } from "../../canvas/types";
import type { WorkflowNode } from "../../model/execution-plan";

/**
 * The five states a node instance can be read in. Nothing here is stored: the
 * server derives a state from the document's fingerprint, the result store and
 * what a Run has in flight, and the canvas only ever renders that derivation.
 */
export type NodeInstanceState = InstanceStateName;

export const INSTANCE_STATES: readonly NodeInstanceState[] = [
  "fresh",
  "stale",
  "queued",
  "running",
  "failed",
];

export function instanceStateIsTerminal(state: NodeInstanceState): boolean {
  return state === "fresh" || state === "stale" || state === "failed";
}

/**
 * The canvas overlay a Run surface can paint from an instance state.
 *
 * The card chrome still speaks the coarse overlay vocabulary, and its own
 * `stale` is a fresh-enough answer with a different name. A stale instance is
 * not idle: it holds the result it last produced, so the overlay is only the
 * quiet half of what the card shows, and `instanceStateByNodeId` carries the
 * rest.
 */
export function overlayStatusForInstance(
  state: NodeInstanceState,
): NodeExecutionStatus {
  switch (state) {
    case "fresh":
      return "succeeded";
    case "queued":
      return "queued";
    case "running":
      return "running";
    case "failed":
      return "failed";
    case "stale":
      return "idle";
  }
}

/** An instance of the Graph a person is looking at, not one behind a call node. */
export function isRootInstance(instance: InstanceState): boolean {
  return (
    instance.key.call_path.length === 0 &&
    (instance.key.map_index ?? null) === null
  );
}

/**
 * State per node id for the open Graph.
 *
 * Instances addressed through a call node, or one mapped item of a collection,
 * belong to the same Graph but not to a card on this canvas, so they are left
 * out rather than collapsed onto their outer node.
 */
export function instanceStateByNodeId(
  instances: readonly InstanceState[],
): ReadonlyMap<string, InstanceState> {
  const byNodeId = new Map<string, InstanceState>();
  for (const instance of instances) {
    if (!isRootInstance(instance)) continue;
    byNodeId.set(instance.key.node_id, instance);
  }
  return byNodeId;
}

function isSequenceValue(
  value: ArtifactOutputValue,
): value is ArtifactRefSequence {
  return Array.isArray((value as ArtifactRefSequence).item_refs);
}

function portArtifact(value: {
  artifact_id: string;
  artifact_type: string;
  schema_version: number;
  content_hash?: string | null;
}): RunPortArtifact {
  return {
    artifact_id: value.artifact_id,
    artifact_type: value.artifact_type,
    schema_version: value.schema_version,
    content_hash: value.content_hash ?? null,
  };
}

/**
 * One stored result's outputs, as the canvas reads them.
 *
 * A result is a map of port name to an artifact reference or a sequence of
 * them; the cards want a list of ports with the references each one holds.
 */
export function runPortOutputs(
  outputs: InstanceResult["outputs"],
): RunPortOutput[] {
  if (!outputs) return [];
  return Object.entries(outputs).flatMap(([port, value]): RunPortOutput[] => {
    if (!value || typeof value !== "object") return [];
    if (isSequenceValue(value)) {
      return [
        {
          port,
          kind: "sequence" as const,
          value,
          artifacts: value.item_refs.map(portArtifact),
        },
      ];
    }
    return [
      {
        port,
        kind: "single" as const,
        value,
        artifacts: [portArtifact(value)],
      },
    ];
  });
}

/**
 * The stored result of one instance, in the shape a node card reads.
 *
 * A result only ever exists when it was stored, so an instance with no result
 * of its own is not a `RunNodeResult` with empty outputs: it is no result at
 * all, and the caller says so by passing `null`.
 */
export function runNodeResultFromInstance(
  instanceResult: InstanceResult,
): RunNodeResult | null {
  const { instance } = instanceResult;
  const failed = instance.state === "failed";
  if (!instanceResult.result_fingerprint && !failed) return null;
  return {
    node_id: instance.key.node_id,
    status: failed ? "failed" : "succeeded",
    error: failed
      ? (instance.error ?? "This node failed without error details.")
      : null,
    outputs: runPortOutputs(instanceResult.outputs),
    result_fingerprint: instanceResult.result_fingerprint,
    created_at: instanceResult.created_at,
  };
}

/**
 * Publish derived instance state onto the canvas overlays.
 *
 * Only nodes this snapshot names move, so an instance that left the Graph (a
 * deleted node, or one a collaborator has not yet added here) keeps whatever
 * the canvas already showed instead of being silently reset.
 */
export function withInstanceStates(
  nodes: readonly WorkflowNode[],
  states: ReadonlyMap<string, InstanceState>,
): WorkflowNode[] {
  return nodes.map((node) => {
    const instance = states.get(node.id);
    if (!instance) return node;
    const status = overlayStatusForInstance(instance.state);
    if (node.data.execution.status === status) return node;
    return {
      ...node,
      data: {
        ...node.data,
        execution: {
          status,
          error:
            instance.state === "failed"
              ? (instance.error ?? "This node failed without error details.")
              : undefined,
        },
      },
    };
  });
}

/**
 * Publish stored results onto the canvas, keeping what an instance last
 * produced when its own result has not been read yet.
 *
 * An edit during a Run leaves the instance stale, and a stale node must keep
 * showing the result it stored under its previous fingerprint: dropping the
 * older result here is how a canvas goes blank on someone who asked nothing of
 * the Run.
 */
export function withInstanceResults(
  nodes: readonly WorkflowNode[],
  results: ReadonlyMap<string, RunNodeResult>,
): WorkflowNode[] {
  return nodes.map((node) => {
    const result = results.get(node.id);
    if (!result) return node;
    if (node.data.run === result) return node;
    return { ...node, data: { ...node.data, run: result } };
  });
}

/** The overlay a node shows before any instance state has been read for it. */
export const IDLE_OVERLAY = { status: "idle" } as const;

/** How many instances are read at once. Results travel one per request. */
const INSTANCE_RESULT_CONCURRENCY = 6;

export interface InstanceSnapshot {
  /** Derived state for every root instance of the Graph, in document order. */
  readonly instances: readonly InstanceState[];
  /** The stored results those instances point at, one per node id. */
  readonly results: readonly RunNodeResult[];
}

async function mapWithLimit<Item, Result>(
  items: readonly Item[],
  limit: number,
  work: (item: Item) => Promise<Result | null>,
): Promise<Result[]> {
  const results: Result[] = [];
  let nextIndex = 0;
  const runners = Array.from(
    { length: Math.min(limit, items.length) },
    async () => {
      while (nextIndex < items.length) {
        const item = items[nextIndex];
        nextIndex += 1;
        if (item === undefined) continue;
        const result = await work(item);
        if (result !== null) results.push(result);
      }
    },
  );
  await Promise.all(runners);
  return results;
}

/**
 * Read one Graph's instances, and the results they point at.
 *
 * State is one request for the whole Graph because it is derived from the
 * document; a result is one request per instance because a result belongs to
 * the instance that produced it and no request can name all of them at once.
 * So a caller that only cares about a few nodes names them, and an instance
 * whose last result has not moved is not read again.
 */
export async function loadInstanceSnapshot(
  workspaceId: string,
  projectId: string,
  graphId: string,
  options: {
    signal?: AbortSignal;
    /** Read results only for these nodes; state always covers the whole Graph. */
    onlyNodeIds?: ReadonlySet<string>;
    /** Skip results already held under this fingerprint for the node. */
    loadedFingerprints?: ReadonlyMap<string, string>;
  } = {},
): Promise<InstanceSnapshot> {
  const instances = await listGraphInstances(
    workspaceId,
    projectId,
    graphId,
    options.signal,
  );
  const wanted = instances.instances.filter(
    (instance) =>
      isRootInstance(instance) &&
      instance.last_result_fingerprint !== null &&
      (options.onlyNodeIds?.has(instance.key.node_id) ?? true) &&
      options.loadedFingerprints?.get(instance.key.node_id) !==
        instance.last_result_fingerprint,
  );
  const results = await mapWithLimit(
    wanted,
    INSTANCE_RESULT_CONCURRENCY,
    async (instance) => {
      const result = await getInstanceResult(
        workspaceId,
        projectId,
        {
          graph_id: instance.key.graph_id,
          node_id: instance.key.node_id,
          call_path: instance.key.call_path,
        },
        options.signal,
      );
      return runNodeResultFromInstance(result);
    },
  );
  return { instances: instances.instances, results };
}
