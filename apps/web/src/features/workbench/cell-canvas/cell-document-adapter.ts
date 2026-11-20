import type {
  ArtifactTypeKey,
  NodeRegistry,
  NodeSpec,
  Port,
  SavedGraphDocument,
} from "@/lib/api";

import { DEFAULT_ARTIFACT_CARD_WIDTH } from "../canvas/artifact-card";
import { schemaFields, type SchemaField } from "../canvas/config-schema";
import {
  DEFAULT_NODE_WIDTH,
  type SavedNodeLayout,
} from "../canvas/node-layout";
import {
  configBoardColumns,
  configControlKind,
  fieldFootprint,
  packFieldFootprints,
  type ConfigControlKind,
  type FieldFootprint,
} from "../canvas/nodes/field-footprints";
import {
  COLLECTION_OPERATOR_ID,
  COLLECTION_PORT,
  isCollectionSpec,
} from "../model/collection-spec";
import type {
  AuthoredGraphDocument,
  AuthoredGraphEdge,
  AuthoredGraphNode,
  AuthoredGraphOrigin,
  GraphCommand,
} from "../model/graph-document";
import type {
  AnnotationColorToken,
  CellCardSurfaceData,
  CellConfigFieldKind,
  CellConfigFieldSpec,
  CellInstancePlugGroup,
  CellResizeCommit,
  CollectionCardSurfaceData,
} from "./cell-contracts";
import {
  CELL_SIZE,
  cellToWorldOrigin,
  type CellCardModel,
  type CellCoord,
  type CellGraph,
  type CellPort,
} from "./cell-model";

const PLUG_SEPARATOR = "::";

export function snapPixelsToCell(px: number): number {
  const cells = Math.round(px / CELL_SIZE);
  return Object.is(cells, -0) ? 0 : cells;
}

export function cellOriginFromWorld(pos: { x: number; y: number }): CellCoord {
  return { col: snapPixelsToCell(pos.x), row: snapPixelsToCell(pos.y) };
}

function targetPortId(port: string, plug: string | null | undefined): string {
  return plug ? `${port}${PLUG_SEPARATOR}${plug}` : port;
}

function nodeSpec(node: AuthoredGraphNode, registry: NodeRegistry) {
  return (
    registry.nodes.find(
      (spec) =>
        spec.operator_id === node.operator_id &&
        spec.operator_version === node.operator_version,
    ) ?? registry.nodes.find((spec) => spec.operator_id === node.operator_id)
  );
}

function portArtifactType(node: AuthoredGraphNode, port: Port | undefined) {
  const variable = port?.artifact_type_variable;
  const binding = variable
    ? node.artifact_type_bindings.find(
        (candidate) => candidate.variable === variable,
      )
    : undefined;
  return binding?.artifact_type ?? port?.artifact_type;
}

function portTypeId(node: AuthoredGraphNode, port: Port): string {
  return (
    portArtifactType(node, port)?.id ??
    port.artifact_type_variable ??
    "artifact"
  );
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

function nodePorts(
  node: AuthoredGraphNode,
  spec: NodeSpec | undefined,
  connections: ReadonlyMap<string, PlugConnection> | undefined,
) {
  const inputs = spec?.inputs ?? [];
  const fixedInputs = inputs.filter((port) => !port.instance_plugs);
  const outputs = spec?.outputs ?? [];
  const fixedPort = (port: Port, index: number): CellPort => ({
    id: port.name,
    name: port.title || port.name,
    direction: port.direction,
    rowOffset: 1 + index,
    artifactTypeId: portTypeId(node, port),
    shape: port.shape,
    required: port.required,
  });
  const ports = [...fixedInputs.map(fixedPort), ...outputs.map(fixedPort)];
  const groups: CellInstancePlugGroup[] = [];
  let nextRow = 1 + Math.max(fixedInputs.length, outputs.length);

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
          rowOffset: nextRow++,
          artifactTypeId,
          shape: port.shape,
          required: port.required,
        });
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
  }
  return { ports, groups, nextRow };
}

const FIELD_KINDS: Record<ConfigControlKind, CellConfigFieldKind> = {
  text: "text",
  number: "number",
  select: "select",
  checkbox: "toggle",
  textarea: "multiline",
  "number-tuple": "text",
  "string-list": "multiline",
  secret: "text",
};

function configField(
  node: AuthoredGraphNode,
  field: SchemaField,
  footprint: FieldFootprint,
): CellConfigFieldSpec {
  const kind = FIELD_KINDS[configControlKind(field)];
  const saved = node.config?.[field.name];
  const fallback = kind === "toggle" ? false : kind === "number" ? 0 : "";
  const value =
    typeof saved === "string" ||
    typeof saved === "number" ||
    typeof saved === "boolean"
      ? saved
      : Array.isArray(saved)
        ? JSON.stringify(saved)
        : fallback;
  return {
    id: field.name,
    label: field.title,
    kind,
    value,
    options: field.enumValues?.map((option) => ({
      value: String(option),
      label: String(option),
    })),
    span: footprint.columns >= 6 ? 2 : 1,
    denseRows: footprint.rows * 2,
  };
}

function collectionTypeLabel(
  artifactType: ArtifactTypeKey | null | undefined,
  catalog: NodeRegistry["artifact_types"],
): string {
  if (!artifactType) return "Artifact";
  const { id, schema_version: version } = artifactType;
  const title = catalog
    .find(
      (entry) => entry.key.id === id && entry.key.schema_version === version,
    )
    ?.title.trim();
  if (!title) return `${id}@${version}`;
  return version > 1 ? `${title} · v${version}` : title;
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
  return {
    kind: "collection",
    artifactTypeId,
    typeLabel,
    members,
    showSparePlug: true,
  };
}

function annotationColor(color: string): AnnotationColorToken {
  switch (color.toLowerCase()) {
    case "blue":
    case "#0369a1":
      return "blue";
    case "emerald":
    case "#047857":
      return "emerald";
    case "amber":
    case "#b45309":
      return "amber";
    case "violet":
    case "#6d28d9":
      return "violet";
    case "rose":
    case "#be123c":
      return "rose";
    default:
      return "slate";
  }
}

export function cellGraphFromAuthoredDocument(
  document: AuthoredGraphDocument,
  registry: NodeRegistry,
  options?: { presentation?: SavedGraphDocument["presentation"] | null },
): { graph: CellGraph; surfaceById: Record<string, CellCardSurfaceData> } {
  const cards: CellCardModel[] = [];
  const surfaces = new Map<string, CellCardSurfaceData>();
  const specsByNode = new Map(
    document.nodes.map((node) => [node.id, nodeSpec(node, registry)]),
  );
  const connections = connectionsByNode(document);

  for (const node of document.nodes) {
    const spec = specsByNode.get(node.id);
    const isCollection =
      isCollectionSpec(spec) || node.operator_id === COLLECTION_OPERATOR_ID;
    const kind = isCollection ? "collection" : "operator";
    const defaultWidth = isCollection
      ? DEFAULT_ARTIFACT_CARD_WIDTH
      : DEFAULT_NODE_WIDTH;
    const widthCells = Math.max(
      4,
      snapPixelsToCell(node.layout?.width ?? defaultWidth),
    );
    const nodeConnections = connections.get(node.id);
    const { ports, groups, nextRow } = nodePorts(node, spec, nodeConnections);

    const fields = schemaFields(spec?.config_schema).map((field) => ({
      field,
      footprint: fieldFootprint(field),
    }));
    const packedBoard = packFieldFootprints(
      fields.map(({ footprint }) => footprint),
      {
        columns: configBoardColumns(widthCells * CELL_SIZE, CELL_SIZE),
      },
    );
    const appendixHeight = node.layout?.appendix_height ?? 0;
    const appendixCells =
      appendixHeight > 0
        ? Math.max(2, Math.ceil(appendixHeight / CELL_SIZE))
        : 0;
    const heightCells = Math.max(
      2,
      nextRow + packedBoard.rows + appendixCells,
      snapPixelsToCell(node.layout?.body_height ?? 0) + appendixCells,
    );

    cards.push({
      id: node.id,
      title: spec?.title || node.operator_id,
      subtitle: node.operator_id,
      kind,
      ...cellOriginFromWorld(node.position),
      widthCells,
      heightCells,
      ports,
      resizable: true,
      resizeBounds: {
        minWidthCells: 4,
        maxWidthCells: 24,
        minHeightCells: Math.max(2, nextRow),
        maxHeightCells: 30,
      },
    });
    surfaces.set(
      node.id,
      isCollection
        ? collectionSurface(
            node,
            spec,
            nodeConnections,
            specsByNode,
            registry.artifact_types,
          )
        : {
            kind: "operator",
            configFields: fields.map(({ field, footprint }) =>
              configField(node, field, footprint),
            ),
            instancePlugGroups: groups,
            appendix:
              appendixCells > 0
                ? {
                    title: "Execution output",
                    kindBadge: "Output",
                    heightCells: appendixCells,
                    summaryText: "",
                  }
                : null,
          },
    );
  }

  for (const agent of document.agents) {
    const modelLabel =
      agent.model?.kind === "custom" ? agent.model.model : "Deployment model";
    cards.push({
      id: agent.id,
      kind: "agent",
      title: agent.name || "Agent",
      subtitle: modelLabel,
      ...cellOriginFromWorld(agent.position ?? { x: 0, y: 0 }),
      widthCells: Math.max(5, snapPixelsToCell(agent.width || 360)),
      heightCells: Math.max(4, snapPixelsToCell(agent.height || 200)),
      ports: [],
      resizable: true,
    });
    surfaces.set(agent.id, {
      kind: "agent",
      modelLabel,
      linkedToolCount: agent.tools.length,
      agentStatus: "idle",
      lastMessageSnippet: agent.instructions || undefined,
    });
  }

  for (const annotation of options?.presentation?.annotations ?? []) {
    const isNote = annotation.kind === "text";
    cards.push({
      id: annotation.id,
      kind: "annotation",
      title: isNote ? "Note" : "Frame",
      subtitle: annotation.kind,
      ...cellOriginFromWorld(annotation.position),
      widthCells: Math.max(3, snapPixelsToCell(annotation.layout.width)),
      heightCells: Math.max(2, snapPixelsToCell(annotation.layout.height)),
      ports: [],
      resizable: true,
    });
    surfaces.set(annotation.id, {
      kind: "annotation",
      variant: isNote ? "note" : "frame",
      color: annotationColor(annotation.color),
      bodyText: annotation.text ?? "",
      layer: "under-cards",
    });
  }

  return {
    graph: {
      cards,
      pipes: document.edges.map((edge) => ({
        id: edge.id,
        sourceCardId: edge.from_node,
        sourcePortId: edge.from_port,
        targetCardId: edge.to_node,
        targetPortId: targetPortId(edge.to_port, edge.to_plug),
        enabled: edge.enabled,
        projectionLabel: edge.projection?.path.length
          ? edge.projection.path.join(".")
          : null,
        conversionLabel: edge.conversion_path.length
          ? `${edge.conversion_path.length} conv`
          : null,
      })),
    },
    surfaceById: Object.fromEntries(surfaces),
  };
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

export function graphCommandsFromCellResize(
  commit: CellResizeCommit,
  existingLayout?: SavedNodeLayout | null,
): GraphCommand[] {
  return [
    {
      kind: "update_node_layout",
      node_id: commit.cardId,
      layout: {
        width: commit.widthCells * CELL_SIZE,
        body_height: commit.heightCells * CELL_SIZE,
        appendix_height: existingLayout?.appendix_height ?? null,
      },
    },
  ];
}

export function graphCommandsFromCellConnect(params: {
  edgeId: string;
  sourceCardId: string;
  sourcePortName: string;
  targetCardId: string;
  targetPortName: string;
  targetPlugId?: string | null;
}): GraphCommand[] {
  const separator = params.targetPortName.indexOf(PLUG_SEPARATOR);
  const split = params.targetPlugId === undefined && separator >= 0;
  const toPort = split
    ? params.targetPortName.slice(0, separator)
    : params.targetPortName;
  const toPlug = split
    ? params.targetPortName.slice(separator + PLUG_SEPARATOR.length)
    : (params.targetPlugId ?? null);
  return [
    {
      kind: "add_edge",
      edge: {
        id: params.edgeId,
        from_node: params.sourceCardId,
        from_port: params.sourcePortName,
        to_node: params.targetCardId,
        to_port: toPort,
        to_plug: toPlug,
        enabled: true,
        collection_mode: "direct",
        projection: null,
        conversion_path: [],
        route_offset: null,
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
