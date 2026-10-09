import type {
  ArtifactRef,
  ArtifactTypeKey,
  NodeSpec,
  SavedGraphOrigin,
} from "@/lib/api";
import {
  artifactCardValue,
  cardArtifactRefs,
  type ArtifactCardValue,
} from "../canvas/artifact-card";
import {
  addEdgeCommand,
  addNodeCommand,
} from "../canvas/graph-document-adapter";
import type { CollectionMember } from "../canvas/collection-member";
import {
  COLLECTION_OPERATOR_ID,
  COLLECTION_PORT,
  isCollectionNode,
  isCollectionSpec,
} from "./collection-spec";
import { decodeHandleId, encodeHandleId } from "../canvas/handles";
import { inputPlugsForPort } from "../canvas/input-plugs";
import {
  effectivePortShape,
  portMetaForPort,
  resolvedPortArtifactType,
  type WorkflowEdge,
  type WorkflowNodeData,
} from "../canvas/types";
import type { GraphCommand } from "./graph-document";
import { createUuid } from "./uuid";

/**
 * A collection is not a node you pick from the catalog: it is what artifacts
 * become when you gather them. On the canvas it is an artifact stack; in the
 * graph it is the `sequence.collect` operator, whose input plugs are the
 * members, in order. A member is either a Library artifact (an origin on its
 * plug) or a node output (an edge into its plug), so one collection can gather
 * both, and more can join it later through its spare plug.
 */
export {
  COLLECTION_OPERATOR_ID,
  COLLECTION_PORT,
  isCollectionNode,
  isCollectionSpec,
};

export type { CollectionMember };

interface CollectionGraphNode {
  readonly id: string;
  readonly data: WorkflowNodeData;
}

/** A collection's plugs in order, each resolved to what fills it. */
export function collectionMembers(
  node: CollectionGraphNode,
  nodes: readonly CollectionGraphNode[],
  edges: readonly WorkflowEdge[],
  origins: readonly SavedGraphOrigin[],
): CollectionMember[] {
  return inputPlugsForPort(node.data.inputPlugs, COLLECTION_PORT).map(
    (plug): CollectionMember => {
      const origin = origins.find(
        (candidate) =>
          candidate.to_node === node.id &&
          candidate.to_port === COLLECTION_PORT &&
          candidate.to_plug === plug.id,
      );
      if (origin) {
        return {
          plugId: plug.id,
          kind: "library",
          originId: origin.id,
          refs: cardArtifactRefs(origin.value),
        };
      }
      const edge = edges.find(
        (candidate) =>
          candidate.target === node.id &&
          decodeHandleId(candidate.targetHandle)?.plugId === plug.id,
      );
      const sourcePortName =
        edge?.data?.sourcePortName ??
        decodeHandleId(edge?.sourceHandle)?.portName;
      const source = edge
        ? nodes.find((candidate) => candidate.id === edge.source)
        : undefined;
      if (edge && sourcePortName) {
        const port = source?.data.spec.outputs.find(
          (candidate) => candidate.name === sourcePortName,
        );
        const output =
          source?.data.run?.status === "succeeded"
            ? source.data.run.outputs.find(
                (candidate) => candidate.port === sourcePortName,
              )
            : undefined;
        return {
          plugId: plug.id,
          kind: "output",
          edgeId: edge.id,
          sourceNodeId: edge.source,
          sourcePortName,
          label: `${source?.data.spec.title ?? "Output"} → ${port?.title ?? sourcePortName}`,
          refs: output ? cardArtifactRefs(output.value) : null,
        };
      }
      return { plugId: plug.id, kind: "empty" };
    },
  );
}

/**
 * The plug a new member lands on: the first empty one. A collection keeps one
 * spare, so there is always somewhere for the next member to go.
 */
export function collectionSparePlugId(
  members: readonly CollectionMember[],
): string | null {
  return members.find((member) => member.kind === "empty")?.plugId ?? null;
}

/**
 * Whether a collection already gathers every one of these artifacts, so adding
 * them again would only repeat members.
 */
export function collectionHoldsArtifacts(
  members: readonly CollectionMember[],
  refs: readonly ArtifactRef[],
): boolean {
  if (refs.length === 0) return false;
  const held = new Set(
    members.flatMap((member) =>
      member.kind === "library"
        ? member.refs.map((ref) => ref.artifact_id)
        : member.kind === "output"
          ? (member.refs ?? []).map((ref) => ref.artifact_id)
          : [],
    ),
  );
  return refs.every((ref) => held.has(ref.artifact_id));
}

/** Collections whose every plug is filled, so they need a new spare. */
export function collectionsWithoutSpare(
  nodes: readonly CollectionGraphNode[],
  edges: readonly WorkflowEdge[],
  origins: readonly SavedGraphOrigin[],
): string[] {
  return nodes
    .filter(isCollectionNode)
    .filter(
      (node) =>
        collectionSparePlugId(
          collectionMembers(node, nodes, edges, origins),
        ) === null,
    )
    .map((node) => node.id);
}

/** What the canvas "Collect" gathers: a Library card, or a card on an output. */
export type CollectionSource =
  | {
      readonly kind: "library";
      readonly cardId: string;
      readonly position: { x: number; y: number };
      readonly value: ArtifactCardValue;
    }
  | {
      readonly kind: "output";
      readonly cardId: string;
      readonly position: { x: number; y: number };
      readonly sourceNodeId: string;
      readonly sourcePortName: string;
    };

interface CollectPlan {
  readonly collectionId: string;
  readonly commands: GraphCommand[];
  /** Cards (and the edges that fed them) the collection replaces. */
  readonly removedCardIds: readonly string[];
}

function artifactTypeOfSource(
  source: CollectionSource,
  nodes: readonly CollectionGraphNode[],
): ArtifactTypeKey | null {
  if (source.kind === "library") {
    return {
      id: source.value.artifact_type,
      schema_version: source.value.schema_version,
    };
  }
  const producer = nodes.find((node) => node.id === source.sourceNodeId);
  const port = producer?.data.spec.outputs.find(
    (candidate) => candidate.name === source.sourcePortName,
  );
  if (!producer || !port) return null;
  const output =
    producer.data.run?.status === "succeeded"
      ? producer.data.run.outputs.find(
          (candidate) => candidate.port === source.sourcePortName,
        )
      : undefined;
  if (output) {
    return {
      id: output.value.artifact_type,
      schema_version: output.value.schema_version,
    };
  }
  return resolvedPortArtifactType(port, producer.data.artifactTypeBindings);
}

/**
 * Why these cards cannot become one collection, or null when they can: a
 * collection holds one artifact type, and every member's type must be known.
 */
export function collectDisabledReason(
  sources: readonly CollectionSource[],
  nodes: readonly CollectionGraphNode[],
): string | null {
  if (sources.length < 2) return "Select two or more artifacts to collect.";
  const types = sources.map((source) => artifactTypeOfSource(source, nodes));
  if (types.some((type) => type === null)) {
    return "Run the producing node first, so its artifact type is known.";
  }
  const [first] = types;
  const mixed = types.some(
    (type) =>
      type?.id !== first?.id || type?.schema_version !== first?.schema_version,
  );
  return mixed ? "Select artifacts of one type to collect." : null;
}

/**
 * Build the collection that gathers these cards, in reading order: Library
 * cards become origins on their plugs, cards on an output become edges from
 * that output. The collection keeps one spare plug for whatever joins next.
 */
export function collectCardsCommands({
  sources,
  nodes,
  collectSpec,
  createNodeData,
}: {
  sources: readonly CollectionSource[];
  nodes: readonly CollectionGraphNode[];
  collectSpec: NodeSpec;
  createNodeData: (
    spec: NodeSpec,
    plugs: readonly { id: string; port: string }[],
  ) => WorkflowNodeData;
}): CollectPlan | null {
  if (collectDisabledReason(sources, nodes)) return null;
  const itemsPort = collectSpec.inputs.find(
    (port) => port.name === COLLECTION_PORT,
  );
  const variable = itemsPort?.artifact_type_variable;
  const firstSource = sources[0];
  const artifactType = firstSource
    ? artifactTypeOfSource(firstSource, nodes)
    : null;
  if (!itemsPort || !variable || !artifactType) return null;

  // Reading order: cards within half a card label of each other share a row.
  // A card showing artifacts already gathered, or following an output that is
  // already a member, adds nothing: a collection never repeats a member.
  const seenArtifacts = new Set<string>();
  const seenOutputs = new Set<string>();
  const ordered = [...sources]
    .sort((left, right) => {
      const dy = left.position.y - right.position.y;
      return Math.abs(dy) > 24 ? dy : left.position.x - right.position.x;
    })
    .filter((source) => {
      if (source.kind === "output") {
        const key = `${source.sourceNodeId}:${source.sourcePortName}`;
        if (seenOutputs.has(key)) return false;
        seenOutputs.add(key);
        return true;
      }
      const ids = cardArtifactRefs(source.value).map((ref) => ref.artifact_id);
      if (ids.every((id) => seenArtifacts.has(id))) return false;
      for (const id of ids) seenArtifacts.add(id);
      return true;
    });
  const members = ordered.map((source) => ({ source, plugId: createUuid() }));
  const spare = createUuid();
  const collectionId = `node-${createUuid()}`;
  const bindings = { [variable]: artifactType };
  const data = {
    ...createNodeData(collectSpec, [
      ...members.map(({ plugId }) => ({ id: plugId, port: COLLECTION_PORT })),
      { id: spare, port: COLLECTION_PORT },
    ]),
    artifactTypeBindings: bindings,
  };
  const commands: GraphCommand[] = [
    addNodeCommand(collectionId, data, {
      x: Math.min(...sources.map((source) => source.position.x)),
      y: Math.min(...sources.map((source) => source.position.y)),
    }),
  ];
  for (const { source, plugId } of members) {
    const targetHandle = encodeHandleId(
      portMetaForPort(itemsPort, itemsPort.shape, plugId, bindings),
    );
    if (source.kind === "library") {
      commands.push({
        kind: "add_origin",
        origin: {
          id: `origin-${createUuid()}`,
          to_node: collectionId,
          to_port: COLLECTION_PORT,
          to_plug: plugId,
          value: source.value,
          conversion_path: [],
        },
      });
      continue;
    }
    const producer = nodes.find((node) => node.id === source.sourceNodeId);
    const port = producer?.data.spec.outputs.find(
      (candidate) => candidate.name === source.sourcePortName,
    );
    if (!producer || !port) return null;
    commands.push(
      addEdgeCommand(
        {
          source: producer.id,
          sourceHandle: encodeHandleId(
            portMetaForPort(
              port,
              effectivePortShape(producer.data, port),
              undefined,
              producer.data.artifactTypeBindings,
            ),
          ),
          target: collectionId,
          targetHandle,
        },
        { enabled: true, collectionMode: "direct", conversionPath: [] },
        `edge-${createUuid()}`,
      ),
    );
  }
  return {
    collectionId,
    commands,
    removedCardIds: sources.map((source) => source.cardId),
  };
}

/** One card a collection member becomes again when it is ungrouped. */
export type UngroupedCard =
  | {
      readonly kind: "library";
      readonly position: { x: number; y: number };
      readonly value: ArtifactCardValue;
    }
  | {
      readonly kind: "output";
      readonly position: { x: number; y: number };
      readonly sourceNodeId: string;
      readonly sourcePortName: string;
    };

/**
 * Why a collection cannot be ungrouped, or null: its output must not feed
 * anything, since the individual cards cannot stand in for the sequence.
 */
export function ungroupCollectionDisabledReason(
  collectionId: string,
  edges: readonly WorkflowEdge[],
): string | null {
  return edges.some((edge) => edge.source === collectionId)
    ? "Disconnect this collection's output before ungrouping it."
    : null;
}

/** The cards a collection's members become, laid out in member order. */
export function ungroupedCollectionCards(
  origin: { x: number; y: number },
  members: readonly CollectionMember[],
  cardWidth: number,
  cardHeight: number,
): UngroupedCard[] {
  const filled = members.filter((member) => member.kind !== "empty");
  const columns = Math.max(1, Math.ceil(Math.sqrt(filled.length)));
  return filled.flatMap((member, index): UngroupedCard[] => {
    const position = {
      x: origin.x + (index % columns) * (cardWidth + 64),
      y: origin.y + Math.floor(index / columns) * (cardHeight + 88),
    };
    if (member.kind === "library") {
      const value = artifactCardValue([...member.refs]);
      return value ? [{ kind: "library", position, value }] : [];
    }
    if (member.kind === "output") {
      return [
        {
          kind: "output",
          position,
          sourceNodeId: member.sourceNodeId,
          sourcePortName: member.sourcePortName,
        },
      ];
    }
    return [];
  });
}
