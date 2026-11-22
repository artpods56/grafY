import type {
  EdgeCollectionMode,
  NodeRegistry,
  Port,
  SavedGraphOrigin,
} from "@/lib/api";
import type { AuthoredGraphDocument, GraphCommand } from "./graph-document";
import { collectionModesForShapes } from "./types";

/**
 * The parts of a stored connection this rule reads. A saved graph edge and an
 * authored graph edge both satisfy it.
 */
export interface CollectionModeConnection {
  readonly id: string;
  readonly from_node: string;
  readonly from_port: string;
  readonly to_node: string;
  readonly to_port: string;
  readonly collection_mode: EdgeCollectionMode;
}

/** One step's ports. A step with no interface to read is null. */
export interface CollectionModeStep {
  readonly inputs: readonly Port[];
  readonly outputs: readonly Port[];
}

/**
 * The ports of one step, or null when the step is not in the registry. A
 * connection whose ends cannot be read is left alone: whichever reader noticed
 * the missing step reports it, and this rule has nothing to say about ports it
 * cannot see.
 */
export type CollectionStepResolver = (
  nodeId: string,
) => CollectionModeStep | null;

function inputKey(nodeId: string, portName: string): string {
  return `${nodeId}\u0000${portName}`;
}

interface MapDrivers {
  /** The connection driving mapped execution into one input. */
  readonly byInput: Map<string, string>;
  /** Every step with a map connection or a map origin feeding it. */
  readonly nodeIds: Set<string>;
}

function mapDrivers(
  connections: readonly CollectionModeConnection[],
  modes: ReadonlyMap<string, EdgeCollectionMode>,
  origins: readonly Pick<SavedGraphOrigin, "to_node" | "collection_mode">[],
): MapDrivers {
  const byInput = new Map<string, string>();
  const nodeIds = new Set<string>();
  for (const origin of origins) {
    if (origin.collection_mode === "map") nodeIds.add(origin.to_node);
  }
  for (const connection of connections) {
    if (modes.get(connection.id) !== "map") continue;
    nodeIds.add(connection.to_node);
    const key = inputKey(connection.to_node, connection.to_port);
    if (!byInput.has(key)) byInput.set(key, connection.id);
  }
  return { byInput, nodeIds };
}

/**
 * Connections whose stored collection mode the graph no longer allows, keyed by
 * connection id and holding the mode its shapes do allow.
 *
 * A connection's mode is not its own to keep. It follows the shapes at its ends,
 * and the graph decides those: a step with a map connection into one of its
 * inputs runs once per item and offers a sequence from every output, and a step
 * without one runs once and offers a single value. Deleting the sequence feed
 * into an OCR step therefore turns each of that step's outputs from many to one,
 * and the connections leaving it cannot go on asking a runner to iterate over a
 * single value. The API refuses such a connection, and the canvas cannot open a
 * graph that holds one.
 *
 * Only a mode the graph's own map connections explain is repaired. A "map" the
 * source step could only have carried while it ran per item, on a step that has
 * inputs to drive it, is a mode an edit left behind. A mode no mappedness of the
 * source could have carried — because the step has nothing to feed it, or because
 * the two ports do not fit at all — is a document that disagrees with the node
 * types it names, and that stays visible instead of being rewritten.
 *
 * Modes are re-read as they are repaired, so one call settles a chain of steps:
 * losing a map driver unmaps its step, which turns the connections after it from
 * map to direct, which unmaps the next step, and so on.
 *
 * Two map connections into one input are left alone. Choosing the driver between
 * them is a decision about what the person meant, not about what the shapes
 * allow, and hydration reports it.
 */
export function collectionModesToRepair(
  connections: readonly CollectionModeConnection[],
  origins: readonly Pick<SavedGraphOrigin, "to_node" | "collection_mode">[],
  resolveStep: CollectionStepResolver,
): Map<string, EdgeCollectionMode> {
  const modes = new Map<string, EdgeCollectionMode>();
  for (const connection of connections) {
    modes.set(connection.id, connection.collection_mode);
  }

  // Each pass either settles every connection or moves at least one mode to one
  // the graph asks for, so this bound is generous rather than load-bearing.
  for (let pass = 0; pass <= connections.length; pass += 1) {
    const drivers = mapDrivers(connections, modes, origins);
    let repaired = false;
    for (const connection of connections) {
      const stored = modes.get(connection.id);
      if (!stored) continue;
      const driver = drivers.byInput.get(
        inputKey(connection.to_node, connection.to_port),
      );
      if (driver !== undefined && driver !== connection.id) continue;

      const sourceStep = resolveStep(connection.from_node);
      const targetStep = resolveStep(connection.to_node);
      if (!sourceStep || !targetStep) continue;
      const sourcePort = sourceStep.outputs.find(
        (port) => port.name === connection.from_port,
      );
      const targetPort = targetStep.inputs.find(
        (port) => port.name === connection.to_port,
      );
      if (!sourcePort || !targetPort) continue;

      const runsPerItem = drivers.nodeIds.has(connection.from_node);
      // This connection is the only map driver of its input, so no other
      // connection is widening that input to a sequence here.
      const accepted = collectionModesForShapes(
        runsPerItem ? "many" : sourcePort.shape,
        targetPort,
        targetPort.shape,
      );
      if (accepted.length === 0 || accepted.includes(stored)) continue;

      const theOtherMappedness = collectionModesForShapes(
        runsPerItem ? sourcePort.shape : "many",
        targetPort,
        targetPort.shape,
      );
      // The mode the connection carries is the one the other mappedness of this
      // step asks for, and a step with inputs can be driven per item, so an edit
      // moved the shapes rather than anyone choosing this mode.
      const leftBehindByMappedness =
        theOtherMappedness.includes(stored) &&
        (runsPerItem || sourceStep.inputs.length > 0);
      if (!leftBehindByMappedness) continue;

      const replacement = accepted[0];
      if (replacement === undefined) continue;
      modes.set(connection.id, replacement);
      repaired = true;
    }
    if (!repaired) break;
  }

  const repairs = new Map<string, EdgeCollectionMode>();
  for (const connection of connections) {
    const mode = modes.get(connection.id);
    if (mode !== undefined && mode !== connection.collection_mode) {
      repairs.set(connection.id, mode);
    }
  }
  return repairs;
}

/**
 * The `update_edge` commands that put a document's collection modes back in step
 * with the graph's own map connections.
 *
 * Every authoring gesture arrives as a command batch, and a gesture as small as
 * deleting one connection moves the modes of the connections downstream of it.
 * Repairing here keeps the durable document, the collaboration room, and the run
 * request holding the modes the steps actually have, rather than the modes a
 * connection carried when it was first drawn.
 */
export function collectionModeRepairCommands(
  document: AuthoredGraphDocument,
  registry: NodeRegistry | null,
): GraphCommand[] {
  if (!registry) return [];
  const specs = new Map(
    registry.nodes.map((spec) => [
      `${spec.operator_id}@${spec.operator_version}`,
      spec,
    ]),
  );
  const steps = new Map<string, CollectionModeStep | null>(
    document.nodes.map((node) => {
      const spec = specs.get(`${node.operator_id}@${node.operator_version}`);
      return [
        node.id,
        spec ? { inputs: spec.inputs, outputs: spec.outputs } : null,
      ];
    }),
  );
  const resolveStep: CollectionStepResolver = (nodeId) =>
    steps.get(nodeId) ?? null;

  const commands: GraphCommand[] = [];
  for (const [edgeId, collectionMode] of collectionModesToRepair(
    document.edges,
    document.origins,
    resolveStep,
  )) {
    commands.push({
      kind: "update_edge",
      edge_id: edgeId,
      update: { collection_mode: collectionMode },
    });
  }
  return commands;
}
