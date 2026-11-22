import type {
  ArtifactTypeKey,
  NodeRegistry,
  NodeSpec,
  Port,
  SavedGraphDocument,
  ServiceContract,
} from "@/lib/api";

import {
  ARTIFACT_CARD_HEIGHT_MAX,
  ARTIFACT_CARD_HEIGHT_MIN,
  ARTIFACT_CARD_WIDTH_MAX,
  ARTIFACT_CARD_WIDTH_MIN,
  cardArtifactRefs,
  DEFAULT_ARTIFACT_CARD_WIDTH,
} from "../canvas/artifact-card";
import { schemaFields, type SchemaField } from "../canvas/config-schema";
import {
  DEFAULT_NODE_WIDTH,
  type SavedNodeLayout,
} from "../canvas/node-layout";
import {
  configControlKind,
  fieldFootprint,
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
  ArtifactPreviewKind,
  ArtifactStackItem,
  CellCardSurfaceData,
  CellConfigFieldKind,
  CellConfigFieldSpec,
  CellExecutionAppendixSpec,
  CellInstancePlugGroup,
  CellResizeCommit,
  CollectionCardSurfaceData,
} from "./cell-contracts";
import { countConfigShelfCells } from "./cell-card-geometry";
import {
  CARD_PLATE_BOTTOM_INSET,
  CARD_PLATE_INSET_X,
  CARD_PLATE_TOP,
  CELL_SIZE,
  STRIP_FIRST_PORT_ROW,
  artifactCardOutputRow,
  FIRST_PORT_ROW,
  PORT_ROW_PITCH,
  cellToWorldOrigin,
  collectionHeightCells,
  type CellCardModel,
  type CellCoord,
  type CellGraph,
  type CellPipeModel,
  type CellPort,
} from "./cell-model";

const PLUG_SEPARATOR = "::";
/** A config footprint row is 50px: two 25px dense rows, two cells. */
const CELLS_PER_FOOTPRINT_ROW = 2;
/**
 * A node secret's label, input and save hint fit three dense rows; its
 * two-row footprint would leave a dense row empty under the hint.
 */
const SECRET_DENSE_ROWS = 3;
/** An expanded execution appendix is never shorter than four cells. */
const MIN_APPENDIX_CELLS = 4;
/** An operator never shrinks below its header and one port row. */
const MIN_OPERATOR_HEIGHT_CELLS = 4;
const MIN_CARD_WIDTH_CELLS = 8;
const MAX_CARD_WIDTH_CELLS = 48;
const MAX_CARD_HEIGHT_CELLS = 60;
/** Artifact card bounds derived directly from the shared pixel floor/ceiling (6×3..48×48 cells). */
const MIN_ARTIFACT_WIDTH_CELLS = Math.ceil(ARTIFACT_CARD_WIDTH_MIN / CELL_SIZE);
const MAX_ARTIFACT_WIDTH_CELLS = Math.floor(
  ARTIFACT_CARD_WIDTH_MAX / CELL_SIZE,
);
const MIN_ARTIFACT_HEIGHT_CELLS = Math.ceil(
  ARTIFACT_CARD_HEIGHT_MIN / CELL_SIZE,
);
const MAX_ARTIFACT_HEIGHT_CELLS = Math.floor(
  ARTIFACT_CARD_HEIGHT_MAX / CELL_SIZE,
);
/** Default height for unsized artifact cards when natural dimensions are unknown. */
const DEFAULT_ARTIFACT_HEIGHT_CELLS = 6;
/** Tall unsized portraits cap at 350px (14 cells) so they stay thumbnail-sized. */
const MAX_AUTO_ARTIFACT_HEIGHT_CELLS = 14;
const DEFAULT_ARTIFACT_WIDTH_CELLS = Math.max(
  MIN_ARTIFACT_WIDTH_CELLS,
  Math.round(DEFAULT_ARTIFACT_CARD_WIDTH / CELL_SIZE),
);

export function snapPixelsToCell(px: number): number {
  const cells = Math.round(px / CELL_SIZE);
  return Object.is(cells, -0) ? 0 : cells;
}

/**
 * Grid footprint for an image artifact card from its natural pixel size,
 * honouring any explicit width/body_height the user already saved.
 */
export function cellArtifactImageCells(
  natural: { width: number; height: number } | null | undefined,
  layout?: { width?: number | null; body_height?: number | null } | null,
): { widthCells: number; heightCells: number } {
  const savedWidth =
    layout?.width != null && layout.width > 0
      ? Math.min(
          MAX_ARTIFACT_WIDTH_CELLS,
          Math.max(MIN_ARTIFACT_WIDTH_CELLS, snapPixelsToCell(layout.width)),
        )
      : null;
  const savedHeight =
    layout?.body_height != null && layout.body_height > 0
      ? Math.min(
          MAX_ARTIFACT_HEIGHT_CELLS,
          Math.max(
            MIN_ARTIFACT_HEIGHT_CELLS,
            snapPixelsToCell(layout.body_height),
          ),
        )
      : null;

  if (
    !natural ||
    natural.width <= 0 ||
    natural.height <= 0 ||
    (savedWidth !== null && savedHeight !== null)
  ) {
    return {
      widthCells: savedWidth ?? DEFAULT_ARTIFACT_WIDTH_CELLS,
      heightCells: savedHeight ?? DEFAULT_ARTIFACT_HEIGHT_CELLS,
    };
  }

  const aspect = natural.width / natural.height;
  const insetX = CARD_PLATE_INSET_X * 2;
  const insetY = CARD_PLATE_TOP + CARD_PLATE_BOTTOM_INSET;

  if (savedWidth !== null) {
    const plateW = savedWidth * CELL_SIZE - insetX;
    const heightCells = Math.min(
      MAX_ARTIFACT_HEIGHT_CELLS,
      Math.max(
        MIN_ARTIFACT_HEIGHT_CELLS,
        snapPixelsToCell(plateW / aspect + insetY),
      ),
    );
    return { widthCells: savedWidth, heightCells };
  }

  if (savedHeight !== null) {
    const plateH = savedHeight * CELL_SIZE - insetY;
    const widthCells = Math.min(
      MAX_ARTIFACT_WIDTH_CELLS,
      Math.max(
        MIN_ARTIFACT_WIDTH_CELLS,
        snapPixelsToCell(plateH * aspect + insetX),
      ),
    );
    return { widthCells, heightCells: savedHeight };
  }

  const defaultPlateW = DEFAULT_ARTIFACT_WIDTH_CELLS * CELL_SIZE - insetX;
  const rawHeightCells = snapPixelsToCell(defaultPlateW / aspect + insetY);
  if (rawHeightCells <= MAX_AUTO_ARTIFACT_HEIGHT_CELLS) {
    return {
      widthCells: DEFAULT_ARTIFACT_WIDTH_CELLS,
      heightCells: Math.max(MIN_ARTIFACT_HEIGHT_CELLS, rawHeightCells),
    };
  }
  const cappedPlateH = MAX_AUTO_ARTIFACT_HEIGHT_CELLS * CELL_SIZE - insetY;
  const widthCells = Math.min(
    DEFAULT_ARTIFACT_WIDTH_CELLS,
    Math.max(
      MIN_ARTIFACT_WIDTH_CELLS,
      snapPixelsToCell(cappedPlateH * aspect + insetX),
    ),
  );
  return {
    widthCells,
    heightCells: MAX_AUTO_ARTIFACT_HEIGHT_CELLS,
  };
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
    // A switch carries its label beside it, so it never needs a label row.
    denseRows:
      kind === "toggle"
        ? footprint.rows * CELLS_PER_FOOTPRINT_ROW - 1
        : footprint.rows * CELLS_PER_FOOTPRINT_ROW,
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

export interface CellNodeRunState {
  status?: CellCardModel["status"];
  statusLabel?: string;
  runDisabled?: boolean;
  appendix?: CellExecutionAppendixSpec | null;
}

export interface CellOriginLink {
  id: string;
  originId: string;
  sourceCardId: string;
  targetCardId: string;
  targetPortId: string;
  collectionMode: "direct" | "map";
  conversionCount?: number;
}

export interface CellPipeMetadata {
  projectionLabel?: string | null;
  conversionLabel?: string | null;
  sourcePortLabel?: string;
  incompatible?: boolean;
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

export function annotationHexFromToken(color: AnnotationColorToken): string {
  switch (color) {
    case "blue":
      return "#0369a1";
    case "emerald":
      return "#047857";
    case "amber":
      return "#b45309";
    case "violet":
      return "#6d28d9";
    case "rose":
      return "#be123c";
    case "slate":
      return "#475569";
  }
}

function viewerPreviewKind(artifactTypeId: string): ArtifactPreviewKind {
  const lower = artifactTypeId.toLowerCase();
  if (
    lower.startsWith("image.") ||
    lower === "geo.raster_scan" ||
    /^file\.(png|jpe?g|tiff|webp|bmp)$/.test(lower)
  ) {
    return "image";
  }
  if (lower.startsWith("table.") || lower.includes("tabular")) return "table";
  if (lower.startsWith("geo.")) return "map";
  if (
    lower === "text.markdown" ||
    lower === "scalar.text" ||
    lower === "llm.completion" ||
    lower.startsWith("text.") ||
    lower.startsWith("prompt.")
  ) {
    return "markdown";
  }
  return "file";
}

/** What an artifact card can paint of its current value. */
export interface CellViewerImages {
  /** The first item's picture, or null when the browser cannot paint it. */
  imageUrl: string | null;
  /** Up to two following items' pictures, for the fanned stack. */
  stackImageUrls: readonly string[];
  /** Items the card holds: 1 for a single artifact. */
  itemCount: number;
  /** Natural pixel dimensions of the lead image once decoded, for auto-fit sizing. */
  naturalSize?: { width: number; height: number } | null;
}

/** What the caller knows about an artifact card's file, already worded. */
export interface CellViewerMetadata {
  /** The file's name as the Library shows it. */
  filename?: string | null;
  /** The file's size, already formatted (`12 KB`). */
  byteSizeLabel?: string | null;
  /** Every item of a sequence, named and pictured, for its spread. */
  stackItems?: readonly ArtifactStackItem[];
}

export function cellGraphFromAuthoredDocument(
  document: AuthoredGraphDocument,
  registry: NodeRegistry,
  options?: {
    presentation?: SavedGraphDocument["presentation"] | null;
    nodeRunState?: Readonly<Record<string, CellNodeRunState>>;
    collapsedAppendices?: ReadonlySet<string>;
    originLinks?: readonly CellOriginLink[];
    viewerOutputValues?: ReadonlyMap<
      string,
      { artifactTypeId: string; schemaVersion?: number; shape: "one" | "many" }
    >;
    pipeMetadataById?: ReadonlyMap<string, CellPipeMetadata>;
    /**
     * Pictures resolved for artifact cards, by card id. The caller owns the
     * URLs, so this adapter never names the API.
     */
    viewerImages?: ReadonlyMap<string, CellViewerImages>;
    /**
     * File names and sizes for artifact cards, by card id. Like
     * `viewerImages`, the caller resolves them, so this adapter never reads
     * the Library.
     */
    viewerMetadata?: ReadonlyMap<string, CellViewerMetadata>;
  },
): { graph: CellGraph; surfaceById: Record<string, CellCardSurfaceData> } {
  const cards: CellCardModel[] = [];
  const surfaces = new Map<string, CellCardSurfaceData>();
  const specsByNode = new Map(
    document.nodes.map((node) => [node.id, nodeSpec(node, registry)]),
  );
  const connections = connectionsByNode(document);

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

    const fields = schemaFields(spec?.config_schema).map((field) => ({
      field,
      footprint: fieldFootprint(field),
    }));
    const secretInputs = isCollection ? [] : (spec?.secret_inputs ?? []);
    const configFields: CellConfigFieldSpec[] = [
      ...fields.map(({ field, footprint }) =>
        configField(node, field, footprint),
      ),
      ...secretInputs.map((input): CellConfigFieldSpec => ({
        id: input.name,
        label: input.title || input.name,
        kind: "secret",
        value: "",
        span: 2,
        denseRows: SECRET_DENSE_ROWS,
        ...(input.description == null
          ? {}
          : { description: input.description }),
      })),
    ];
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
        instancePlugGroups: groups,
        appendix,
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
      widthCells: Math.max(10, snapPixelsToCell(agent.width || 360)),
      heightCells: Math.max(8, snapPixelsToCell(agent.height || 200)),
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

  const presentationLinks = options?.presentation?.links ?? [];
  const viewers = options?.presentation?.viewers ?? [];
  for (const viewer of viewers) {
    if (
      !viewer?.id ||
      typeof viewer.position?.x !== "number" ||
      !Number.isFinite(viewer.position.x) ||
      typeof viewer.position?.y !== "number" ||
      !Number.isFinite(viewer.position.y)
    ) {
      continue;
    }
    const feedLink = presentationLinks.find(
      (link) => link.target_viewer_id === viewer.id,
    );
    const ref = viewer.artifact_ref ?? null;
    const feedNode = feedLink
      ? document.nodes.find((n) => n.id === feedLink.source_node_id)
      : undefined;
    const feedSpec = feedNode ? specsByNode.get(feedNode.id) : undefined;
    const feedPort = feedSpec?.outputs.find(
      (p) => p.name === feedLink?.source_port_name,
    );
    const fallbackType =
      feedNode && feedPort ? portArtifactType(feedNode, feedPort) : undefined;
    const liveOutput = options?.viewerOutputValues?.get(viewer.id);
    // A following card shows what its producer last made, which may be
    // narrower than the port's declared type (a PNG out of an image port).
    const artifactKey: ArtifactTypeKey | null = ref
      ? { id: ref.artifact_type, schema_version: ref.schema_version }
      : liveOutput?.schemaVersion !== undefined
        ? {
            id: liveOutput.artifactTypeId,
            schema_version: liveOutput.schemaVersion,
          }
        : (fallbackType ?? null);
    const artifactTypeId = artifactKey?.id ?? "artifact";
    const typeLabel = collectionTypeLabel(artifactKey, registry.artifact_types);
    const previewKind = viewerPreviewKind(artifactTypeId);
    const viewerPorts: CellPort[] = [];
    if (feedLink || !ref) {
      viewerPorts.push({
        id: "artifact-viewer-input",
        name: "feed",
        direction: "input",
        rowOffset: STRIP_FIRST_PORT_ROW,
        artifactTypeId,
        shape: "one",
      });
    }
    const images = options?.viewerImages?.get(viewer.id);
    const minHeightCells = feedLink
      ? STRIP_FIRST_PORT_ROW + 2
      : MIN_ARTIFACT_HEIGHT_CELLS;
    const rawCells =
      previewKind === "image"
        ? cellArtifactImageCells(images?.naturalSize, viewer.layout)
        : {
            widthCells: Math.min(
              MAX_ARTIFACT_WIDTH_CELLS,
              Math.max(
                MIN_ARTIFACT_WIDTH_CELLS,
                snapPixelsToCell(
                  viewer.layout?.width ?? DEFAULT_ARTIFACT_CARD_WIDTH,
                ),
              ),
            ),
            heightCells: Math.min(
              MAX_ARTIFACT_HEIGHT_CELLS,
              Math.max(
                minHeightCells,
                snapPixelsToCell(viewer.layout?.body_height ?? 150),
              ),
            ),
          };
    const widthCells = rawCells.widthCells;
    const heightCells = Math.max(minHeightCells, rawCells.heightCells);
    if (ref || liveOutput) {
      viewerPorts.push({
        id: "artifact-card-output",
        name: "artifact",
        direction: "output",
        rowOffset: artifactCardOutputRow(heightCells),
        artifactTypeId: ref
          ? ref.artifact_type
          : (liveOutput?.artifactTypeId ?? artifactTypeId),
        shape: ref
          ? "item_refs" in ref
            ? "many"
            : "one"
          : (liveOutput?.shape ?? "one"),
      });
    }
    const metadata = options?.viewerMetadata?.get(viewer.id);
    const filename = metadata?.filename ?? feedLink?.source_port_name;
    const itemCount =
      ref && "item_refs" in ref ? ref.item_refs.length : images?.itemCount;
    const itemCountLabel =
      itemCount !== undefined && itemCount > 1
        ? `${itemCount} items`
        : undefined;
    cards.push({
      id: viewer.id,
      kind: "artifact",
      title: typeLabel,
      subtitle: itemCountLabel ?? (feedLink ? "From output" : typeLabel),
      ...cellOriginFromWorld(viewer.position),
      widthCells,
      heightCells,
      ports: viewerPorts,
      resizable: true,
      resizeBounds: {
        minWidthCells: MIN_ARTIFACT_WIDTH_CELLS,
        maxWidthCells: MAX_ARTIFACT_WIDTH_CELLS,
        minHeightCells,
        maxHeightCells: MAX_ARTIFACT_HEIGHT_CELLS,
      },
    });
    surfaces.set(viewer.id, {
      kind: "artifact",
      previewKind,
      artifactTypeId,
      typeLabel,
      ...(itemCountLabel ? { dimensionsLabel: itemCountLabel } : {}),
      ...(itemCount !== undefined && itemCount > 1 ? { itemCount } : {}),
      ...(itemCount !== undefined && itemCount > 1 && metadata?.stackItems
        ? { stackItems: metadata.stackItems }
        : {}),
      ...(filename ? { filename } : {}),
      ...(metadata?.byteSizeLabel
        ? { byteSizeLabel: metadata.byteSizeLabel }
        : {}),
      ...(previewKind === "image" && images
        ? {
            imageUrl: images.imageUrl,
            ...(images.stackImageUrls.length
              ? { stackImageUrls: images.stackImageUrls }
              : {}),
          }
        : {}),
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
      widthCells: Math.max(6, snapPixelsToCell(annotation.layout.width)),
      heightCells: Math.max(4, snapPixelsToCell(annotation.layout.height)),
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

  const cardIds = new Set(cards.map((card) => card.id));
  const originPipes: CellPipeModel[] = [];
  if (options?.originLinks !== undefined) {
    for (const link of options.originLinks) {
      if (!cardIds.has(link.sourceCardId) || !cardIds.has(link.targetCardId)) {
        continue;
      }
      originPipes.push({
        id: link.id,
        sourceCardId: link.sourceCardId,
        sourcePortId: "artifact-card-output",
        targetCardId: link.targetCardId,
        targetPortId: link.targetPortId,
        enabled: true,
        collectionMode: link.collectionMode,
        sourcePortLabel: "artifact",
        projectionLabel: null,
        conversionLabel: link.conversionCount
          ? `${link.conversionCount} conv`
          : null,
      });
    }
  } else {
    for (const origin of document.origins) {
      const targetPort = targetPortId(origin.to_port, origin.to_plug);
      if (!cardIds.has(origin.to_node)) continue;
      const remaining = new Set(
        cardArtifactRefs(origin.value).map((ref) => ref.artifact_id),
      );
      for (const viewer of viewers) {
        if (!cardIds.has(viewer.id)) continue;
        if (
          origin.source_card_ids != null &&
          !origin.source_card_ids.includes(viewer.id)
        ) {
          continue;
        }
        const value = viewer.artifact_ref ?? null;
        const refs = cardArtifactRefs(value);
        if (
          !value ||
          value.artifact_type !== origin.value.artifact_type ||
          value.schema_version !== origin.value.schema_version ||
          refs.length === 0 ||
          !refs.every((ref) => remaining.has(ref.artifact_id))
        ) {
          continue;
        }
        originPipes.push({
          id: `artifact-origin:${origin.id}:${viewer.id}`,
          sourceCardId: viewer.id,
          sourcePortId: "artifact-card-output",
          targetCardId: origin.to_node,
          targetPortId: targetPort,
          enabled: true,
          collectionMode: origin.collection_mode,
          sourcePortLabel: "artifact",
          projectionLabel: null,
          conversionLabel: origin.conversion_path.length
            ? `${origin.conversion_path.length} conv`
            : null,
        });
        if (origin.source_card_ids == null) {
          for (const ref of refs) remaining.delete(ref.artifact_id);
          if (remaining.size === 0) break;
        }
      }
    }
  }

  const pipes: CellPipeModel[] = [
    ...document.edges.map((edge): CellPipeModel => {
      const meta = options?.pipeMetadataById?.get(edge.id);
      return {
        id: edge.id,
        sourceCardId: edge.from_node,
        sourcePortId: edge.from_port,
        targetCardId: edge.to_node,
        targetPortId: targetPortId(edge.to_port, edge.to_plug),
        enabled: edge.enabled,
        collectionMode: edge.collection_mode,
        sourcePortLabel: meta?.sourcePortLabel ?? edge.from_port,
        projectionLabel:
          meta?.projectionLabel !== undefined
            ? meta.projectionLabel
            : edge.projection?.path.length
              ? edge.projection.path.join(".")
              : null,
        conversionLabel:
          meta?.conversionLabel !== undefined
            ? meta.conversionLabel
            : edge.conversion_path.length
              ? `${edge.conversion_path.length} conv`
              : null,
        ...(meta?.incompatible ? { incompatible: true } : {}),
      };
    }),
    ...originPipes,
    ...presentationLinks.flatMap((link): CellPipeModel[] => {
      if (
        !cardIds.has(link.source_node_id) ||
        !cardIds.has(link.target_viewer_id)
      ) {
        return [];
      }
      const meta = options?.pipeMetadataById?.get(link.id);
      return [
        {
          id: link.id,
          sourceCardId: link.source_node_id,
          sourcePortId: link.source_port_name,
          targetCardId: link.target_viewer_id,
          targetPortId: "artifact-viewer-input",
          enabled: true,
          sourcePortLabel: meta?.sourcePortLabel ?? link.source_port_name,
          projectionLabel:
            meta?.projectionLabel !== undefined
              ? meta.projectionLabel
              : link.projection?.path.length
                ? link.projection.path.join(".")
                : null,
          conversionLabel: null,
        },
      ];
    }),
  ];

  return {
    graph: {
      cards,
      pipes,
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
          width: commit.widthCells * CELL_SIZE,
          height: commit.heightCells * CELL_SIZE,
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
