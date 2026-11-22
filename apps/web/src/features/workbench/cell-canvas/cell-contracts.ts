import type {
  Credential,
  CredentialVerification,
  NodeCredentialStatus,
} from "@/lib/api";
import type { CredentialProvider } from "@/features/credentials/CredentialForm";
import type { NodeCredentialSelection } from "../authoring/node-secrets";
import type {
  ConnectedInputPortMap,
  SchemaField,
} from "../config-ui/config-schema";
import type { WorkflowNodeSecretState } from "../authoring/node-secrets";

import type { StageViewport } from "./cell-glass-stage";
import type { CellCoord, PortShape, WorldPoint } from "./cell-model";
import type { WorldBounds } from "./use-cell-viewport";

/**
 * Frozen cross-lane contracts for the cell-canvas engine.
 * Pure types only so engine core, real cards/overlays, and workbench adapters
 * can be built and tested in parallel with guaranteed compile-time alignment.
 */

export interface CellDockedJoin {
  pipeId: string;
  sourceCardId: string;
  sourcePortId: string;
  targetCardId: string;
  targetPortId: string;
  /** Vertical grid line shared by sourceCard right edge and targetCard left edge. */
  seamCol: number;
  /** World row shared by both ports. */
  row: number;
  /** World centre of the docked seam: `{ x: seamCol * CELL_SIZE, y: (row + 0.5) * CELL_SIZE }`. */
  seamPoint: WorldPoint;
  color: string;
  sequence: boolean;
  enabled: boolean;
  projectionLabel?: string | null;
  conversionLabel?: string | null;
}

export interface CellPipeAttachment {
  pipeId: string;
  /** World centre of the 3x1-cell EdgeSelector pill above the glass. */
  anchor: WorldPoint;
  segmentOrientation: "horizontal" | "vertical";
  widthCells: number;
  heightCells: number;
  label: string;
  conversionLabel?: string | null;
  color: string;
  enabled: boolean;
  isDocked: boolean;
}

export interface CellSelectionSnapshot {
  cardIds: ReadonlySet<string>;
  pipeIds: ReadonlySet<string>;
}

export interface CellMarqueeRect {
  start: WorldPoint;
  current: WorldPoint;
}

export interface CellRemotePeerState {
  actorId: string;
  sessionId?: string;
  displayName: string;
  color: string;
  cursor: WorldPoint | null;
  activity?: "idle" | "moving_nodes" | "editing_node" | "connecting";
  selectedCardIds: readonly string[];
  /** Live snapped cell positions for cards currently dragged by this peer. */
  draggingCards: Readonly<Record<string, CellCoord>>;
}

export interface CellRemotePeerBadge {
  actorId: string;
  displayName: string;
  color: string;
}

export interface CellCardInteractionState {
  selected: boolean;
  hovered: boolean;
  dragging: boolean;
  resizing: boolean;
  /** Referentially stable when unchanged (empty frozen array when none). */
  remoteSelectedBy: readonly CellRemotePeerBadge[];
  remoteDragCell: CellCoord | null;
  remoteDragColor: string | null;
}

export interface CellPipeInteractionState {
  selected: boolean;
  hovered: boolean;
}

/**
 * Per-card / per-pipe external store compatible with `React.useSyncExternalStore`.
 * Changing selection, hover, or remote peer state notifies only affected ids.
 */
export interface CellInteractionStore {
  subscribeCard(cardId: string, listener: () => void): () => void;
  getCardState(cardId: string): CellCardInteractionState;

  subscribePipe(pipeId: string, listener: () => void): () => void;
  getPipeState(pipeId: string): CellPipeInteractionState;

  subscribeSelection(listener: () => void): () => void;
  getSelection(): CellSelectionSnapshot;

  subscribeMarquee(listener: () => void): () => void;
  getMarquee(): CellMarqueeRect | null;

  subscribeRemotePeers(listener: () => void): () => void;
  getRemotePeers(): readonly CellRemotePeerState[];

  subscribeActivePort(listener: () => void): () => void;
  getActivePortKey(): string | null;

  setSelection(next: {
    cardIds?: Iterable<string>;
    pipeIds?: Iterable<string>;
  }): void;
  toggleCardSelection(cardId: string): void;
  clearSelection(): void;
  setHoveredCard(cardId: string | null): void;
  setHoveredPipe(pipeId: string | null): void;
  setDraggingCards(cardIds: Iterable<string>): void;
  setResizingCard(cardId: string | null): void;
  setMarquee(rect: CellMarqueeRect | null): void;
  setRemotePeers(peers: readonly CellRemotePeerState[]): void;
  setActivePortKey(key: string | null): void;
}

export interface CellViewportApi {
  viewport: StageViewport;
  screenToWorld(clientX: number, clientY: number): WorldPoint;
  worldToScreen(world: WorldPoint): WorldPoint;
  zoomAtCenter(nextZoom: number): void;
  zoomBy(factor: number): void;
  fitRect(bounds: WorldBounds, paddingRatio?: number, maxZoom?: number): void;
  viewAt(
    worldX: number,
    worldY: number,
    zoom: number,
    screenX?: number,
    screenY?: number,
  ): StageViewport;
}

export type CellResizeEdge = "e" | "s" | "se";

export interface CellResizeCommit {
  cardId: string;
  widthCells: number;
  heightCells: number;
}

export interface CellConnectDropEmptyEvent {
  sourceCardId: string;
  sourcePortId: string;
  direction: "downstream" | "upstream";
  worldPoint: WorldPoint;
  targetCell: CellCoord;
  clientPoint: WorldPoint;
}

// --- Real Grafy Card Surface Data (zero DOM measurement contracts) ---------

export type CellConfigFieldKind =
  | "text"
  | "select"
  | "toggle"
  | "number"
  | "multiline"
  /** A field drawn from its config schema: `schemaField` says which control. */
  | "schema"
  /** A named group's header row: `section` says whether it is open. */
  | "group"
  /** The row that folds a card's untouched advanced fields away. */
  | "advanced"
  /** One quiet row naming config issues no shown field can display. */
  | "issues";

export interface CellConfigSectionRow {
  /** The key `onToggleConfigSection` receives, e.g. `group:Style`. */
  key: string;
  open: boolean;
  /** Fields behind the row. */
  count: number;
  /** Validation issues in those fields. */
  issueCount: number;
}

export interface CellConfigFieldSpec {
  id: string;
  label: string;
  kind: CellConfigFieldKind;
  /**
   * The value a simple control shows. A `schema` field carries the stored
   * value in `rawValue` too, whatever its shape; this stays its primitive face.
   */
  value: string | number | boolean;
  options?: readonly { value: string; label: string }[];
  placeholder?: string;
  /** Width span in half-card shelf units: 1 = half shelf, 2 = full shelf (default 2). */
  span?: 1 | 2;
  /** Dense 25px rows occupied (default 1 for single-line, 3 for multiline). */
  denseRows?: number;
  /** Quiet line under the control. */
  description?: string;
  /** The schema field a `schema` entry draws, with everything it declares. */
  schemaField?: SchemaField;
  /** The stored value of a `schema` field: an object, a list, or a primitive. */
  rawValue?: unknown;
  /** What validation says is wrong with this field, if anything. */
  issue?: string;
  /** A `group` or `advanced` row's disclosure. */
  section?: CellConfigSectionRow;
}

/** One write-only key a node declares, with what the API says about it. */
export interface CellSecretInputSpec {
  name: string;
  title: string;
  description?: string;
  state: WorkflowNodeSecretState;
  message?: string;
  /**
   * Whether a key may be written now: the node is saved and the settings the
   * key is bound to still match the saved ones.
   */
  ready: boolean;
  /**
   * Changes when the key's binding does (graph, room epoch, or a config field
   * it depends on), so an editor holding a half-typed key starts over.
   */
  revision: string;
  vault?: {
    workspaceId: string;
    canManageShared: boolean;
    canEditShared: boolean;
    canSelectPersonal: boolean;
    credentials: readonly Credential[];
    status: NodeCredentialStatus;
    provider: CredentialProvider;
    select: (selection: NodeCredentialSelection) => Promise<void>;
    verify: () => Promise<CredentialVerification>;
    refresh: () => Promise<void>;
  };
}

export interface CellInstancePlugItem {
  plugId: string;
  label: string;
  connected: boolean;
  connectionMeta?: string | null;
}

export interface CellInstancePlugGroup {
  portName: string;
  title: string;
  artifactTypeId: string;
  shape: PortShape;
  /** First cell rowOffset where this group's plugs begin. */
  startRowOffset: number;
  plugs: readonly CellInstancePlugItem[];
  canAdd?: boolean;
}

export interface CellExecutionAppendixSpec {
  title: string;
  kindBadge: string;
  /** Exact cell rows allocated to the appendix body (min 2, default 3). */
  heightCells: number;
  collapsed?: boolean;
  summaryText: string;
  previewLines?: readonly string[];
  itemCount?: number;
}

export interface OperatorCardSurfaceData {
  kind: "operator";
  statusLabel?: string;
  runDisabled?: boolean;
  configFields?: readonly CellConfigFieldSpec[];
  /**
   * Open or closed, by section key, wherever the person chose: a group, the
   * advanced fields, or an object field nested at any depth. A section not
   * listed keeps its default.
   */
  configSections?: Readonly<Record<string, boolean>>;
  /** What each input port receives, for fields nested under a `visibleWhen`. */
  connectedInputPorts?: ConnectedInputPortMap;
  /** Write-only keys, behind the header's key button rather than in the band. */
  secretInputs?: readonly CellSecretInputSpec[];
  instancePlugGroups?: readonly CellInstancePlugGroup[];
  appendix?: CellExecutionAppendixSpec | null;
}

export type ArtifactPreviewKind =
  "image" | "table" | "markdown" | "file" | "map";

/** One artifact of a sequence card, as its spread shows it. */
export interface ArtifactStackItem {
  artifactId: string;
  imageUrl?: string | null;
  label: string;
}

export interface ArtifactCardSurfaceData {
  kind: "artifact";
  previewKind: ArtifactPreviewKind;
  artifactTypeId: string;
  typeLabel: string;
  filename?: string;
  dimensionsLabel?: string;
  imageUrl?: string | null;
  /**
   * The next items' pictures in a sequence, after `imageUrl`: at most two,
   * shown as the card backs fanned behind the plate.
   */
  stackImageUrls?: readonly string[];
  /** How many artifacts the card holds, when it holds a sequence. */
  itemCount?: number;
  /**
   * Every item of a sequence, in order, for its spread: its
   * picture when the browser can paint it, and its name.
   */
  stackItems?: readonly ArtifactStackItem[];
  previewText?: string | null;
  tableHeaders?: readonly string[];
  tableRows?: readonly (readonly string[])[];
  byteSizeLabel?: string;
}

export interface CollectionCardMemberSpec {
  id: string;
  label: string;
  artifactTypeId: string;
  typeLabel: string;
  meta?: string;
}

export interface CollectionCardSurfaceData {
  kind: "collection";
  artifactTypeId: string;
  typeLabel: string;
  members: readonly CollectionCardMemberSpec[];
  /** When true, allocates 1 spare plug row at the bottom. */
  showSparePlug?: boolean;
  /** Unconnected plug id backing the spare drop slot. */
  sparePlugId?: string | null;
}

export type AnnotationColorToken =
  "slate" | "blue" | "emerald" | "amber" | "violet" | "rose";

export interface AnnotationCardSurfaceData {
  kind: "annotation";
  variant: "frame" | "note";
  color: AnnotationColorToken;
  bodyText: string;
  /** Background annotations sit above the frosted glass sheet and below cards. */
  layer: "under-cards";
}

export interface AgentToolRowSpec {
  id: string;
  toolName: string;
  status: "pending" | "running" | "done" | "error";
  summary: string;
}

export interface AgentCardSurfaceData {
  kind: "agent";
  modelLabel: string;
  agentStatus: "idle" | "thinking" | "streaming" | "error";
  linkedToolCount: number;
  recentToolRows?: readonly AgentToolRowSpec[];
  lastMessageSnippet?: string;
}

export type CellCardSurfaceData =
  | OperatorCardSurfaceData
  | ArtifactCardSurfaceData
  | CollectionCardSurfaceData
  | AnnotationCardSurfaceData
  | AgentCardSurfaceData;
