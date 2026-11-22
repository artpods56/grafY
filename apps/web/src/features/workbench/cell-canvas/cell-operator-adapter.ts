/**
 * Operator and collection cards, and the graph commands that edit the nodes
 * behind them.
 *
 * A node card is the one kind whose shape is authored rather than derived: its
 * width, body height and appendix come back as `GraphNodeLayout`, so every
 * command this module emits is clamped through the shared layout serializer
 * before it reaches the wire.
 */
import type {
  NodeRegistry,
  NodeSpec,
  Port,
  SavedGraphNode,
  ServiceContract,
} from "@/lib/api";

import { DEFAULT_ARTIFACT_CARD_WIDTH } from "../artifacts/artifact-card";
import {
  BODY_HEIGHT_MIN,
  DEFAULT_NODE_WIDTH,
  LAYOUT_DIMENSION_MAX,
  NODE_WIDTH_MIN,
  type SavedNodeLayout,
  serializeNodeLayout,
} from "../authoring/node-layout";
import {
  COLLECTION_OPERATOR_ID,
  COLLECTION_PORT,
  isCollectionSpec,
} from "../authoring/collection-spec";
import type {
  AuthoredGraphDocument,
  AuthoredGraphEdge,
  AuthoredGraphNode,
  AuthoredGraphOrigin,
  GraphCommand,
} from "../authoring/graph-document";
import {
  nodeSecretBindingReady,
  nodeSecretDependencyRevision,
  nodeSecretInputs,
  type WorkflowNodeSecretStatuses,
} from "../authoring/node-secrets";
import { schemaFields, validateConfig } from "../config-ui/config-schema";
import { connectedInputPortsForDocumentNode } from "../config-ui/connected-inputs";

import { countConfigShelfCells } from "./cell-card-geometry";
import { buildSchemaConfigEntries } from "./cell-config-plan";
import type {
  CellCardSurfaceData,
  CellExecutionAppendixSpec,
  CellInstancePlugGroup,
  CellResizeCommit,
  CellSecretInputSpec,
  CollectionCardSurfaceData,
} from "./cell-contracts";
import {
  MAX_CARD_HEIGHT_CELLS,
  MAX_CARD_WIDTH_CELLS,
  MIN_CARD_WIDTH_CELLS,
  MIN_OPERATOR_HEIGHT_CELLS,
  PLUG_SEPARATOR,
  collectionTypeLabel,
  cellOriginFromWorld,
  nodeSpec,
  portArtifactType,
  portTypeId,
  snapPixelsToCell,
  targetPortId,
} from "./cell-adapter-shared";
import {
  CELL_SIZE,
  FIRST_PORT_ROW,
  PORT_ROW_PITCH,
  STRIP_FIRST_PORT_ROW,
  type CellCardModel,
  type CellPort,
  cellToWorldOrigin,
  collectionHeightCells,
} from "./cell-model";

/** An expanded execution appendix is never shorter than four cells. */
const MIN_APPENDIX_CELLS = 4;

export interface CellNodeRunState {
  status?: CellCardModel["status"];
  statusLabel?: string;
  runDisabled?: boolean;
  appendix?: CellExecutionAppendixSpec | null;
}

/**
 * What the secret store knows about a graph's write-only keys. The caller owns
 * the store, so this adapter only reads statuses and the saved nodes a key is
 * bound to.
 */
export interface CellNodeSecretState {
  statuses: Readonly<Record<string, WorkflowNodeSecretStatuses>>;
  /** The nodes as last saved; `null` while the graph has never been saved. */
  savedNodes: readonly SavedGraphNode[] | null;
  /** Names the graph and room epoch a key was written for. */
  scope: string;
}

/**
 * Each key a node declares, with its status. A key saved for settings that
 * have since changed cannot be trusted, so a configured status only counts
 * while the binding it was saved for still holds.
 */
function nodeSecretSurface(
  node: AuthoredGraphNode,
  spec: NodeSpec,
  secrets: CellNodeSecretState | undefined,
): CellSecretInputSpec[] {
  const savedNode = secrets?.savedNodes?.find(
    (candidate) => candidate.id === node.id,
  );
  return nodeSecretInputs(spec).map((input) => {
    const stored = secrets?.statuses[node.id]?.[input.name] ?? {
      state: "unknown" as const,
    };
    const ready = nodeSecretBindingReady(input, node, savedNode);
    const status =
      !ready && stored.state === "configured"
        ? { state: "stale" as const }
        : stored;
    return {
      name: input.name,
      title: input.title,
      ...(input.description ? { description: input.description } : {}),
      state: status.state,
      ...(status.message ? { message: status.message } : {}),
      ready,
      revision: `${secrets?.scope ?? "unsaved"}:${nodeSecretDependencyRevision(input, node.config ?? {})}`,
    };
  });
}

type PlugConnection = AuthoredGraphEdge | AuthoredGraphOrigin;

function connectionsByNode(document: AuthoredGraphDocument) {
  const byNode = new Map<string, Map<string, PlugConnection>>();
  for (const connection of [...document.origins, ...document.edges]) {
    if (!connection.to_plug) continue;
    let byPort = byNode.get(connection.to_node);
    if (!byPort) {
      byPort = new Map();
      byNode.set(connection.to_node, byPort);
    }
    const portId = targetPortId(connection.to_port, connection.to_plug);
    if (!byPort.has(portId)) byPort.set(portId, connection);
  }
  return byNode;
}

function servicePortContractLabel(
  port: Port,
  serviceContracts: readonly ServiceContract[] | undefined,
): string {
  const contracts = port.service_contracts ?? [];
  if (contracts.length === 0) return "service";
  return contracts
    .map((key) => {
      const match = serviceContracts?.find(
        (contract) =>
          contract.id === key.id && contract.version === key.version,
      );
      return match?.title ?? `${key.id}@${key.version}`;
    })
    .join(", ");
}

/**
 * Ports of a node, {@link PORT_ROW_PITCH} rows apart. An operator's fixed
 * ports pair up by row from {@link FIRST_PORT_ROW} and its instance plugs
 * follow in their own band, each group closing with its "Add" row and an
 * empty row. A collection's plugs are its member rows, so they start level
 * with its output at {@link STRIP_FIRST_PORT_ROW}.
 */
function nodePorts(
  node: AuthoredGraphNode,
  spec: NodeSpec | undefined,
  connections: ReadonlyMap<string, PlugConnection> | undefined,
  isCollection: boolean,
  serviceContracts?: readonly ServiceContract[],
) {
  const inputs = spec?.inputs ?? [];
  const fixedInputs = inputs.filter((port) => !port.instance_plugs);
  const outputs = spec?.outputs ?? [];
  const firstRow = isCollection ? STRIP_FIRST_PORT_ROW : FIRST_PORT_ROW;
  const fixedPort = (port: Port, index: number): CellPort => {
    if (port.kind === "service") {
      return {
        id: port.name,
        name: port.title || port.name,
        direction: port.direction,
        rowOffset: firstRow + index * PORT_ROW_PITCH,
        artifactTypeId: port.service_contracts?.[0]?.id ?? "service",
        shape: port.shape,
        required: port.required,
        kind: "service",
        serviceContractLabel: servicePortContractLabel(port, serviceContracts),
      };
    }
    return {
      id: port.name,
      name: port.title || port.name,
      direction: port.direction,
      rowOffset: firstRow + index * PORT_ROW_PITCH,
      artifactTypeId: portTypeId(node, port),
      shape: port.shape,
      required: port.required,
    };
  };
  const ports = [...fixedInputs.map(fixedPort), ...outputs.map(fixedPort)];
  const groups: CellInstancePlugGroup[] = [];
  let nextRow =
    firstRow +
    PORT_ROW_PITCH *
      (isCollection
        ? fixedInputs.length
        : Math.max(fixedInputs.length, outputs.length));

  for (const port of inputs) {
    if (!port.instance_plugs) continue;
    const title = port.title || port.name;
    const artifactTypeId = portTypeId(node, port);
    const startRowOffset = nextRow;
    const plugs = node.input_plugs
      .filter((plug) => plug.port === port.name)
      .map((plug, index) => {
        const id = targetPortId(port.name, plug.id);
        const label = `${title} #${index + 1}`;
        ports.push({
          id,
          name: label,
          direction: "input",
          rowOffset: nextRow,
          artifactTypeId,
          shape: port.shape,
          required: port.required,
        });
        nextRow += PORT_ROW_PITCH;
        return {
          plugId: plug.id,
          label,
          connected: connections?.has(id) ?? false,
        };
      });
    groups.push({
      portName: port.name,
      title,
      artifactTypeId,
      shape: port.shape,
      startRowOffset,
      plugs,
      canAdd: true,
    });
    // The "Add" row and the empty row under it.
    nextRow += PORT_ROW_PITCH;
  }
  return { ports, groups, nextRow };
}

function collectionSurface(
  node: AuthoredGraphNode,
  spec: NodeSpec | undefined,
  connections: ReadonlyMap<string, PlugConnection> | undefined,
  specsByNode: ReadonlyMap<string, NodeSpec | undefined>,
  catalog: NodeRegistry["artifact_types"],
): CollectionCardSurfaceData {
  const port = spec?.inputs.find((input) => input.name === COLLECTION_PORT);
  const artifactType = portArtifactType(node, port);
  const artifactTypeId =
    artifactType?.id ?? port?.artifact_type_variable ?? "artifact";
  const typeLabel = collectionTypeLabel(artifactType, catalog);
  const members: CollectionCardSurfaceData["members"][number][] = [];

  for (const plug of node.input_plugs) {
    if (plug.port !== COLLECTION_PORT) continue;
    const connection = connections?.get(targetPortId(plug.port, plug.id));
    if (!connection) continue;
    if ("value" in connection) {
      const value = connection.value;
      const originType = collectionTypeLabel(
        { id: value.artifact_type, schema_version: value.schema_version },
        catalog,
      );
      members.push({
        id: plug.id,
        label: originType,
        artifactTypeId: value.artifact_type,
        typeLabel: originType,
      });
    } else {
      const sourceSpec = specsByNode.get(connection.from_node);
      const sourcePort = sourceSpec?.outputs.find(
        (output) => output.name === connection.from_port,
      );
      members.push({
        id: plug.id,
        label: `${sourceSpec?.title || "Output"} → ${sourcePort?.title || connection.from_port}`,
        artifactTypeId,
        typeLabel,
      });
    }
  }
  const sparePlug = node.input_plugs.find(
    (plug) =>
      plug.port === COLLECTION_PORT &&
      !connections?.has(targetPortId(plug.port, plug.id)),
  );
  return {
    kind: "collection",
    artifactTypeId,
    typeLabel,
    members,
    showSparePlug: true,
    sparePlugId: sparePlug?.id ?? null,
  };
}

/**
 * Every node card in the document, operator or collection, with the surface
 * data its card paints and the catalogued spec it was placed from. The specs
 * come back too: a following artifact card names its producer's output port
 * through them.
 */
export function buildOperatorCardsAndSurfaces(
  document: AuthoredGraphDocument,
  registry: NodeRegistry,
  options?: {
    nodeRunState?: Readonly<Record<string, CellNodeRunState>>;
    collapsedAppendices?: ReadonlySet<string>;
    /** Config sections opened or closed, by node id, then by section key. */
    configSections?: Readonly<
      Record<string, Readonly<Record<string, boolean>>>
    >;
    secrets?: CellNodeSecretState;
  },
): {
  cards: CellCardModel[];
  surfaces: Map<string, CellCardSurfaceData>;
  specsByNode: Map<string, NodeSpec | undefined>;
} {
  const cards: CellCardModel[] = [];
  const surfaces = new Map<string, CellCardSurfaceData>();
  const specsByNode = new Map(
    document.nodes.map((node) => [node.id, nodeSpec(node, registry)]),
  );
  const connections = connectionsByNode(document);
  const sources = new Map(
    document.nodes.map((node) => [
      node.id,
      { node, spec: specsByNode.get(node.id) },
    ]),
  );

  for (const node of document.nodes) {
    const spec = specsByNode.get(node.id);
    const runState = options?.nodeRunState?.[node.id];
    const isCollection =
      isCollectionSpec(spec) || node.operator_id === COLLECTION_OPERATOR_ID;
    const kind = isCollection ? "collection" : "operator";
    const defaultWidth = isCollection
      ? DEFAULT_ARTIFACT_CARD_WIDTH
      : DEFAULT_NODE_WIDTH;
    const widthCells = Math.max(
      MIN_CARD_WIDTH_CELLS,
      snapPixelsToCell(node.layout?.width ?? defaultWidth),
    );
    const nodeConnections = connections.get(node.id);
    const { ports, groups, nextRow } = nodePorts(
      node,
      spec,
      nodeConnections,
      isCollection,
      registry.service_contracts,
    );
    const collection = isCollection
      ? collectionSurface(
          node,
          spec,
          nodeConnections,
          specsByNode,
          registry.artifact_types,
        )
      : null;

    const configSections = options?.configSections?.[node.id];
    const connectedInputPorts =
      spec && !isCollection
        ? connectedInputPortsForDocumentNode({
            nodeId: node.id,
            spec,
            edges: document.edges,
            origins: document.origins,
            sources,
            conversions: registry.artifact_conversions,
            artifactTypes: registry.artifact_types,
          })
        : undefined;
    const config = node.config ?? {};
    const configFields = isCollection
      ? []
      : buildSchemaConfigEntries({
          fields: schemaFields(spec?.config_schema),
          config,
          issues: validateConfig(spec?.config_schema, config),
          connectedPorts: connectedInputPorts,
          sections: configSections,
        });
    // Keys live behind the header's key button, so they cost the band nothing.
    const secretInputs =
      spec && !isCollection
        ? nodeSecretSurface(node, spec, options?.secrets)
        : [];
    const appendixHeight = node.layout?.appendix_height ?? 0;
    const savedAppendixCells =
      appendixHeight > 0
        ? Math.max(MIN_APPENDIX_CELLS, Math.ceil(appendixHeight / CELL_SIZE))
        : 0;
    const rawAppendix: CellExecutionAppendixSpec | null =
      runState?.appendix !== undefined
        ? runState.appendix
        : savedAppendixCells > 0
          ? {
              title: "Execution output",
              kindBadge: "Output",
              heightCells: savedAppendixCells,
              summaryText: "",
            }
          : null;
    const collapsedFromSet = options?.collapsedAppendices?.has(node.id);
    const isAppendixCollapsed =
      rawAppendix != null &&
      (collapsedFromSet || rawAppendix.collapsed === true);
    const appendix: CellExecutionAppendixSpec | null = rawAppendix
      ? isAppendixCollapsed || rawAppendix.collapsed !== undefined
        ? { ...rawAppendix, collapsed: isAppendixCollapsed }
        : rawAppendix
      : null;
    const effectiveAppendixCells = appendix
      ? isAppendixCollapsed
        ? 2
        : Math.max(MIN_APPENDIX_CELLS, appendix.heightCells)
      : 0;
    // Counted the way the card lays its two-column shelves out.
    const configCells = countConfigShelfCells(configFields);
    // Config shelves end on an empty row so the plate's bottom inset never
    // clips their last control; an appendix closes the card itself.
    const tailCells =
      effectiveAppendixCells > 0
        ? effectiveAppendixCells
        : configCells > 0
          ? 1
          : 0;
    const bandCells = collection
      ? collectionHeightCells(
          collection.members.length + (collection.showSparePlug ? 1 : 0),
        )
      : nextRow + configCells + tailCells;
    const minHeightCells = collection
      ? collectionHeightCells(1)
      : Math.max(MIN_OPERATOR_HEIGHT_CELLS, nextRow);
    const heightCells = Math.max(
      minHeightCells,
      bandCells,
      snapPixelsToCell(node.layout?.body_height ?? 0) + effectiveAppendixCells,
    );

    cards.push({
      id: node.id,
      title: spec?.title || node.operator_id,
      subtitle: spec?.description || node.operator_id,
      kind,
      ...(runState?.status !== undefined ? { status: runState.status } : {}),
      ...cellOriginFromWorld(node.position),
      widthCells,
      heightCells,
      ports,
      resizable: true,
      resizeBounds: {
        minWidthCells: MIN_CARD_WIDTH_CELLS,
        maxWidthCells: MAX_CARD_WIDTH_CELLS,
        minHeightCells,
        maxHeightCells: MAX_CARD_HEIGHT_CELLS,
      },
    });
    surfaces.set(
      node.id,
      collection ?? {
        kind: "operator",
        ...(runState?.statusLabel !== undefined
          ? { statusLabel: runState.statusLabel }
          : {}),
        ...(runState?.runDisabled !== undefined
          ? { runDisabled: runState.runDisabled }
          : {}),
        configFields,
        ...(configSections ? { configSections } : {}),
        ...(connectedInputPorts ? { connectedInputPorts } : {}),
        ...(secretInputs.length > 0 ? { secretInputs } : {}),
        instancePlugGroups: groups,
        appendix,
      },
    );
  }

  return { cards, surfaces, specsByNode };
}

export function graphCommandsFromCellMoves(
  moves: readonly { cardId: string; col: number; row: number }[],
): GraphCommand[] {
  if (moves.length === 0) return [];
  return [
    {
      kind: "move_nodes",
      positions: moves.map(({ cardId, col, row }) => ({
        node_id: cardId,
        ...cellToWorldOrigin(col, row),
      })),
    },
  ];
}

/**
 * The layout a resize writes back. A dragged card snaps to whole cells, so its
 * pixels can still sit under the API's floors, and a stale saved appendix can
 * sit under its own: clamping through {@link serializeNodeLayout} is what keeps
 * every emitted `update_node_layout` inside `GraphNodeLayout`'s bounds.
 */
export function graphCommandsFromCellResize(
  commit: CellResizeCommit,
  existingLayout?: SavedNodeLayout | null,
): GraphCommand[] {
  const rawWidth = Number.isFinite(commit.widthCells)
    ? commit.widthCells * CELL_SIZE
    : existingLayout?.width != null && Number.isFinite(existingLayout.width)
      ? existingLayout.width
      : NODE_WIDTH_MIN;
  const rawBodyHeight = Number.isFinite(commit.heightCells)
    ? commit.heightCells * CELL_SIZE
    : existingLayout?.body_height != null &&
        Number.isFinite(existingLayout.body_height)
      ? existingLayout.body_height
      : BODY_HEIGHT_MIN;
  const rawAppendixHeight =
    existingLayout?.appendix_height != null &&
    Number.isFinite(existingLayout.appendix_height) &&
    existingLayout.appendix_height > 0
      ? existingLayout.appendix_height
      : undefined;
  const layout = serializeNodeLayout({
    width: rawWidth,
    bodyHeight: rawBodyHeight,
    appendixHeight: rawAppendixHeight,
  });
  return [
    {
      kind: "update_node_layout",
      node_id: commit.cardId,
      // A finite commit always clamps to something; this is the shape only.
      layout: layout ?? {
        width: NODE_WIDTH_MIN,
        body_height: BODY_HEIGHT_MIN,
        appendix_height: null,
      },
    },
  ];
}

export function graphCommandsFromCellDelete(
  cardIds: readonly string[],
  pipeIds: readonly string[],
): GraphCommand[] {
  const commands: GraphCommand[] = [];
  if (pipeIds.length > 0)
    commands.push({ kind: "remove_edges", edge_ids: pipeIds });
  if (cardIds.length > 0)
    commands.push({ kind: "remove_nodes", node_ids: cardIds });
  return commands;
}

export function graphCommandsFromCellConfigChange(
  cardId: string,
  fieldId: string,
  value: unknown,
): GraphCommand[] {
  return [
    {
      kind: "update_node_configuration",
      node_id: cardId,
      field: fieldId,
      value,
    },
  ];
}

export function graphCommandsFromCellAddPlug(
  cardId: string,
  portName: string,
  existingPlugs: readonly { id: string; port: string }[],
): GraphCommand[] {
  const usedIds = new Set(existingPlugs.map((plug) => plug.id));
  const portPlugsCount = existingPlugs.filter(
    (plug) => plug.port === portName,
  ).length;
  let index = portPlugsCount + 1;
  let plugId = `${portName}-plug-${index}`;
  while (usedIds.has(plugId)) {
    index += 1;
    plugId = `${portName}-plug-${index}`;
  }
  return [
    {
      kind: "add_input_plug",
      node_id: cardId,
      plug: { id: plugId, port: portName },
    },
  ];
}

export function graphCommandsFromCellRemovePlug(
  cardId: string,
  portName: string,
  plugId: string,
): GraphCommand[] {
  const prefix = `${portName}${PLUG_SEPARATOR}`;
  const rawPlugId = plugId.startsWith(prefix)
    ? plugId.slice(prefix.length)
    : plugId;
  return [
    {
      kind: "remove_input_plug",
      node_id: cardId,
      plug_id: rawPlugId,
    },
  ];
}

export function graphCommandsFromCellMovesForDocument(
  document: AuthoredGraphDocument,
  moves: readonly { cardId: string; col: number; row: number }[],
): GraphCommand[] {
  if (moves.length === 0) return [];
  const nodeIds = new Set(document.nodes.map((node) => node.id));
  const agentsById = new Map(document.agents.map((agent) => [agent.id, agent]));
  const nodeMoves: { cardId: string; col: number; row: number }[] = [];
  const agentCommands: GraphCommand[] = [];
  for (const move of moves) {
    if (nodeIds.has(move.cardId)) {
      nodeMoves.push(move);
      continue;
    }
    const agent = agentsById.get(move.cardId);
    if (agent) {
      agentCommands.push({
        kind: "configure_agent",
        agent: {
          ...agent,
          position: cellToWorldOrigin(move.col, move.row),
        },
      });
    }
  }
  return [...graphCommandsFromCellMoves(nodeMoves), ...agentCommands];
}

/** An agent's box is bounded by `GraphAgent`, which has no appendix to carry. */
function clampAgentDimension(
  value: number,
  fallback: number,
  min: number,
): number {
  const candidate = Number.isFinite(value)
    ? value
    : Number.isFinite(fallback)
      ? fallback
      : min;
  return Math.min(LAYOUT_DIMENSION_MAX, Math.max(min, candidate));
}

export function graphCommandsFromCellResizeForDocument(
  document: AuthoredGraphDocument,
  commit: CellResizeCommit,
): GraphCommand[] {
  const node = document.nodes.find(
    (candidate) => candidate.id === commit.cardId,
  );
  if (node) {
    return graphCommandsFromCellResize(commit, node.layout);
  }
  const agent = document.agents.find(
    (candidate) => candidate.id === commit.cardId,
  );
  if (agent) {
    return [
      {
        kind: "configure_agent",
        agent: {
          ...agent,
          width: clampAgentDimension(
            commit.widthCells * CELL_SIZE,
            agent.width,
            NODE_WIDTH_MIN,
          ),
          height: clampAgentDimension(
            commit.heightCells * CELL_SIZE,
            agent.height,
            BODY_HEIGHT_MIN,
          ),
        },
      },
    ];
  }
  return [];
}

export function graphCommandsFromCellDeleteForDocument(
  document: AuthoredGraphDocument,
  cardIds: readonly string[],
  pipeIds: readonly string[],
): GraphCommand[] {
  const edgeIds = new Set(document.edges.map((edge) => edge.id));
  const nodeIds = new Set(document.nodes.map((node) => node.id));
  const agentIds = new Set(document.agents.map((agent) => agent.id));

  const docEdgeIds = pipeIds.filter((id) => edgeIds.has(id));
  const docNodeIds = cardIds.filter((id) => nodeIds.has(id));
  const docAgentIds = cardIds.filter((id) => agentIds.has(id));

  const commands = graphCommandsFromCellDelete(docNodeIds, docEdgeIds);
  for (const agentId of docAgentIds) {
    commands.push({ kind: "remove_agent", agent_id: agentId });
  }
  return commands;
}
