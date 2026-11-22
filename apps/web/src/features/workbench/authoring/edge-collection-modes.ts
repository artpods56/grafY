import type {
  EdgeCollectionMode,
  NodeRegistry,
  Port,
  SavedGraphOrigin,
} from "@/lib/api";
import { artifactCardValue } from "../artifacts/artifact-card";
import type { AuthoredGraphDocument, GraphCommand } from "./graph-document";
import {
  acceptedPortShapes,
  collectionModesForShapes,
  defaultNodeConfig,
  originCollectionModes,
  resolveInstancePortShapes,
} from "./types";

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

/**
 * The parts of a stored origin this rule reads. `id`, `to_port`, and `value`
 * are present on saved and authored origins; leaving them optional lets unit
 * tests pass a bare `{ to_node, collection_mode }` driver fixture.
 */
export interface CollectionModeOrigin {
  readonly id?: string;
  readonly to_node: string;
  readonly to_port?: string;
  readonly value?: SavedGraphOrigin["value"];
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
  origins: readonly CollectionModeOrigin[],
  originModes: ReadonlyMap<string, EdgeCollectionMode>,
): MapDrivers {
  const byInput = new Map<string, string>();
  const nodeIds = new Set<string>();
  for (const origin of origins) {
    const mode =
      origin.id !== undefined
        ? (originModes.get(origin.id) ?? origin.collection_mode)
        : origin.collection_mode;
    if (mode !== "map") continue;
    nodeIds.add(origin.to_node);
    if (origin.id !== undefined && origin.to_port !== undefined) {
      const key = inputKey(origin.to_node, origin.to_port);
      if (!byInput.has(key)) byInput.set(key, `origin:${origin.id}`);
    }
  }
  for (const connection of connections) {
    if (modes.get(connection.id) !== "map") continue;
    nodeIds.add(connection.to_node);
    const key = inputKey(connection.to_node, connection.to_port);
    if (!byInput.has(key)) byInput.set(key, `edge:${connection.id}`);
  }
  return { byInput, nodeIds };
}

export function solveCollectionModeRepairs(
  connections: readonly CollectionModeConnection[],
  origins: readonly CollectionModeOrigin[],
  resolveStep: CollectionStepResolver,
): {
  readonly edges: Map<string, EdgeCollectionMode>;
  readonly origins: Map<string, EdgeCollectionMode>;
} {
  const modes = new Map<string, EdgeCollectionMode>();
  for (const connection of connections) {
    modes.set(connection.id, connection.collection_mode);
  }
  const originModes = new Map<string, EdgeCollectionMode>();
  for (const origin of origins) {
    if (origin.id !== undefined) {
      originModes.set(origin.id, origin.collection_mode);
    }
  }

  for (const origin of origins) {
    if (
      origin.id === undefined ||
      origin.to_port === undefined ||
      origin.value === undefined
    ) {
      continue;
    }
    const stored = originModes.get(origin.id);
    if (!stored) continue;
    const drivers = mapDrivers(connections, modes, origins, originModes);
    const driver = drivers.byInput.get(
      inputKey(origin.to_node, origin.to_port),
    );
    if (driver !== undefined && driver !== `origin:${origin.id}`) continue;

    const targetStep = resolveStep(origin.to_node);
    const targetPort = targetStep?.inputs.find(
      (port) => port.name === origin.to_port,
    );
    if (!targetPort) continue;

    const shape: Port["shape"] = "item_refs" in origin.value ? "many" : "one";
    const accepted = originCollectionModes(targetPort, shape);
    if (accepted.length === 0 || accepted.includes(stored)) continue;

    const theOtherShape = originCollectionModes(
      targetPort,
      shape === "many" ? "one" : "many",
    );
    if (!theOtherShape.includes(stored)) continue;

    const replacement = accepted[0];
    if (replacement === undefined) continue;
    originModes.set(origin.id, replacement);
  }

  // Each pass either settles every connection or moves at least one mode to one
  // the graph asks for, so this bound is generous rather than load-bearing.
  for (let pass = 0; pass <= connections.length; pass += 1) {
    const drivers = mapDrivers(connections, modes, origins, originModes);
    let repaired = false;
    for (const connection of connections) {
      const stored = modes.get(connection.id);
      if (!stored) continue;
      const driver = drivers.byInput.get(
        inputKey(connection.to_node, connection.to_port),
      );
      if (driver !== undefined && driver !== `edge:${connection.id}`) continue;

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
      // step asks for, and a step with inputs (or a config-driven port shape)
      // can move between one and many, so an edit moved the shapes rather than
      // anyone choosing this mode.
      const leftBehindByMappedness =
        theOtherMappedness.includes(stored) &&
        (runsPerItem ||
          sourceStep.inputs.length > 0 ||
          Boolean(sourcePort.shape_field));
      if (!leftBehindByMappedness) continue;

      const replacement = accepted[0];
      if (replacement === undefined) continue;
      modes.set(connection.id, replacement);
      repaired = true;
    }
    if (!repaired) break;
  }

  const edgeRepairs = new Map<string, EdgeCollectionMode>();
  for (const connection of connections) {
    const mode = modes.get(connection.id);
    if (mode !== undefined && mode !== connection.collection_mode) {
      edgeRepairs.set(connection.id, mode);
    }
  }
  const originRepairs = new Map<string, EdgeCollectionMode>();
  for (const origin of origins) {
    if (origin.id === undefined) continue;
    const mode = originModes.get(origin.id);
    if (mode !== undefined && mode !== origin.collection_mode) {
      originRepairs.set(origin.id, mode);
    }
  }
  return { edges: edgeRepairs, origins: originRepairs };
}

/**
 * Origins whose stored collection mode no longer fits the shape of the artifact
 * value they carry. Stacking a second scan onto a single-image card turns its
 * origin value into a sequence, and unstacking it turns it back into one item.
 */
export function originModesToRepair(
  connections: readonly CollectionModeConnection[],
  origins: readonly CollectionModeOrigin[],
  resolveStep: CollectionStepResolver,
): Map<string, EdgeCollectionMode> {
  return solveCollectionModeRepairs(connections, origins, resolveStep).origins;
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
  origins: readonly CollectionModeOrigin[],
  resolveStep: CollectionStepResolver,
): Map<string, EdgeCollectionMode> {
  return solveCollectionModeRepairs(connections, origins, resolveStep).edges;
}

function portAcceptsOnlySequences(port: Port): boolean {
  const accepted = acceptedPortShapes(port);
  return accepted.includes("many") && !accepted.includes("one");
}

/**
 * The `update_origin` and `update_edge` commands that put a document's
 * collection modes back in step with the graph's own map connections.
 *
 * Every authoring gesture arrives as a command batch, and a gesture as small as
 * stacking an artifact onto a card or deleting one connection moves the modes of
 * the connections downstream of it. Repairing here keeps the durable document,
 * the collaboration room, and the run request holding the modes the steps
 * actually have, rather than the modes a connection carried when it was first
 * drawn.
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
      const rawSpec = specs.get(`${node.operator_id}@${node.operator_version}`);
      const spec = rawSpec
        ? resolveInstancePortShapes(rawSpec, {
            ...defaultNodeConfig(rawSpec),
            ...(node.config ?? {}),
          })
        : undefined;
      return [
        node.id,
        spec ? { inputs: spec.inputs, outputs: spec.outputs } : null,
      ];
    }),
  );
  const resolveStep: CollectionStepResolver = (nodeId) =>
    steps.get(nodeId) ?? null;

  const commands: GraphCommand[] = [];
  const normalizedOrigins = document.origins.map((origin) => {
    if ("item_refs" in origin.value) return origin;
    const targetPort = resolveStep(origin.to_node)?.inputs.find(
      (port) => port.name === origin.to_port,
    );
    if (!targetPort || !portAcceptsOnlySequences(targetPort)) return origin;
    const wrapped = artifactCardValue([origin.value], null, {
      asSequence: true,
    });
    return wrapped ? { ...origin, value: wrapped } : origin;
  });

  const { origins: originRepairs, edges: edgeRepairs } =
    solveCollectionModeRepairs(document.edges, normalizedOrigins, resolveStep);

  for (const [index, origin] of document.origins.entries()) {
    const normalized = normalizedOrigins[index];
    const valueWrapped =
      normalized !== undefined && normalized.value !== origin.value
        ? normalized.value
        : undefined;
    const collectionMode = originRepairs.get(origin.id);
    if (valueWrapped === undefined && collectionMode === undefined) continue;
    commands.push({
      kind: "update_origin",
      origin_id: origin.id,
      update: {
        ...(valueWrapped !== undefined ? { value: valueWrapped } : {}),
        ...(collectionMode !== undefined
          ? { collection_mode: collectionMode }
          : {}),
      },
    });
  }
  for (const [edgeId, collectionMode] of edgeRepairs) {
    commands.push({
      kind: "update_edge",
      edge_id: edgeId,
      update: { collection_mode: collectionMode },
    });
  }
  return commands;
}

/**
 * Combine a gesture's commands with the collection-mode repairs they triggered.
 *
 * When a gesture rewrites an origin's value (such as stacking a second scan
 * onto a card) and a repair updates that same origin's `collection_mode`,
 * folding the repair into the origin command sends one atomic update against
 * the pre-batch document rather than two competing updates for the same id.
 */
export function foldCollectionModeRepairs(
  commands: readonly GraphCommand[],
  repairs: readonly GraphCommand[],
): GraphCommand[] {
  if (repairs.length === 0) return [...commands];
  const merged = [...commands];
  const trailing: GraphCommand[] = [];

  for (const repair of repairs) {
    if (repair.kind === "update_origin") {
      let folded = false;
      for (let i = merged.length - 1; i >= 0; i -= 1) {
        const candidate = merged[i];
        if (!candidate) continue;
        if (
          candidate.kind === "update_origin" &&
          candidate.origin_id === repair.origin_id
        ) {
          merged[i] = {
            ...candidate,
            update: { ...candidate.update, ...repair.update },
          };
          folded = true;
          break;
        }
        if (
          candidate.kind === "add_origin" &&
          candidate.origin.id === repair.origin_id
        ) {
          merged[i] = {
            ...candidate,
            origin: {
              ...candidate.origin,
              ...(repair.update.value !== undefined
                ? { value: repair.update.value }
                : {}),
              ...(repair.update.collection_mode !== undefined
                ? { collection_mode: repair.update.collection_mode }
                : {}),
            },
          };
          folded = true;
          break;
        }
      }
      if (!folded) trailing.push(repair);
      continue;
    }

    if (repair.kind === "update_edge") {
      let folded = false;
      for (let i = merged.length - 1; i >= 0; i -= 1) {
        const candidate = merged[i];
        if (!candidate) continue;
        if (
          candidate.kind === "update_edge" &&
          candidate.edge_id === repair.edge_id
        ) {
          merged[i] = {
            ...candidate,
            update: { ...candidate.update, ...repair.update },
          };
          folded = true;
          break;
        }
        if (
          candidate.kind === "add_edge" &&
          candidate.edge.id === repair.edge_id
        ) {
          merged[i] = {
            ...candidate,
            edge: {
              ...candidate.edge,
              ...(repair.update.collection_mode !== undefined
                ? { collection_mode: repair.update.collection_mode }
                : {}),
            },
          };
          folded = true;
          break;
        }
      }
      if (!folded) trailing.push(repair);
      continue;
    }

    trailing.push(repair);
  }

  return [...merged, ...trailing];
}
