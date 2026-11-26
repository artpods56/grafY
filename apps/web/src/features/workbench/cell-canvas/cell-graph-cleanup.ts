/**
 * The canvas cleanup: straighten a graph into canonical cards, read left to right.
 *
 * A person drops cards where they think, then the graph rots: a markdown card
 * stretched to 1200px beside an operator nobody can scan, two lanes crossing
 * because a wire left the lower port and entered the upper one, a service
 * provider holding a column open for the one card it ever served. This module
 * decides where every card should sit and how big it should be, and returns the
 * difference as authoring commands plus the new presentation state. It never
 * mutates what it was handed, and every value it overwrites it first records in
 * a snapshot that `buildCleanupUndoPlan` turns back into the original graph.
 *
 * Six phases, in order: choose the cards in scope, size them canonically
 * *before* the scene is built so ports land on their post-resize rows, read the
 * flow that wires them, rank and lane that flow, turn ranks into cell
 * coordinates, and emit the minimal diff.
 */
import type { NodeRegistry, NodeSpec, SavedGraphOrigin } from "@/lib/api";

import {
  presentationFromArtifactViewers,
  type ArtifactViewerCanvasState,
  type ArtifactViewerEdge,
  type ArtifactViewerNode,
} from "../artifacts/artifact-viewer";
import { cardArtifactRefs } from "../artifacts/artifact-card";
import {
  clampAnnotationLayout,
  type AnnotationLayout,
  type AnnotationNode,
} from "../authoring/annotations";
import {
  COLLECTION_OPERATOR_ID,
  isCollectionSpec,
} from "../authoring/collection-spec";
import type {
  AuthoredGraphAgent,
  AuthoredGraphDocument,
  AuthoredGraphNode,
  GraphCommand,
} from "../authoring/graph-document";
import {
  resolveGraphSemantics,
  type ResolvedGraphSemantics,
} from "../authoring/graph-semantics";
import {
  serializeNodeLayout,
  type SavedNodeLayout,
  type WorkflowNodeLayout,
} from "../authoring/node-layout";
import { isServiceProviderNode } from "../authoring/types";
import type {
  ArtifactCardSurfaceData,
  ArtifactPreviewKind,
} from "./cell-contracts";

import { PLUG_SEPARATOR, targetPortId } from "./cell-adapter-shared";
import {
  cellGraphFromAuthoredDocument,
  graphCommandsFromCellMovesForDocument,
  type CellNodeRunState,
  type CellOriginLink,
  type CellViewerImages,
} from "./cell-document-adapter";
import {
  CELL_SIZE,
  FIRST_PORT_ROW,
  cellToWorldOrigin,
  findPipeEndPort,
  type CellCardKind,
  type CellCardModel,
} from "./cell-model";

/** What the cleanup knows about one card's live value, keyed by its producer. */
type ViewerOutputValue = {
  artifactTypeId: string;
  schemaVersion?: number;
  shape: "one" | "many";
};

/** A point the caller resolved for one card's picture, when it has one. */
type NaturalSize = { width: number; height: number };

export type CellCleanupCardSizePreset = "compact" | "default" | "roomy";

export interface CellCleanupParams {
  /** Resize cards to canonical type-based dimensions before positioning. */
  readonly resizeCards: boolean;
  /** Canonical card size scale when `resizeCards` is enabled. */
  readonly cardSize: CellCleanupCardSizePreset;
  /** Horizontal gutter in grid cells between pipeline columns (1 cell = 25px). */
  readonly columnGapCells: number;
  /** Vertical gap in grid cells between sibling branches/lanes. */
  readonly laneGapCells: number;
  /** Vertical gap in grid cells between cards stacked in one column slot. */
  readonly stackGapCells: number;
  /** Vertical gap in grid cells between separate experiments and parked cards. */
  readonly experimentGapCells: number;
  /** Tuck single-consumer service providers under/beside their consumer. */
  readonly tuckProviders: boolean;
  /** Nudge downstream operators to align straight port-to-port wires. */
  readonly alignPorts: boolean;
  /** Keep unpaired same-type cards placed beside a wired card as pairs. */
  readonly keepCompanions: boolean;
  /** Clear manual wire route offsets on in-scope edges. */
  readonly clearRouteOffsets: boolean;
}

export interface CellCleanupOptions {
  /**
   * When 2 or more foreground cards (nodes, agents, or artifact viewers) are in
   * this set, only those cards are resized and repositioned, anchored at their
   * current top-left cell bounding box. Otherwise the entire open graph is
   * cleaned up starting at safe origin (col: 4, row: 5 -> x: 100, y: 125) so
   * the top-left GraphSwitcher chrome never overlaps cards.
   */
  readonly selectedCardIds?: ReadonlySet<string>;
  /** Resize cards to canonical type-based dimensions before positioning (default: true). */
  readonly resizeCards?: boolean;
  /** Tunable layout & sizing parameters; omitted fields fall back to defaults. */
  readonly params?: Partial<CellCleanupParams>;
  readonly nodeRunState?: Readonly<Record<string, CellNodeRunState>>;
  readonly collapsedAppendices?: ReadonlySet<string>;
  readonly configSections?: Readonly<
    Record<string, Readonly<Record<string, boolean>>>
  >;
  readonly viewerImages?: ReadonlyMap<string, CellViewerImages>;
  readonly viewerOutputValues?: ReadonlyMap<string, ViewerOutputValue>;
}

/** Every pre-cleanup value the plan overwrites, keyed by the card that held it. */
export interface CellCleanupUndoSnapshot {
  readonly nodeSnapshots: ReadonlyMap<
    string,
    {
      readonly position: { readonly x: number; readonly y: number };
      readonly layout: SavedNodeLayout | null;
    }
  >;
  readonly edgeRouteOffsets: ReadonlyMap<
    string,
    { readonly x: number; readonly y: number } | null
  >;
  readonly agentSnapshots: ReadonlyMap<
    string,
    {
      readonly position: { readonly x: number; readonly y: number };
      readonly width: number;
      readonly height: number;
    }
  >;
  readonly viewerSnapshots: ReadonlyMap<
    string,
    {
      readonly position: { readonly x: number; readonly y: number };
      readonly layout: WorkflowNodeLayout | null;
    }
  >;
  readonly viewerEdgeRouteOffsets: ReadonlyMap<
    string,
    { readonly x: number; readonly y: number } | undefined
  >;
  readonly annotationSnapshots: ReadonlyMap<
    string,
    {
      readonly position: { readonly x: number; readonly y: number };
      readonly layout: AnnotationLayout;
    }
  >;
}

export interface CellCleanupPlan {
  /** Authoring commands to apply in one batch (move_nodes, update_node_layout, update_edge, configure_agent). */
  readonly graphCommands: readonly GraphCommand[];
  /** Updated ArtifactViewerCanvasState (viewers, viewer edges with cleared routeOffsets, annotations). */
  readonly nextArtifactViewers: ArtifactViewerCanvasState;
  /** Number of foreground cards touched by the cleanup. */
  readonly affectedCardCount: number;
  /** Number of wired experiments (connected components of >= 2 cards) arranged. */
  readonly experimentCount: number;
  /** Bounding box in world pixels of all cards moved/sized by this cleanup. */
  readonly bounds: {
    readonly x: number;
    readonly y: number;
    readonly width: number;
    readonly height: number;
  } | null;
  /** Snapshot that `buildCleanupUndoPlan` uses to restore pre-cleanup positions and layouts. */
  readonly undoSnapshot: CellCleanupUndoSnapshot;
  /** True when at least one command or viewer/annotation change was produced. */
  readonly changed: boolean;
}

// --- The gaps ---------------------------------------------------------------

/**
 * 100px of column gutter: the two port cells the router needs on the way out of
 * a card plus two routing tracks, so a pipe leaves into ground no other card
 * occupies and never has to dive below layer 0.
 */
const COL_GUTTER_CELLS = 4;
/**
 * 50px between two cards the author already paired by eye. Flush and the
 * stacking pill offers to merge them into one sequence — a comparison is two
 * cards, not a pile — and a mile wide and they stop reading as one thing.
 */
const COMPANION_GAP_CELLS = 2;
/** 50px between cards stacked in one cell: a scan and the reader tucked under it. */
const STACK_GAP_CELLS = 2;
/** 50px between sibling lanes: clears a card's floating title and its merge seam. */
const LANE_GAP_CELLS = 2;
/** 125px between unrelated experiments — enough air to read as a new paragraph. */
const EXPERIMENT_GAP_CELLS = 5;
const PARKED_GAP_X_CELLS = 3;
const PARKED_GAP_Y_CELLS = 3;
/** 1800px of parked cards, then the strip wraps rather than run off the world. */
const PARKED_MAX_ROW_WIDTH_CELLS = 72;

/** The unscoped cleanup's origin: clear of the GraphSwitcher pill at top-left. */
const SAFE_ORIGIN_COL = 4;
const SAFE_ORIGIN_ROW = 5;

/** An appendix the author opened stays, but never taller than six cells. */
const MAX_CANONICAL_APPENDIX_PX = 6 * CELL_SIZE;
const AGENT_CANONICAL_WIDTH_PX = 14 * CELL_SIZE;
const AGENT_CANONICAL_HEIGHT_PX = 12 * CELL_SIZE;
const AGENT_TALL_HEIGHT_PX = 16 * CELL_SIZE;
/** Past two linked tools and cards an agent's roster needs a taller box. */
const AGENT_TALL_LINK_COUNT = 2;

const TIFF_WIDTH_PX = 16 * CELL_SIZE;
/** A picture with no pixels yet falls back to a 4:3-ish plate, 400 × 350. */
const TIFF_FALLBACK_HEIGHT_PX = 14 * CELL_SIZE;
const TABLE_WIDTH_PX = 20 * CELL_SIZE;
const TABLE_HEIGHT_PX = 12 * CELL_SIZE;
const MAP_WIDTH_PX = 18 * CELL_SIZE;
const MAP_HEIGHT_PX = 14 * CELL_SIZE;
const PROSE_WIDTH_PX = 16 * CELL_SIZE;
const PROSE_HEIGHT_PX = 12 * CELL_SIZE;
const SCALAR_WIDTH_PX = 10 * CELL_SIZE;
const SCALAR_HEIGHT_PX = 5 * CELL_SIZE;
const FILE_WIDTH_PX = 8 * CELL_SIZE;
const FILE_HEIGHT_PX = 4 * CELL_SIZE;
const SCALAR_INTEGER_TYPE = "scalar.integer";

export const DEFAULT_CELL_CLEANUP_PARAMS: CellCleanupParams = {
  resizeCards: true,
  cardSize: "default",
  columnGapCells: COL_GUTTER_CELLS,
  laneGapCells: LANE_GAP_CELLS,
  stackGapCells: STACK_GAP_CELLS,
  experimentGapCells: EXPERIMENT_GAP_CELLS,
  tuckProviders: true,
  alignPorts: true,
  keepCompanions: true,
  clearRouteOffsets: true,
};

interface CardSizeProfile {
  readonly maxAppendixPx: number;
  readonly agentWidthPx: number;
  readonly agentHeightPx: number;
  readonly agentTallHeightPx: number;
  readonly tiffWidthPx: number;
  readonly tiffFallbackHeightPx: number;
  readonly tableWidthPx: number;
  readonly tableHeightPx: number;
  readonly mapWidthPx: number;
  readonly mapHeightPx: number;
  readonly proseWidthPx: number;
  readonly proseHeightPx: number;
  readonly scalarWidthPx: number;
  readonly scalarHeightPx: number;
  readonly fileWidthPx: number;
  readonly fileHeightPx: number;
}

const CARD_SIZE_PROFILES: Record<CellCleanupCardSizePreset, CardSizeProfile> = {
  compact: {
    maxAppendixPx: 4 * CELL_SIZE,
    agentWidthPx: 12 * CELL_SIZE,
    agentHeightPx: 10 * CELL_SIZE,
    agentTallHeightPx: 13 * CELL_SIZE,
    tiffWidthPx: 12 * CELL_SIZE,
    tiffFallbackHeightPx: 10 * CELL_SIZE,
    tableWidthPx: 16 * CELL_SIZE,
    tableHeightPx: 10 * CELL_SIZE,
    mapWidthPx: 14 * CELL_SIZE,
    mapHeightPx: 11 * CELL_SIZE,
    proseWidthPx: 12 * CELL_SIZE,
    proseHeightPx: 9 * CELL_SIZE,
    scalarWidthPx: 8 * CELL_SIZE,
    scalarHeightPx: 4 * CELL_SIZE,
    fileWidthPx: 8 * CELL_SIZE,
    fileHeightPx: 4 * CELL_SIZE,
  },
  default: {
    maxAppendixPx: MAX_CANONICAL_APPENDIX_PX,
    agentWidthPx: AGENT_CANONICAL_WIDTH_PX,
    agentHeightPx: AGENT_CANONICAL_HEIGHT_PX,
    agentTallHeightPx: AGENT_TALL_HEIGHT_PX,
    tiffWidthPx: TIFF_WIDTH_PX,
    tiffFallbackHeightPx: TIFF_FALLBACK_HEIGHT_PX,
    tableWidthPx: TABLE_WIDTH_PX,
    tableHeightPx: TABLE_HEIGHT_PX,
    mapWidthPx: MAP_WIDTH_PX,
    mapHeightPx: MAP_HEIGHT_PX,
    proseWidthPx: PROSE_WIDTH_PX,
    proseHeightPx: PROSE_HEIGHT_PX,
    scalarWidthPx: SCALAR_WIDTH_PX,
    scalarHeightPx: SCALAR_HEIGHT_PX,
    fileWidthPx: FILE_WIDTH_PX,
    fileHeightPx: FILE_HEIGHT_PX,
  },
  roomy: {
    maxAppendixPx: 8 * CELL_SIZE,
    agentWidthPx: 18 * CELL_SIZE,
    agentHeightPx: 14 * CELL_SIZE,
    agentTallHeightPx: 18 * CELL_SIZE,
    tiffWidthPx: 20 * CELL_SIZE,
    tiffFallbackHeightPx: 17 * CELL_SIZE,
    tableWidthPx: 24 * CELL_SIZE,
    tableHeightPx: 15 * CELL_SIZE,
    mapWidthPx: 22 * CELL_SIZE,
    mapHeightPx: 17 * CELL_SIZE,
    proseWidthPx: 20 * CELL_SIZE,
    proseHeightPx: 15 * CELL_SIZE,
    scalarWidthPx: 12 * CELL_SIZE,
    scalarHeightPx: 6 * CELL_SIZE,
    fileWidthPx: 10 * CELL_SIZE,
    fileHeightPx: 4 * CELL_SIZE,
  },
};

function clampInt(
  value: number | undefined,
  fallback: number,
  min: number,
  max: number,
): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return fallback;
  return Math.max(min, Math.min(max, Math.round(value)));
}

function resolveCleanupParams(options: CellCleanupOptions): CellCleanupParams {
  const input = options.params ?? {};
  const resizeCards =
    input.resizeCards ??
    options.resizeCards ??
    DEFAULT_CELL_CLEANUP_PARAMS.resizeCards;
  const cardSize: CellCleanupCardSizePreset =
    input.cardSize === "compact" ||
    input.cardSize === "default" ||
    input.cardSize === "roomy"
      ? input.cardSize
      : DEFAULT_CELL_CLEANUP_PARAMS.cardSize;
  return {
    resizeCards,
    cardSize,
    columnGapCells: clampInt(
      input.columnGapCells,
      DEFAULT_CELL_CLEANUP_PARAMS.columnGapCells,
      2,
      12,
    ),
    laneGapCells: clampInt(
      input.laneGapCells,
      DEFAULT_CELL_CLEANUP_PARAMS.laneGapCells,
      1,
      10,
    ),
    stackGapCells: clampInt(
      input.stackGapCells,
      DEFAULT_CELL_CLEANUP_PARAMS.stackGapCells,
      1,
      8,
    ),
    experimentGapCells: clampInt(
      input.experimentGapCells,
      DEFAULT_CELL_CLEANUP_PARAMS.experimentGapCells,
      2,
      16,
    ),
    tuckProviders:
      input.tuckProviders ?? DEFAULT_CELL_CLEANUP_PARAMS.tuckProviders,
    alignPorts: input.alignPorts ?? DEFAULT_CELL_CLEANUP_PARAMS.alignPorts,
    keepCompanions:
      input.keepCompanions ?? DEFAULT_CELL_CLEANUP_PARAMS.keepCompanions,
    clearRouteOffsets:
      input.clearRouteOffsets ?? DEFAULT_CELL_CLEANUP_PARAMS.clearRouteOffsets,
  };
}

/** A companion sits level with, and just right of, the card it compares to. */
const COMPANION_MAX_Y_DELTA_PX = 100;
const COMPANION_MIN_GAP_PX = -CELL_SIZE;
const COMPANION_MAX_GAP_PX = 150;
/** A note stays glued to the card it was pinned to within this reach. */
const NOTE_ATTACH_PX = 300;
/** A frame closes on its cards with two cells of air on every side. */
const FRAME_PADDING_CELLS = 2;

/** Past four cells a port nudge reads as a card that fell out of its row. */
const PORT_ALIGN_TOLERANCE = 4;

const POSITION_EPSILON = 0.01;

// --- The cards --------------------------------------------------------------

/** One foreground card: its post-resize footprint and the place it came from. */
interface CleanupCard {
  readonly id: string;
  readonly kind: CellCardKind;
  readonly widthCells: number;
  readonly heightCells: number;
  /** Where the card sat before the cleanup, in pixels, for human-order sorting. */
  readonly origX: number;
  readonly origY: number;
  readonly origWidthPx: number;
  readonly origHeightPx: number;
  /** The artifact type an artifact card presents; `""` for every other kind. */
  readonly artifactTypeId: string;
  readonly previewKind: ArtifactPreviewKind | null;
  /** A provider is placed for its consumer, never for its own rank. */
  readonly serviceProvider: boolean;
}

/** A direction on the flow graph, with the port rows its ends sit on. */
interface FlowEdge {
  readonly source: string;
  readonly target: string;
  readonly sourcePortId: string;
  readonly targetPortId: string;
  readonly sourceRowOffset: number;
  readonly targetRowOffset: number;
  readonly companion: boolean;
}

/** One column of a ranked experiment: `rank -> cards stacked in that cell`. */
interface Lane {
  readonly index: number;
  readonly slots: Map<number, string[]>;
}

interface Placement {
  col: number;
  row: number;
}

interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** A provider riding along with the one card it serves. */
interface Satellite {
  readonly providerId: string;
  readonly consumerId: string;
  readonly targetRowOffset: number;
  readonly sourceRowOffset: number;
}

/** The scene root's own record of one card, before the cleanup's vocabulary. */
type SceneCard = CellCardModel;

type CleanupScene = ReturnType<typeof cellGraphFromAuthoredDocument>;

function outputRowOffset(card: SceneCard | undefined, portId: string): number {
  if (!card) return FIRST_PORT_ROW;
  return (
    findPipeEndPort(card.ports, portId, "output")?.rowOffset ?? FIRST_PORT_ROW
  );
}

function inputRowOffset(card: SceneCard | undefined, portId: string): number {
  if (!card) return FIRST_PORT_ROW;
  return (
    findPipeEndPort(card.ports, portId, "input")?.rowOffset ?? FIRST_PORT_ROW
  );
}

function snapCell(px: number): number {
  const cells = Math.round(px / CELL_SIZE);
  return Object.is(cells, -0) ? 0 : cells;
}

/** Reading order: the row a person was looking at, then left to right, then id. */
function compareOrigPosition(a: CleanupCard, b: CleanupCard): number {
  if (a.origY !== b.origY) return a.origY - b.origY;
  if (a.origX !== b.origX) return a.origX - b.origX;
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

/** The band a person's eye calls one line: 100px of canvas. */
function compareReadingOrder(a: CleanupCard, b: CleanupCard): number {
  const row = Math.round(a.origY / 100) - Math.round(b.origY / 100);
  return row !== 0 ? row : compareOrigPosition(a, b);
}

// --- Phase 1: canonical sizing ---------------------------------------------

/**
 * The layout a node is worth after cleanup: the standard 300px card with a band
 * that fits its own ports, keeping only an appendix the author opened.
 *
 * The appendix is a choice; width and body height are what the drag handle left
 * behind. A collection sizes itself from its members, so it keeps no layout.
 */
function canonicalNodeLayout(
  node: AuthoredGraphNode,
  spec: NodeSpec | null | undefined,
  profile: CardSizeProfile,
): SavedNodeLayout | null {
  if (isCollectionSpec(spec) || node.operator_id === COLLECTION_OPERATOR_ID) {
    return null;
  }
  const appendixHeight = node.layout?.appendix_height;
  if (appendixHeight === null || appendixHeight === undefined) return null;
  if (appendixHeight <= 0) return null;
  return serializeNodeLayout({
    appendixHeight: Math.min(appendixHeight, profile.maxAppendixPx),
  });
}

/** An agent's box is its roster: wide enough to read, tall enough to list. */
function canonicalAgentBox(
  agent: AuthoredGraphAgent,
  profile: CardSizeProfile,
): {
  width: number;
  height: number;
} {
  const links = agent.tools.length + agent.context.length;
  return {
    width: profile.agentWidthPx,
    height:
      links > AGENT_TALL_LINK_COUNT
        ? profile.agentTallHeightPx
        : profile.agentHeightPx,
  };
}

/**
 * The size an artifact card is worth for the kind of thing it shows.
 *
 * A picture keeps its own aspect: the width is set and the height left unset so
 * the adapter fits the plate to the picture it paints. A table, a map and a
 * page of prose each get the shape they need to show a first screen of
 * themselves, and a file card is a chip, not a preview.
 */
function canonicalViewerLayout(
  previewKind: ArtifactPreviewKind | null,
  artifactTypeId: string,
  wiredTiff: boolean,
  natural: NaturalSize | null | undefined,
  profile: CardSizeProfile,
): WorkflowNodeLayout | null {
  const hasPicture = !!natural && natural.width > 0 && natural.height > 0;
  switch (previewKind) {
    case "tiff-text":
      return hasPicture
        ? { width: profile.tiffWidthPx }
        : {
            width: profile.tiffWidthPx,
            bodyHeight: profile.tiffFallbackHeightPx,
          };
    case "tiff":
      if (!wiredTiff) return null;
      return hasPicture
        ? { width: profile.tiffWidthPx }
        : {
            width: profile.tiffWidthPx,
            bodyHeight: profile.tiffFallbackHeightPx,
          };
    case "image":
      // No width either: the card opens at ten cells and auto-fits the picture.
      return null;
    case "table":
      return { width: profile.tableWidthPx, bodyHeight: profile.tableHeightPx };
    case "map":
      return { width: profile.mapWidthPx, bodyHeight: profile.mapHeightPx };
    case "markdown":
    case "html-page":
      return { width: profile.proseWidthPx, bodyHeight: profile.proseHeightPx };
    case "text":
      return artifactTypeId === SCALAR_INTEGER_TYPE
        ? { width: profile.scalarWidthPx, bodyHeight: profile.scalarHeightPx }
        : { width: profile.proseWidthPx, bodyHeight: profile.proseHeightPx };
    case "file":
      return { width: profile.fileWidthPx, bodyHeight: profile.fileHeightPx };
    case null:
      return null;
  }
}

// --- Phase 2: the flow ------------------------------------------------------

/**
 * The wires that decide reading order: workflow edges, origin pipes, the links
 * from a node's output into a following card, the field bindings between two
 * cards, and the tools and context an agent was given.
 *
 * Parallel wires collapse to one lane, keeping the topmost exit into the topmost
 * entry, so a card that feeds another twice still reads as one step.
 */
function collectFlowEdges(
  document: AuthoredGraphDocument,
  viewerBindings: readonly { sourceViewerId: string; targetViewerId: string }[],
  sceneCards: ReadonlyMap<string, SceneCard>,
  pipes: readonly {
    id: string;
    sourceCardId: string;
    sourcePortId: string;
    targetCardId: string;
    targetPortId: string;
  }[],
  inScope: (id: string) => boolean,
): FlowEdge[] {
  const byPair = new Map<string, FlowEdge>();
  const add = (edge: FlowEdge) => {
    if (edge.source === edge.target) return;
    if (!inScope(edge.source) || !inScope(edge.target)) return;
    const key = `${edge.source}\u0000${edge.target}`;
    const held = byPair.get(key);
    if (
      held &&
      held.sourceRowOffset * 1000 + held.targetRowOffset <=
        edge.sourceRowOffset * 1000 + edge.targetRowOffset
    ) {
      return;
    }
    byPair.set(key, edge);
  };

  for (const pipe of pipes) {
    add({
      source: pipe.sourceCardId,
      target: pipe.targetCardId,
      sourcePortId: pipe.sourcePortId,
      targetPortId: pipe.targetPortId,
      sourceRowOffset: outputRowOffset(
        sceneCards.get(pipe.sourceCardId),
        pipe.sourcePortId,
      ),
      targetRowOffset: inputRowOffset(
        sceneCards.get(pipe.targetCardId),
        pipe.targetPortId,
      ),
      companion: false,
    });
  }
  for (const binding of viewerBindings) {
    add({
      source: binding.sourceViewerId,
      target: binding.targetViewerId,
      sourcePortId: "",
      targetPortId: "",
      sourceRowOffset: FIRST_PORT_ROW,
      targetRowOffset: FIRST_PORT_ROW,
      companion: false,
    });
  }
  for (const agent of document.agents) {
    for (const tool of agent.tools) {
      add({
        source: tool.node_id,
        target: agent.id,
        sourcePortId: "",
        targetPortId: "",
        sourceRowOffset: FIRST_PORT_ROW,
        targetRowOffset: FIRST_PORT_ROW,
        companion: false,
      });
    }
    for (const context of agent.context) {
      const source = context.node_id ?? context.card_id;
      if (!source) continue;
      add({
        source,
        target: agent.id,
        sourcePortId: "",
        targetPortId: "",
        sourceRowOffset: FIRST_PORT_ROW,
        targetRowOffset: FIRST_PORT_ROW,
        companion: false,
      });
    }
  }
  return [...byPair.values()];
}

/**
 * A card the author already set beside a wired card, showing the same thing: the
 * comparison half of a pair. Hanging it off its partner instead of parking it
 * with the strays keeps a comparison one decision instead of two layouts, and
 * gives column widths and overlap prevention a partner to account for.
 */
function findCompanionOwner(
  stray: CleanupCard,
  candidates: readonly CleanupCard[],
  degreeOf: (id: string) => { in: number; out: number },
): CleanupCard | null {
  if (!stray.artifactTypeId || stray.artifactTypeId === "artifact") return null;
  let best: CleanupCard | null = null;
  let bestGap = Number.POSITIVE_INFINITY;
  for (const other of candidates) {
    if (other.id === stray.id) continue;
    if (other.kind !== "artifact") continue;
    if (other.artifactTypeId !== stray.artifactTypeId) continue;
    const otherDegree = degreeOf(other.id);
    if (otherDegree.in + otherDegree.out === 0) continue;
    if (Math.abs(stray.origY - other.origY) > COMPANION_MAX_Y_DELTA_PX)
      continue;
    const gapX = stray.origX - (other.origX + other.origWidthPx);
    if (gapX < COMPANION_MIN_GAP_PX || gapX > COMPANION_MAX_GAP_PX) continue;
    if (gapX < bestGap) {
      best = other;
      bestGap = gapX;
    }
  }
  return best;
}

/** Weakly connected components of the flow graph, each a candidate experiment. */
function connectedComponents(
  ids: readonly string[],
  edges: readonly FlowEdge[],
): string[][] {
  const adjacency = new Map<string, string[]>();
  for (const id of ids) adjacency.set(id, []);
  for (const edge of edges) {
    adjacency.get(edge.source)?.push(edge.target);
    adjacency.get(edge.target)?.push(edge.source);
  }
  const seen = new Set<string>();
  const components: string[][] = [];
  for (const id of ids) {
    if (seen.has(id)) continue;
    seen.add(id);
    const component = [id];
    for (let cursor = 0; cursor < component.length; cursor += 1) {
      for (const next of adjacency.get(component[cursor] as string) ?? []) {
        if (seen.has(next)) continue;
        seen.add(next);
        component.push(next);
      }
    }
    components.push(component);
  }
  return components;
}

/**
 * A provider that only ever served one card is that card's satellite: it rides
 * along in the consumer's lane instead of holding a column of the DAG open for
 * the whole graph.
 *
 * A provider that is the consumer's *only* input stays in the DAG, because there
 * `P -> C` is the pipeline's own first step and rank 0 is where a reader looks
 * for it.
 */
function detachSatellites(
  cards: ReadonlyMap<string, CleanupCard>,
  members: readonly string[],
  edges: readonly FlowEdge[],
) {
  const providers = members.filter((id) => cards.get(id)?.serviceProvider);
  const candidates: FlowEdge[] = [];
  for (const id of providers) {
    const outgoing = edges.filter((edge) => edge.source === id);
    const incoming = edges.filter((edge) => edge.target === id);
    if (incoming.length !== 0 || outgoing.length !== 1) continue;
    const edge = outgoing[0];
    if (edge) candidates.push(edge);
  }
  const candidateIds = new Set(candidates.map((edge) => edge.source));

  const satellitesByConsumer = new Map<string, Satellite[]>();
  const detached = new Set<string>();
  for (const edge of candidates) {
    // Providers serving the same card are not "another input": C still needs a
    // producer of its own kind to be worth holding a column.
    const otherInputs = edges.filter(
      (candidate) =>
        candidate.target === edge.target && !candidateIds.has(candidate.source),
    ).length;
    if (otherInputs === 0) continue;
    detached.add(edge.source);
    const list = satellitesByConsumer.get(edge.target) ?? [];
    list.push({
      providerId: edge.source,
      consumerId: edge.target,
      targetRowOffset: edge.targetRowOffset,
      sourceRowOffset: edge.sourceRowOffset,
    });
    satellitesByConsumer.set(edge.target, list);
  }
  const kept = edges.filter(
    (edge) => !detached.has(edge.source) && !detached.has(edge.target),
  );
  for (const list of satellitesByConsumer.values()) {
    list.sort((a, b) => a.targetRowOffset - b.targetRowOffset);
  }
  return {
    remaining: members.filter((id) => !detached.has(id)),
    kept,
    satellitesByConsumer,
  };
}

// --- Phase 3: ranks and lanes ----------------------------------------------

/**
 * Drop the wires that close a loop.
 *
 * A cycle is a person wiring a result back into its own producer. Ranking has to
 * break it somewhere, so it drops the wire that runs back into a card this pass
 * is already laying out — the one a reader follows last, which is why walking
 * from the roots first makes the dropped set the feedback, not the trunk.
 */
function breakCycles(
  members: readonly string[],
  edges: readonly FlowEdge[],
  cards: ReadonlyMap<string, CleanupCard>,
  inDegree: ReadonlyMap<string, number>,
): FlowEdge[] {
  const outgoing = new Map<string, FlowEdge[]>();
  for (const id of members) outgoing.set(id, []);
  for (const edge of edges) outgoing.get(edge.source)?.push(edge);
  const order = [...members].sort((a, b) => {
    const root = (inDegree.get(a) ?? 0) === 0 ? 0 : 1;
    const other = (inDegree.get(b) ?? 0) === 0 ? 0 : 1;
    if (root !== other) return root - other;
    return compareOrigPosition(
      cards.get(a) as CleanupCard,
      cards.get(b) as CleanupCard,
    );
  });
  const state = new Map<string, "unvisited" | "visiting" | "done">();
  const forward: FlowEdge[] = [];
  const visit = (id: string) => {
    state.set(id, "visiting");
    const children = [...(outgoing.get(id) ?? [])].sort((a, b) =>
      compareOrigPosition(
        cards.get(a.target) as CleanupCard,
        cards.get(b.target) as CleanupCard,
      ),
    );
    for (const edge of children) {
      const next = state.get(edge.target) ?? "unvisited";
      if (next === "visiting") continue;
      if (next === "unvisited") visit(edge.target);
      forward.push(edge);
    }
    state.set(id, "done");
  };
  for (const id of order) {
    if ((state.get(id) ?? "unvisited") === "unvisited") visit(id);
  }
  return forward;
}

function degrees(members: readonly string[], edges: readonly FlowEdge[]) {
  const inDegree = new Map<string, number>();
  const outDegree = new Map<string, number>();
  for (const id of members) {
    inDegree.set(id, 0);
    outDegree.set(id, 0);
  }
  for (const edge of edges) {
    outDegree.set(edge.source, (outDegree.get(edge.source) ?? 0) + 1);
    inDegree.set(edge.target, (inDegree.get(edge.target) ?? 0) + 1);
  }
  return { inDegree, outDegree };
}

/**
 * Longest-path column ranks, then the tightening that pulls a feed up beside
 * what it feeds.
 *
 * A secondary input that joins a card three columns in belongs next to it, not
 * at the head of the graph where nothing it feeds is in sight.
 */
function assignRanks(
  members: readonly string[],
  edges: readonly FlowEdge[],
  inDegree: ReadonlyMap<string, number>,
  outDegree: ReadonlyMap<string, number>,
  satelliteConsumers: ReadonlySet<string>,
): Map<string, number> {
  const outgoing = new Map<string, FlowEdge[]>();
  for (const id of members) outgoing.set(id, []);
  for (const edge of edges) outgoing.get(edge.source)?.push(edge);

  const rank = new Map<string, number>();
  const pending = new Map<string, number>();
  for (const id of members) pending.set(id, inDegree.get(id) ?? 0);
  const queue = members.filter((id) => (pending.get(id) ?? 0) === 0);
  for (const id of queue) rank.set(id, 0);
  for (let head = 0; head < queue.length; head += 1) {
    const id = queue[head] as string;
    for (const edge of outgoing.get(id) ?? []) {
      rank.set(
        edge.target,
        Math.max(rank.get(edge.target) ?? 0, (rank.get(id) ?? 0) + 1),
      );
      const left = (pending.get(edge.target) ?? 0) - 1;
      pending.set(edge.target, left);
      if (left === 0) queue.push(edge.target);
    }
  }
  for (const id of members) {
    if (!rank.has(id)) rank.set(id, 0);
  }

  for (const id of members) {
    const children = outgoing.get(id) ?? [];
    if ((inDegree.get(id) ?? 0) !== 0 || (outDegree.get(id) ?? 0) === 0)
      continue;
    let pull = Number.POSITIVE_INFINITY;
    for (const edge of children) {
      pull = Math.min(pull, (rank.get(edge.target) ?? 0) - 1);
    }
    if (Number.isFinite(pull)) rank.set(id, Math.max(0, pull));
  }

  // Satellites live one column to the left of their consumer, so a consumer
  // pinned at rank 0 would park its provider off the grid.
  if ([...satelliteConsumers].some((id) => (rank.get(id) ?? 0) === 0)) {
    for (const id of members) rank.set(id, (rank.get(id) ?? 0) + 1);
  }
  return rank;
}

/**
 * Children of one card, stacked in the order they should be read.
 *
 * Wires leaving different ports must not cross, so the card the top port feeds
 * stays above the card the bottom port feeds. Children of the *same* port keep
 * wherever the author had them, since those ports are interchangeable. A
 * companion stays inline with its partner as long as the two are level.
 */
function compareChildren(
  parent: CleanupCard,
  a: FlowEdge,
  b: FlowEdge,
  cards: ReadonlyMap<string, CleanupCard>,
): number {
  const childA = cards.get(a.target) as CleanupCard;
  const childB = cards.get(b.target) as CleanupCard;
  const levelA =
    Math.abs(childA.origY - parent.origY) <= COMPANION_MAX_Y_DELTA_PX;
  const levelB =
    Math.abs(childB.origY - parent.origY) <= COMPANION_MAX_Y_DELTA_PX;
  const rankA = a.companion ? (levelA ? 0 : 2) : 1;
  const rankB = b.companion ? (levelB ? 0 : 2) : 1;
  if (rankA !== rankB) return rankA - rankB;
  if (a.sourcePortId !== b.sourcePortId) {
    return a.sourceRowOffset - b.sourceRowOffset;
  }
  return compareOrigPosition(childA, childB);
}

/**
 * Roots that fill the plugs of one join card — the lanes into `Collect<T>`, a
 * schema builder's fields — keep the plug order they were wired in, because that
 * order *is* the order the card lists its members.
 */
function plugOrderBy(
  roots: readonly string[],
  edges: readonly FlowEdge[],
): Map<string, number> {
  const plugRow = new Map<string, { target: string; row: number }>();
  for (const id of roots) {
    const wires = edges.filter((edge) => edge.source === id);
    if (wires.length !== 1) continue;
    const wire = wires[0];
    if (!wire?.targetPortId.includes(PLUG_SEPARATOR)) continue;
    plugRow.set(id, { target: wire.target, row: wire.targetRowOffset });
  }
  const joins = new Map<string, string[]>();
  for (const [id, info] of plugRow) {
    const list = joins.get(info.target) ?? [];
    list.push(id);
    joins.set(info.target, list);
  }
  const order = new Map<string, number>();
  for (const list of joins.values()) {
    if (list.length < 2) continue;
    list
      .sort((a, b) => (plugRow.get(a)?.row ?? 0) - (plugRow.get(b)?.row ?? 0))
      .forEach((id, index) => order.set(id, index));
  }
  return order;
}

/**
 * Thread an experiment through horizontal swimlanes.
 *
 * A card's first child carries on along the lane it was reached on — that is the
 * trunk a reader follows — and every further child opens a lane under it, so two
 * branches never share a row and nothing downstream can collide with a leaf.
 */
function traceLanes(
  cards: ReadonlyMap<string, CleanupCard>,
  members: readonly string[],
  edges: readonly FlowEdge[],
  rank: ReadonlyMap<string, number>,
  satellitesByConsumer: ReadonlyMap<string, Satellite[]>,
  inDegree: ReadonlyMap<string, number>,
) {
  const lanes: Lane[] = [];
  const laneOf = new Map<string, number>();
  const createLane = (): Lane => {
    const lane: Lane = { index: lanes.length, slots: new Map() };
    lanes.push(lane);
    return lane;
  };
  const put = (lane: Lane, at: number, id: string) => {
    const slot = lane.slots.get(at) ?? [];
    if (!slot.includes(id)) slot.push(id);
    lane.slots.set(at, slot);
    laneOf.set(id, lane.index);
  };

  const outgoing = new Map<string, FlowEdge[]>();
  for (const id of members) outgoing.set(id, []);
  for (const edge of edges) outgoing.get(edge.source)?.push(edge);

  const visited = new Set<string>();
  const trace = (id: string, laneIndex: number) => {
    const lane = lanes[laneIndex] as Lane;
    const ownRank = rank.get(id) ?? 0;
    visited.add(id);
    put(lane, ownRank, id);
    for (const satellite of satellitesByConsumer.get(id) ?? []) {
      if (visited.has(satellite.providerId)) continue;
      // Tucked *after* whatever already holds that cell, so a provider that
      // reads the card above it sits underneath it in the same column.
      visited.add(satellite.providerId);
      put(lane, ownRank - 1, satellite.providerId);
    }
    const parent = cards.get(id) as CleanupCard;
    const children = (outgoing.get(id) ?? [])
      .filter((edge) => (rank.get(edge.target) ?? 0) > ownRank)
      .filter((edge) => !visited.has(edge.target))
      .sort((a, b) => compareChildren(parent, a, b, cards));
    children.forEach((edge, index) => {
      if (index === 0) {
        trace(edge.target, laneIndex);
        return;
      }
      trace(edge.target, createLane().index);
    });
  };

  const roots = members.filter((id) => (inDegree.get(id) ?? 0) === 0);
  const plugOrder = plugOrderBy(roots, edges);
  roots.sort((a, b) => {
    const orderA = plugOrder.get(a);
    const orderB = plugOrder.get(b);
    if (orderA !== undefined && orderB !== undefined && orderA !== orderB) {
      return orderA - orderB;
    }
    return compareOrigPosition(
      cards.get(a) as CleanupCard,
      cards.get(b) as CleanupCard,
    );
  });
  for (const id of roots) {
    if (visited.has(id)) continue;
    trace(id, createLane().index);
  }
  const leftovers = members
    .filter((id) => !visited.has(id))
    .sort((a, b) =>
      compareOrigPosition(
        cards.get(a) as CleanupCard,
        cards.get(b) as CleanupCard,
      ),
    );
  for (const id of leftovers) {
    if (visited.has(id)) continue;
    trace(id, createLane().index);
  }
  return { lanes, laneOf };
}

// --- Phase 4: coordinates ---------------------------------------------------

/** Column gutter, or 2 cells when the whole seam is a pair the author drew. */
function gutterAfterColumn(
  edges: readonly FlowEdge[],
  rank: ReadonlyMap<string, number>,
  column: number,
  columnGapCells: number,
): number {
  let crossing = 0;
  let companion = 0;
  for (const edge of edges) {
    if (rank.get(edge.source) !== column) continue;
    if (rank.get(edge.target) !== column + 1) continue;
    crossing += 1;
    if (edge.companion) companion += 1;
  }
  return crossing > 0 && companion === crossing
    ? COMPANION_GAP_CELLS
    : columnGapCells;
}

/**
 * The row a card takes so its incoming port lines up with the port feeding it,
 * or the lane's top when there is nothing to line up with.
 *
 * An artifact card's output is punched into its bottom-right corner, so chasing
 * one drags the whole trunk into stairs; operators only.
 */
function straightRowFor(
  id: string,
  laneIndex: number,
  incoming: ReadonlyMap<string, FlowEdge[]>,
  cards: ReadonlyMap<string, CleanupCard>,
  laneOf: ReadonlyMap<string, number>,
  rank: ReadonlyMap<string, number>,
  laneRow: number,
  placements: ReadonlyMap<string, Placement>,
): number {
  for (const edge of incoming.get(id) ?? []) {
    const upstream = cards.get(edge.source);
    if (!upstream || upstream.kind === "artifact") continue;
    if (laneOf.get(edge.source) !== laneIndex) continue;
    if ((rank.get(edge.source) ?? 0) !== (rank.get(id) ?? 0) - 1) continue;
    const placed = placements.get(edge.source);
    if (!placed) continue;
    const delta =
      placed.row + edge.sourceRowOffset - (laneRow + edge.targetRowOffset);
    if (Math.abs(delta) <= PORT_ALIGN_TOLERANCE) {
      return Math.max(laneRow, laneRow + delta);
    }
  }
  return laneRow;
}

/**
 * Where every card of one experiment lands.
 *
 * A column is as wide as its widest card, so a narrow provider never shortens
 * the run; lanes stack downward; and a card only slides down its own column to
 * put two ports on one row.
 */
function placeExperiment(
  cards: ReadonlyMap<string, CleanupCard>,
  lanes: readonly Lane[],
  rank: ReadonlyMap<string, number>,
  edges: readonly FlowEdge[],
  satellitesByConsumer: ReadonlyMap<string, Satellite[]>,
  laneOf: ReadonlyMap<string, number>,
  startCol: number,
  startRow: number,
  params: CellCleanupParams,
) {
  const members = [...rank.keys()];
  const satellites = new Map<string, Satellite>();
  for (const list of satellitesByConsumer.values()) {
    for (const satellite of list)
      satellites.set(satellite.providerId, satellite);
  }
  const placements = new Map<string, Placement>();
  let maxRank = -1;
  for (const id of [...members, ...satellites.keys()]) {
    const at = satellites.has(id)
      ? (rank.get((satellites.get(id) as Satellite).consumerId) ?? 0) - 1
      : (rank.get(id) ?? 0);
    maxRank = Math.max(maxRank, at);
  }
  if (maxRank < 0) return { placements, bottomRow: startRow };

  const columnWidth: number[] = [];
  const columnStart: number[] = [];
  for (let column = 0; column <= maxRank; column += 1) {
    let width = 1;
    for (const [id, card] of cards) {
      if (!isMemberOf(id, column, rank, satellites)) continue;
      width = Math.max(width, card.widthCells);
    }
    columnWidth.push(width);
    columnStart.push(
      column === 0
        ? startCol
        : (columnStart[column - 1] as number) +
            (columnWidth[column - 1] as number) +
            gutterAfterColumn(edges, rank, column - 1, params.columnGapCells),
    );
  }

  const incoming = new Map<string, FlowEdge[]>();
  for (const id of members) incoming.set(id, []);
  for (const edge of edges) incoming.get(edge.target)?.push(edge);

  const colFor = (id: string, column: number): number => {
    const width = cards.get(id)?.widthCells ?? 1;
    // A provider sits flush with its column's right seam: the shortest wire to
    // the consumer, and it stops the provider's own width from moving anything.
    if (satellites.has(id)) {
      return (
        (columnStart[column] as number) + (columnWidth[column] ?? width) - width
      );
    }
    return columnStart[column] as number;
  };

  let laneRow = startRow;
  for (const lane of lanes) {
    let laneBottom = laneRow;
    for (let column = 0; column <= maxRank; column += 1) {
      const slot = lane.slots.get(column) ?? [];
      let row = laneRow;
      slot.forEach((id, index) => {
        const card = cards.get(id);
        if (!card) return;
        const satellite = satellites.get(id);
        if (index > 0) {
          const above = cards.get(slot[index - 1] as string);
          const abovePlacement = placements.get(slot[index - 1] as string);
          if (above && abovePlacement) {
            row = abovePlacement.row + above.heightCells + params.stackGapCells;
          }
        } else if (satellite && slot.length === 1) {
          // A provider alone in its column exists to feed one port, so put that
          // port on its consumer's row instead of the lane's top.
          const aligned =
            params.alignPorts && laneOf.get(satellite.consumerId) === lane.index
              ? satellite.targetRowOffset - satellite.sourceRowOffset
              : 0;
          row = Math.max(laneRow, laneRow + aligned);
        } else if (params.alignPorts) {
          row = straightRowFor(
            id,
            lane.index,
            incoming,
            cards,
            laneOf,
            rank,
            laneRow,
            placements,
          );
        } else {
          row = laneRow;
        }
        placements.set(id, { col: colFor(id, column), row });
        laneBottom = Math.max(laneBottom, row + card.heightCells);
        row += card.heightCells + params.stackGapCells;
      });
    }
    laneRow = laneBottom + params.laneGapCells;
  }
  return { placements, bottomRow: laneRow - params.laneGapCells };
}

/** Which column a card holds: its own rank, or one left of the card it serves. */
function isMemberOf(
  id: string,
  column: number,
  rank: ReadonlyMap<string, number>,
  satellites: ReadonlyMap<string, Satellite>,
): boolean {
  const satellite = satellites.get(id);
  if (satellite) {
    return (rank.get(satellite.consumerId) ?? 0) - 1 === column;
  }
  return rank.get(id) === column;
}

/**
 * The stray cards, in a strip under the wired graph, in the order a person
 * would have read them where they were.
 */
function placeParked(
  parked: readonly CleanupCard[],
  startCol: number,
  startRow: number,
) {
  const placements = new Map<string, Placement>();
  let column = startCol;
  let row = startRow;
  let rowHeight = 0;
  for (const card of parked) {
    if (
      column > startCol &&
      column + card.widthCells > startCol + PARKED_MAX_ROW_WIDTH_CELLS
    ) {
      column = startCol;
      row += rowHeight + PARKED_GAP_Y_CELLS;
      rowHeight = 0;
    }
    placements.set(card.id, { col: column, row });
    column += card.widthCells + PARKED_GAP_X_CELLS;
    rowHeight = Math.max(rowHeight, card.heightCells);
  }
  return { placements, bottomRow: row + rowHeight };
}

// --- Phase 5: annotations --------------------------------------------------

/**
 * Notes and frames follow the cards they were drawn against.
 *
 * A frame is a claim about a group — "these three are one comparison" — so it
 * closes on where those cards ended up. A note is pinned to one card and rides
 * with it. Neither is ever dragged into the graph itself.
 */
function placeAnnotations(
  annotations: readonly AnnotationNode[],
  cards: readonly CleanupCard[],
  placements: ReadonlyMap<string, Placement>,
): Map<
  string,
  { position: { x: number; y: number }; layout: AnnotationLayout }
> {
  const next = new Map<
    string,
    { position: { x: number; y: number }; layout: AnnotationLayout }
  >();
  const newRectOf = (card: CleanupCard): Rect | null => {
    const placement = placements.get(card.id);
    if (!placement) return null;
    return {
      x: placement.col * CELL_SIZE,
      y: placement.row * CELL_SIZE,
      width: card.widthCells * CELL_SIZE,
      height: card.heightCells * CELL_SIZE,
    };
  };
  const occupied: Rect[] = [];
  for (const card of cards) {
    const rect = newRectOf(card);
    if (rect) occupied.push(rect);
  }

  for (const annotation of annotations) {
    const frame = annotation.data.kind !== "text";
    const enclosed = cards.filter((card) => {
      const centreX = card.origX + card.origWidthPx / 2;
      const centreY = card.origY + card.origHeightPx / 2;
      return (
        centreX >= annotation.position.x &&
        centreX <= annotation.position.x + annotation.data.layout.width &&
        centreY >= annotation.position.y &&
        centreY <= annotation.position.y + annotation.data.layout.height
      );
    });
    const wrapped = frame ? encloseCards(enclosed, newRectOf) : null;
    if (wrapped) {
      next.set(annotation.id, wrapped);
      continue;
    }
    const anchor = nearestCard(annotation, cards);
    const moved = anchor ? placements.get(anchor.id) : undefined;
    const shiftX = moved ? moved.col * CELL_SIZE - anchor!.origX : 0;
    const shiftY = moved ? moved.row * CELL_SIZE - anchor!.origY : 0;
    const x = snapCell(annotation.position.x + shiftX) * CELL_SIZE;
    let y = snapCell(annotation.position.y + shiftY) * CELL_SIZE;
    if (!moved) {
      // A note nothing was near stays put, but never underneath a card that
      // moved into its space: those go to the foot of the canvas.
      const clash = occupied.find((rect) => overlaps(rect, x, y, annotation));
      if (clash) {
        y = Math.max(...occupied.map((rect) => rect.y + rect.height));
        y = snapCell(y + CELL_SIZE) * CELL_SIZE;
      }
    }
    next.set(annotation.id, {
      position: { x, y },
      layout: clampAnnotationLayout({ ...annotation.data.layout }),
    });
  }
  return next;
}

/** The frame that wraps these cards' new boxes with two cells of air. */
function encloseCards(
  enclosed: readonly CleanupCard[],
  newRectOf: (card: CleanupCard) => Rect | null,
) {
  const rects = enclosed
    .map(newRectOf)
    .filter((rect): rect is Rect => rect !== null);
  if (rects.length === 0) return null;
  const pad = FRAME_PADDING_CELLS * CELL_SIZE;
  const left = Math.min(...rects.map((rect) => rect.x));
  const top = Math.min(...rects.map((rect) => rect.y));
  const right = Math.max(...rects.map((rect) => rect.x + rect.width));
  const bottom = Math.max(...rects.map((rect) => rect.y + rect.height));
  return {
    position: { x: left - pad, y: top - pad },
    layout: clampAnnotationLayout({
      width: right - left + pad * 2,
      height: bottom - top + pad * 2,
    }),
  };
}

/** The card a note was written against: nearest original rectangle, within reach. */
function nearestCard(
  annotation: AnnotationNode,
  cards: readonly CleanupCard[],
): CleanupCard | null {
  let best: CleanupCard | null = null;
  let bestDistance = Number.POSITIVE_INFINITY;
  for (const card of cards) {
    const dx = distanceOnAxis(
      annotation.position.x,
      card.origX,
      card.origX + card.origWidthPx,
    );
    const dy = distanceOnAxis(
      annotation.position.y,
      card.origY,
      card.origY + card.origHeightPx,
    );
    const distance = dx + dy;
    if (distance < bestDistance) {
      best = card;
      bestDistance = distance;
    }
  }
  return bestDistance <= NOTE_ATTACH_PX ? best : null;
}

function distanceOnAxis(point: number, from: number, to: number): number {
  if (point < from) return from - point;
  if (point > to) return point - to;
  return 0;
}

function overlaps(
  rect: Rect,
  x: number,
  y: number,
  annotation: AnnotationNode,
): boolean {
  return (
    x < rect.x + rect.width &&
    x + annotation.data.layout.width > rect.x &&
    y < rect.y + rect.height &&
    y + annotation.data.layout.height > rect.y
  );
}

// --- The plan -------------------------------------------------------------

function samePosition(
  a: { x: number; y: number } | null | undefined,
  b: { x: number; y: number },
): boolean {
  return (
    !!a &&
    Math.abs(a.x - b.x) <= POSITION_EPSILON &&
    Math.abs(a.y - b.y) <= POSITION_EPSILON
  );
}

function sameSavedLayout(
  a: SavedNodeLayout | null | undefined,
  b: SavedNodeLayout | null,
): boolean {
  if (!a || !b) return !a && !b;
  return (
    (a.width ?? null) === (b.width ?? null) &&
    (a.body_height ?? null) === (b.body_height ?? null) &&
    (a.appendix_height ?? null) === (b.appendix_height ?? null)
  );
}

function sameWorkflowLayout(
  a: WorkflowNodeLayout | null,
  b: WorkflowNodeLayout | null,
): boolean {
  if (!a || !b) return !a && !b;
  return (
    (a.width ?? null) === (b.width ?? null) &&
    (a.bodyHeight ?? null) === (b.bodyHeight ?? null) &&
    (a.appendixHeight ?? null) === (b.appendixHeight ?? null)
  );
}

function sameRouteOffset(
  a: { x: number; y: number } | null | undefined,
  b: { x: number; y: number } | null | undefined,
): boolean {
  if (!a || !b) return !a && !b;
  return a.x === b.x && a.y === b.y;
}

/**
 * What the canvas knows about one card that the cleanup needs to place it.
 *
 * Its *new* size comes from the sized scene, its *old* rectangle from the scene
 * built before any sizing: a person paired two cards by eye at the sizes they
 * had, and reading order is theirs, not the layout's.
 */
function cleanupCards(
  before: CleanupScene,
  after: CleanupScene,
  serviceProviderByNode: ReadonlyMap<string, boolean>,
): CleanupCard[] {
  const beforeById = new Map(before.graph.cards.map((card) => [card.id, card]));
  const cards: CleanupCard[] = [];
  for (const card of after.graph.cards) {
    if (!card.kind || card.kind === "annotation") continue;
    const surface = after.surfaceById[card.id];
    const artifact =
      surface?.kind === "artifact"
        ? (surface as ArtifactCardSurfaceData)
        : null;
    const was = beforeById.get(card.id);
    cards.push({
      id: card.id,
      kind: card.kind,
      widthCells: card.widthCells,
      heightCells: card.heightCells,
      origX: (was?.col ?? card.col) * CELL_SIZE,
      origY: (was?.row ?? card.row) * CELL_SIZE,
      origWidthPx: (was?.widthCells ?? card.widthCells) * CELL_SIZE,
      origHeightPx: (was?.heightCells ?? card.heightCells) * CELL_SIZE,
      artifactTypeId: artifact?.artifactTypeId ?? "",
      previewKind: artifact?.previewKind ?? null,
      serviceProvider: serviceProviderByNode.get(card.id) ?? false,
    });
  }
  return cards;
}

/**
 * Every card's value the adapters need, whether or not the card was dropped with
 * one. A card that follows a node shows what that node last made; a card that
 * feeds a plug shows the origin it filled. Without this the origin pipes of a
 * card authored empty would never appear, and the cleanup would straighten a
 * graph with the wires missing.
 */
function inferViewerValues(
  document: AuthoredGraphDocument,
  viewers: readonly ArtifactViewerNode[],
  viewerEdges: readonly ArtifactViewerEdge[],
  specs: ReadonlyMap<string, NodeSpec | null>,
  options: CellCleanupOptions,
): {
  outputs: Map<string, ViewerOutputValue>;
  originLinks: CellOriginLink[];
} {
  const outputs = new Map<string, ViewerOutputValue>(
    options.viewerOutputValues ?? [],
  );
  const viewerIds = new Set(viewers.map((viewer) => viewer.id));

  for (const origin of document.origins) {
    const shape: "one" | "many" = "item_refs" in origin.value ? "many" : "one";
    for (const cardId of origin.source_card_ids ?? []) {
      if (!cardId || !viewerIds.has(cardId) || outputs.has(cardId)) continue;
      outputs.set(cardId, {
        artifactTypeId: origin.value.artifact_type,
        schemaVersion: origin.value.schema_version,
        shape,
      });
    }
  }
  for (const edge of viewerEdges) {
    if (outputs.has(edge.target)) continue;
    const output = outputTypeOfNode(
      specs.get(edge.source) ?? null,
      document.nodes.find((node) => node.id === edge.source),
      edge.data?.sourcePortName,
    );
    if (!output) continue;
    outputs.set(edge.target, output);
  }
  return {
    outputs,
    originLinks: synthesizeOriginLinks(document, viewers, viewerIds),
  };
}

function resolveSpecsFromSemantics(
  semantics: ResolvedGraphSemantics,
  document: AuthoredGraphDocument,
): Map<string, NodeSpec | null> {
  return new Map(
    document.nodes.map((node) => [
      node.id,
      semantics.nodes.get(node.id)?.displaySpec ?? null,
    ]),
  );
}

/** What one output port of a node carries, once its bindings resolve. */
function outputTypeOfNode(
  spec: NodeSpec | null,
  node: AuthoredGraphNode | undefined,
  portName: string | undefined,
): ViewerOutputValue | null {
  if (!spec || !node || !portName) return null;
  const port = spec.outputs.find((candidate) => candidate.name === portName);
  if (!port) return null;
  const binding = port.artifact_type_variable
    ? node.artifact_type_bindings.find(
        (candidate) => candidate.variable === port.artifact_type_variable,
      )
    : undefined;
  const key = binding?.artifact_type ?? port.artifact_type;
  if (!key) return null;
  return {
    artifactTypeId: key.id,
    schemaVersion: key.schema_version,
    shape: port.shape,
  };
}

/**
 * The origin pipes the scene should draw, per card rather than per artifact.
 *
 * A card that feeds a plug *is* the origin's source: with `source_card_ids` the
 * canvas says so outright, and for older documents the card holding exactly the
 * origin's artifacts is the one that filled it.
 */
function synthesizeOriginLinks(
  document: AuthoredGraphDocument,
  viewers: readonly ArtifactViewerNode[],
  viewerIds: ReadonlySet<string>,
): CellOriginLink[] {
  const links: CellOriginLink[] = [];
  const link = (origin: SavedGraphOrigin, sourceCardId: string) => ({
    id: `artifact-origin:${origin.id}:${sourceCardId}`,
    originId: origin.id,
    sourceCardId,
    targetCardId: origin.to_node,
    targetPortId: targetPortId(origin.to_port, origin.to_plug),
    collectionMode: origin.collection_mode,
    conversionCount: origin.conversion_path.length,
  });
  for (const origin of document.origins) {
    if (origin.source_card_ids != null) {
      const seen = new Set<string>();
      for (const cardId of origin.source_card_ids) {
        if (!cardId || !viewerIds.has(cardId) || seen.has(cardId)) continue;
        seen.add(cardId);
        links.push(link(origin, cardId));
      }
      continue;
    }
    // An older document never said which card filled the plug, so the card that
    // holds exactly these artifacts did — same rule the canvas pipes use.
    const remaining = new Set(
      cardArtifactRefs(origin.value).map((ref) => ref.artifact_id),
    );
    for (const viewer of viewers) {
      const refs = cardArtifactRefs(viewer.data.artifactRef);
      if (!viewerIds.has(viewer.id) || refs.length === 0) continue;
      if (
        refs.some(
          (ref) =>
            ref.artifact_type !== origin.value.artifact_type ||
            ref.schema_version !== origin.value.schema_version,
        )
      ) {
        continue;
      }
      if (!refs.every((ref) => remaining.has(ref.artifact_id))) continue;
      links.push(link(origin, viewer.id));
      for (const ref of refs) remaining.delete(ref.artifact_id);
      if (remaining.size === 0) break;
    }
  }
  return links;
}

// --- The commands and the new state ---------------------------------------

/**
 * The authoring commands that turn the current document into the cleaned one:
 * moves for the cards that moved, layouts for the cards that resized, and a
 * cleared `route_offset` for every wire the author had nudged by hand — the
 * layout changed under it, so its old offset is now a kink.
 */
function buildCommands(
  document: AuthoredGraphDocument,
  placements: ReadonlyMap<string, Placement>,
  layoutsByNode: ReadonlyMap<string, SavedNodeLayout | null>,
  agentsById: ReadonlyMap<string, { width: number; height: number }>,
  inScopeEdge: (from: string, to: string) => boolean,
  clearRouteOffsets: boolean,
): GraphCommand[] {
  const moves: { cardId: string; col: number; row: number }[] = [];
  for (const [id, placement] of placements) {
    const node = document.nodes.find((candidate) => candidate.id === id);
    if (
      node &&
      !samePosition(
        node.position,
        cellToWorldOrigin(placement.col, placement.row),
      )
    ) {
      moves.push({ cardId: id, col: placement.col, row: placement.row });
    }
  }
  const commands: GraphCommand[] = graphCommandsFromCellMovesForDocument(
    document,
    moves,
  );

  for (const [id, placement] of placements) {
    const agent = document.agents.find((candidate) => candidate.id === id);
    if (!agent) continue;
    const position = cellToWorldOrigin(placement.col, placement.row);
    const box = agentsById.get(id) ?? {
      width: agent.width,
      height: agent.height,
    };
    const resized = agent.width !== box.width || agent.height !== box.height;
    if (samePosition(agent.position, position) && !resized) continue;
    commands.push({
      kind: "configure_agent",
      agent: { ...agent, position, width: box.width, height: box.height },
    });
  }

  for (const [id, layout] of layoutsByNode) {
    const node = document.nodes.find((candidate) => candidate.id === id);
    if (!node) continue;
    if (sameSavedLayout(node.layout ?? null, layout)) continue;
    commands.push({ kind: "update_node_layout", node_id: id, layout });
  }

  if (clearRouteOffsets) {
    for (const edge of document.edges) {
      if (edge.route_offset == null) continue;
      if (!inScopeEdge(edge.from_node, edge.to_node)) continue;
      commands.push({
        kind: "update_edge",
        edge_id: edge.id,
        update: { route_offset: null },
      });
    }
  }
  return commands;
}

/**
 * The presentation state of the cleaned graph: every following card at its new
 * cell with its canonical size, and every hand-drawn link offset dropped for
 * the same reason a wire's is.
 */
function nextViewerState(
  artifactViewers: ArtifactViewerCanvasState,
  sizedLayouts: ReadonlyMap<string, WorkflowNodeLayout | null>,
  placements: ReadonlyMap<string, Placement>,
  annotations: ReadonlyMap<
    string,
    { position: { x: number; y: number }; layout: AnnotationLayout }
  >,
  inScopeEdge: (from: string, to: string) => boolean,
  clearRouteOffsets: boolean,
): ArtifactViewerCanvasState {
  const nodes = artifactViewers.nodes.map((viewer) => {
    const placement = placements.get(viewer.id);
    if (!placement) return viewer;
    const layout = sizedLayouts.has(viewer.id)
      ? (sizedLayouts.get(viewer.id) ?? null)
      : viewer.data.layout;
    const position = cellToWorldOrigin(placement.col, placement.row);
    if (
      samePosition(viewer.position, position) &&
      sameWorkflowLayout(viewer.data.layout, layout)
    ) {
      return viewer;
    }
    return { ...viewer, position, data: { ...viewer.data, layout } };
  });
  const edges = clearRouteOffsets
    ? artifactViewers.edges.map((edge) => {
        if (edge.data?.routeOffset == null) return edge;
        if (!inScopeEdge(edge.source, edge.target)) return edge;
        const { routeOffset: _cleared, ...rest } = edge.data;
        return { ...edge, data: rest };
      })
    : artifactViewers.edges;
  const annotationNodes = artifactViewers.annotations.map((annotation) => {
    const placed = annotations.get(annotation.id);
    if (!placed) return annotation;
    if (
      samePosition(annotation.position, placed.position) &&
      annotation.data.layout.width === placed.layout.width &&
      annotation.data.layout.height === placed.layout.height
    ) {
      return annotation;
    }
    return {
      ...annotation,
      position: placed.position,
      data: { ...annotation.data, layout: placed.layout },
    };
  });
  return {
    ...artifactViewers,
    nodes,
    edges,
    annotations: annotationNodes,
  };
}

function boundsOf(
  cards: ReadonlyMap<string, CleanupCard>,
  placements: ReadonlyMap<string, Placement>,
): CellCleanupPlan["bounds"] {
  let left = Number.POSITIVE_INFINITY;
  let top = Number.POSITIVE_INFINITY;
  let right = Number.NEGATIVE_INFINITY;
  let bottom = Number.NEGATIVE_INFINITY;
  for (const [id, placement] of placements) {
    const card = cards.get(id);
    if (!card) continue;
    left = Math.min(left, placement.col * CELL_SIZE);
    top = Math.min(top, placement.row * CELL_SIZE);
    right = Math.max(right, (placement.col + card.widthCells) * CELL_SIZE);
    bottom = Math.max(bottom, (placement.row + card.heightCells) * CELL_SIZE);
  }
  if (!Number.isFinite(left)) return null;
  return { x: left, y: top, width: right - left, height: bottom - top };
}

function snapshotOf(
  document: AuthoredGraphDocument,
  artifactViewers: ArtifactViewerCanvasState,
  placements: ReadonlyMap<string, Placement>,
): CellCleanupUndoSnapshot {
  const touched = (id: string) => placements.has(id);
  return {
    nodeSnapshots: new Map(
      document.nodes
        .filter((node) => touched(node.id))
        .map((node) => [
          node.id,
          {
            position: { x: node.position.x, y: node.position.y },
            layout: node.layout ?? null,
          },
        ]),
    ),
    edgeRouteOffsets: new Map(
      document.edges.map((edge) => [
        edge.id,
        edge.route_offset
          ? { x: edge.route_offset.x, y: edge.route_offset.y }
          : null,
      ]),
    ),
    agentSnapshots: new Map(
      document.agents
        .filter((agent) => touched(agent.id))
        .map((agent) => [
          agent.id,
          {
            position: {
              x: agent.position?.x ?? 0,
              y: agent.position?.y ?? 0,
            },
            width: agent.width,
            height: agent.height,
          },
        ]),
    ),
    viewerSnapshots: new Map(
      artifactViewers.nodes
        .filter((viewer) => touched(viewer.id))
        .map((viewer) => [
          viewer.id,
          {
            position: { x: viewer.position.x, y: viewer.position.y },
            layout: viewer.data.layout,
          },
        ]),
    ),
    viewerEdgeRouteOffsets: new Map(
      artifactViewers.edges.map((edge) => [
        edge.id,
        edge.data?.routeOffset
          ? {
              x: edge.data.routeOffset.x,
              y: edge.data.routeOffset.y,
            }
          : undefined,
      ]),
    ),
    annotationSnapshots: new Map(
      artifactViewers.annotations.map((annotation) => [
        annotation.id,
        {
          position: { x: annotation.position.x, y: annotation.position.y },
          layout: { ...annotation.data.layout },
        },
      ]),
    ),
  };
}

// --- The entry point -------------------------------------------------------

export function planCellGraphCleanup(
  document: AuthoredGraphDocument,
  artifactViewers: ArtifactViewerCanvasState,
  registry: NodeRegistry,
  options: CellCleanupOptions = {},
): CellCleanupPlan {
  const params = resolveCleanupParams(options);
  const { resizeCards } = params;
  const sizeProfile = CARD_SIZE_PROFILES[params.cardSize];
  const semantics = resolveGraphSemantics(document, registry);
  const specsByNode = resolveSpecsFromSemantics(semantics, document);
  const values = inferViewerValues(
    document,
    artifactViewers.nodes,
    artifactViewers.edges,
    specsByNode,
    options,
  );

  // The scene as it stands, before a single card is resized. The cleanup reads
  // the wiring and the author's own geometry off this, and only then rebuilds
  // with canonical sizes.
  const before = buildScene(
    document,
    artifactViewers,
    registry,
    options,
    semantics,
    values,
  );
  const { inScope, isScoped, startCol, startRow } = resolveScope(
    before,
    options,
  );
  const serviceProviderByNode = new Map(
    document.nodes.map((node) => [
      node.id,
      isServiceProviderNode(specsByNode.get(node.id) as NodeSpec),
    ]),
  );

  // Phase 1: canonical sizing, before the sized scene exists. The adapters then
  // compute widths, heights, and port rows for the cards the author ends up
  // with, so a port the resize moved onto row 4 is on row 4 when the flow is read.
  const sizedDocument: AuthoredGraphDocument =
    resizeCards && document.nodes.some((node) => inScope(node.id))
      ? {
          ...document,
          nodes: document.nodes.map((node) =>
            inScope(node.id)
              ? {
                  ...node,
                  layout: canonicalNodeLayout(
                    node,
                    specsByNode.get(node.id),
                    sizeProfile,
                  ),
                }
              : node,
          ),
        }
      : document;
  const sizedAgents =
    resizeCards && document.agents.some((agent) => inScope(agent.id))
      ? document.agents.map((agent) =>
          inScope(agent.id)
            ? { ...agent, ...canonicalAgentBox(agent, sizeProfile) }
            : agent,
        )
      : document.agents;
  const documentSized =
    sizedDocument.nodes === document.nodes && sizedAgents === document.agents
      ? sizedDocument
      : { ...sizedDocument, agents: sizedAgents };
  const layoutsByNode = new Map<string, SavedNodeLayout | null>(
    documentSized.nodes.map((node) => [node.id, node.layout ?? null]),
  );
  const agentsById = new Map(
    sizedAgents.map((agent) => [
      agent.id,
      { width: agent.width, height: agent.height },
    ]),
  );

  const sizedLayouts = resizeCards
    ? canonicalViewerLayouts(before, options, inScope, sizeProfile)
    : new Map<string, WorkflowNodeLayout | null>();
  const sizedViewers: ArtifactViewerCanvasState =
    sizedLayouts.size === 0
      ? artifactViewers
      : {
          ...artifactViewers,
          nodes: artifactViewers.nodes.map((viewer) =>
            sizedLayouts.has(viewer.id)
              ? {
                  ...viewer,
                  data: {
                    ...viewer.data,
                    layout: sizedLayouts.get(viewer.id) ?? null,
                  },
                }
              : viewer,
          ),
        };
  const scene =
    documentSized === document && sizedViewers === artifactViewers
      ? before
      : buildScene(
          documentSized,
          sizedViewers,
          registry,
          options,
          semantics,
          values,
        );

  const sceneCards = new Map<string, SceneCard>(
    scene.graph.cards.map((card) => [card.id, card]),
  );
  const cards = cleanupCards(before, scene, serviceProviderByNode);
  const scope = cards.filter((card) => inScope(card.id));
  const scopeCards = new Map(scope.map((card) => [card.id, card]));
  const inScopeEdge = (from: string, to: string) =>
    inScope(from) && inScope(to);

  const edges = collectFlowEdges(
    document,
    artifactViewers.bindings,
    sceneCards,
    scene.graph.pipes,
    inScope,
  );
  const scopeDegrees = new Map<string, { in: number; out: number }>();
  for (const card of scope) scopeDegrees.set(card.id, { in: 0, out: 0 });
  for (const edge of edges) {
    const out = scopeDegrees.get(edge.source);
    const inc = scopeDegrees.get(edge.target);
    if (out) out.out += 1;
    if (inc) inc.in += 1;
  }

  // Phase 2: a second card of the same type, set beside a wired one, is a
  // comparison, and a comparison belongs together.
  const companionEdges: FlowEdge[] = [];
  if (params.keepCompanions) {
    for (const card of scope) {
      if (card.kind !== "artifact") continue;
      const own = scopeDegrees.get(card.id);
      if (!own || own.in + own.out > 0) continue;
      const owner = findCompanionOwner(
        card,
        scope,
        (id) => scopeDegrees.get(id) ?? { in: 0, out: 0 },
      );
      if (!owner) continue;
      companionEdges.push({
        source: owner.id,
        target: card.id,
        sourcePortId: `companion:${owner.id}`,
        targetPortId: `companion:${card.id}`,
        sourceRowOffset: FIRST_PORT_ROW,
        targetRowOffset: FIRST_PORT_ROW,
        companion: true,
      });
    }
  }
  const allEdges = [...edges, ...companionEdges];

  const experiments: string[][] = [];
  const parked: CleanupCard[] = [];
  for (const component of connectedComponents(
    scope.map((card) => card.id),
    allEdges,
  )) {
    if (component.length === 1) {
      const card = scopeCards.get(component[0] as string);
      if (card) parked.push(card);
      continue;
    }
    experiments.push(component);
  }
  const experimentAnchorCard = (component: readonly string[]): CleanupCard => {
    const memberSet = new Set(component);
    const roots = component.filter(
      (id) =>
        !allEdges.some(
          (edge) => edge.target === id && memberSet.has(edge.source),
        ),
    );
    const candidates = (roots.length > 0 ? roots : component)
      .map((id) => scopeCards.get(id))
      .filter((card): card is CleanupCard => card !== undefined)
      .sort(compareOrigPosition);
    return candidates[0] as CleanupCard;
  };
  experiments.sort((a, b) =>
    compareOrigPosition(experimentAnchorCard(a), experimentAnchorCard(b)),
  );

  // Phases 3 and 4, one experiment at a time, stacked top to bottom.
  const placements = new Map<string, Placement>();
  let cursorRow = startRow;
  for (const component of experiments) {
    const members = component;
    const memberEdges = allEdges.filter(
      (edge) =>
        scopeCards.has(edge.source) &&
        scopeCards.has(edge.target) &&
        members.includes(edge.source) &&
        members.includes(edge.target),
    );
    const { remaining, kept, satellitesByConsumer } = params.tuckProviders
      ? detachSatellites(scopeCards, members, memberEdges)
      : {
          remaining: members,
          kept: memberEdges,
          satellitesByConsumer: new Map<string, Satellite[]>(),
        };
    const seeded = degrees(remaining, kept);
    const forward = breakCycles(remaining, kept, scopeCards, seeded.inDegree);
    const ranked = degrees(remaining, forward);
    const rank = assignRanks(
      remaining,
      forward,
      ranked.inDegree,
      ranked.outDegree,
      new Set(satellitesByConsumer.keys()),
    );
    const { lanes, laneOf } = traceLanes(
      scopeCards,
      remaining,
      forward,
      rank,
      satellitesByConsumer,
      ranked.inDegree,
    );
    const placed = placeExperiment(
      scopeCards,
      lanes,
      rank,
      forward,
      satellitesByConsumer,
      laneOf,
      startCol,
      cursorRow,
      params,
    );
    let bottom = cursorRow;
    for (const [id, placement] of placed.placements) {
      placements.set(id, placement);
      bottom = Math.max(
        bottom,
        placement.row + (scopeCards.get(id)?.heightCells ?? 0),
      );
    }
    cursorRow = bottom + params.experimentGapCells;
  }

  parked.sort(compareReadingOrder);
  for (const [id, placement] of placeParked(
    parked,
    startCol,
    experiments.length > 0 ? cursorRow : startRow,
  ).placements) {
    placements.set(id, placement);
  }

  const annotationPlacements = isScoped
    ? new Map<
        string,
        { position: { x: number; y: number }; layout: AnnotationLayout }
      >()
    : placeAnnotations(artifactViewers.annotations, cards, placements);

  const graphCommands = buildCommands(
    document,
    placements,
    restrict(layoutsByNode, placements),
    agentsById,
    inScopeEdge,
    params.clearRouteOffsets,
  );
  const nextArtifactViewers = nextViewerState(
    artifactViewers,
    sizedLayouts,
    placements,
    annotationPlacements,
    inScopeEdge,
    params.clearRouteOffsets,
  );
  const movedViewers = nextArtifactViewers.nodes.some(
    (viewer, index) => viewer !== artifactViewers.nodes[index],
  );
  const movedLinks = nextArtifactViewers.edges.some(
    (edge, index) => edge !== artifactViewers.edges[index],
  );

  return {
    graphCommands,
    nextArtifactViewers,
    affectedCardCount: placements.size,
    experimentCount: experiments.length,
    bounds: boundsOf(scopeCards, placements),
    undoSnapshot: snapshotOf(document, artifactViewers, placements),
    changed:
      graphCommands.length > 0 ||
      movedViewers ||
      movedLinks ||
      nextArtifactViewers.annotations.some(
        (annotation, index) =>
          annotation !== artifactViewers.annotations[index],
      ),
  };
}

function restrict(
  values: ReadonlyMap<string, SavedNodeLayout | null>,
  placements: ReadonlyMap<string, Placement>,
): Map<string, SavedNodeLayout | null> {
  const scoped = new Map<string, SavedNodeLayout | null>();
  for (const [id, layout] of values) {
    if (placements.has(id)) scoped.set(id, layout);
  }
  return scoped;
}

/**
 * Which cards the cleanup may touch, and the cell it starts laying them at.
 *
 * One selected card is not a selection worth cleaning: straightening a single
 * card against nothing is a no-op the author would read as the canvas ignoring
 * them. A scoped cleanup anchors on the selection's own top-left, so tidying a
 * corner of the graph never drags it across the screen.
 */
function resolveScope(scene: CleanupScene, options: CellCleanupOptions) {
  const known = foregroundCardsOf(scene);
  const scoped = new Set<string>();
  for (const id of options.selectedCardIds ?? []) {
    if (known.has(id)) scoped.add(id);
  }
  if (scoped.size < 2) {
    return {
      isScoped: false,
      inScope: () => true as boolean,
      startCol: SAFE_ORIGIN_COL,
      startRow: SAFE_ORIGIN_ROW,
    };
  }
  let startCol = Number.POSITIVE_INFINITY;
  let startRow = Number.POSITIVE_INFINITY;
  for (const card of scene.graph.cards) {
    if (!scoped.has(card.id)) continue;
    startCol = Math.min(startCol, snapCell(card.col * CELL_SIZE));
    startRow = Math.min(startRow, snapCell(card.row * CELL_SIZE));
  }
  return {
    isScoped: true,
    inScope: (id: string) => scoped.has(id),
    startCol,
    startRow,
  };
}

/** The cards a person sees and drags: everything but the furniture underneath. */
function foregroundCardsOf(scene: CleanupScene): Set<string> {
  const ids = new Set<string>();
  for (const card of scene.graph.cards) {
    if (card.kind && card.kind !== "annotation") ids.add(card.id);
  }
  return ids;
}

/**
 * The scene for one sizing pass.
 *
 * `originLinks` and the inferred values are handed over rather than left to the
 * adapters' own matching, because the cleanup must see the wires the canvas will
 * draw, including the ones whose card was authored empty.
 */
function buildScene(
  document: AuthoredGraphDocument,
  artifactViewers: ArtifactViewerCanvasState,
  registry: NodeRegistry,
  options: CellCleanupOptions,
  semantics: ResolvedGraphSemantics,
  values: {
    outputs: Map<string, ViewerOutputValue>;
    originLinks: CellOriginLink[];
  },
) {
  return cellGraphFromAuthoredDocument(document, registry, {
    semantics,
    presentation: presentationFromArtifactViewers(artifactViewers),
    nodeRunState: options.nodeRunState,
    collapsedAppendices: options.collapsedAppendices,
    configSections: options.configSections,
    viewerImages: options.viewerImages,
    viewerOutputValues: values.outputs,
    originLinks: values.originLinks,
  });
}

/**
 * What each artifact card should be sized to, read off the scene so the canvas's
 * own answer about *which* kind of card it is decides the size.
 *
 * A TIFF card is only as big as its reader needs if something actually consumes
 * the window it opened; unwired, it is just a picture.
 */
function canonicalViewerLayouts(
  scene: CleanupScene,
  options: CellCleanupOptions,
  inScope: (id: string) => boolean,
  profile: CardSizeProfile,
): Map<string, WorkflowNodeLayout | null> {
  const sizes = new Map<string, WorkflowNodeLayout | null>();
  for (const card of scene.graph.cards) {
    if (card.kind !== "artifact" || !inScope(card.id)) continue;
    const surface = scene.surfaceById[card.id];
    if (surface?.kind !== "artifact") continue;
    const artifact = surface as ArtifactCardSurfaceData;
    const wired = scene.graph.pipes.some(
      (pipe) => pipe.sourceCardId === card.id,
    );
    sizes.set(
      card.id,
      canonicalViewerLayout(
        artifact.previewKind,
        artifact.artifactTypeId,
        artifact.previewKind === "tiff" && wired,
        options.viewerImages?.get(card.id)?.naturalSize,
        profile,
      ),
    );
  }
  return sizes;
}

/**
 * Combine two sequential cleanup snapshots, keeping the earliest recorded state
 * for every card, wire, and annotation. That way repeated cleanups (for example
 * while tweaking parameters or expanding scope from a selection to the whole
 * canvas) can always restore the original pre-cleanup layout.
 */
export function mergeCleanupUndoSnapshots(
  earlier: CellCleanupUndoSnapshot,
  later: CellCleanupUndoSnapshot,
): CellCleanupUndoSnapshot {
  const mergeMaps = <V>(
    first: ReadonlyMap<string, V>,
    second: ReadonlyMap<string, V>,
  ): Map<string, V> => {
    const merged = new Map<string, V>(second);
    for (const [id, value] of first) {
      merged.set(id, value);
    }
    return merged;
  };
  return {
    nodeSnapshots: mergeMaps(earlier.nodeSnapshots, later.nodeSnapshots),
    edgeRouteOffsets: mergeMaps(
      earlier.edgeRouteOffsets,
      later.edgeRouteOffsets,
    ),
    agentSnapshots: mergeMaps(earlier.agentSnapshots, later.agentSnapshots),
    viewerSnapshots: mergeMaps(earlier.viewerSnapshots, later.viewerSnapshots),
    viewerEdgeRouteOffsets: mergeMaps(
      earlier.viewerEdgeRouteOffsets,
      later.viewerEdgeRouteOffsets,
    ),
    annotationSnapshots: mergeMaps(
      earlier.annotationSnapshots,
      later.annotationSnapshots,
    ),
  };
}

/**
 * Put the graph back the way it was.
 *
 * The cleanup overwrote positions, sizes, hand-drawn wire offsets, and the whole
 * furniture layer; the snapshot holds each of those exactly as it found them, so
 * undo is a diff against the snapshot rather than a remembered copy of a canvas
 * that may have been edited in between.
 */
export function buildCleanupUndoPlan(
  currentDocument: AuthoredGraphDocument,
  currentArtifactViewers: ArtifactViewerCanvasState,
  snapshot: CellCleanupUndoSnapshot,
): {
  readonly graphCommands: readonly GraphCommand[];
  readonly nextArtifactViewers: ArtifactViewerCanvasState;
  readonly changed: boolean;
} {
  const commands: GraphCommand[] = [];

  const nodeMoves: { node_id: string; x: number; y: number }[] = [];
  for (const node of currentDocument.nodes) {
    const was = snapshot.nodeSnapshots.get(node.id);
    if (!was) continue;
    if (!samePosition(node.position, was.position)) {
      // Undo restores the author's pixels, not the grid's: a card nudged to
      // 410 was at 410, and an undo that lands it on 400 moved it again.
      nodeMoves.push({
        node_id: node.id,
        x: was.position.x,
        y: was.position.y,
      });
    }
    if (!sameSavedLayout(node.layout ?? null, was.layout)) {
      commands.push({
        kind: "update_node_layout",
        node_id: node.id,
        layout: was.layout,
      });
    }
  }
  if (nodeMoves.length > 0) {
    commands.unshift({ kind: "move_nodes", positions: nodeMoves });
  }

  for (const agent of currentDocument.agents) {
    const was = snapshot.agentSnapshots.get(agent.id);
    if (!was) continue;
    if (
      samePosition(agent.position, was.position) &&
      agent.width === was.width &&
      agent.height === was.height
    ) {
      continue;
    }
    commands.push({
      kind: "configure_agent",
      agent: {
        ...agent,
        position: was.position,
        width: was.width,
        height: was.height,
      },
    });
  }

  for (const edge of currentDocument.edges) {
    if (!snapshot.edgeRouteOffsets.has(edge.id)) continue;
    const was = snapshot.edgeRouteOffsets.get(edge.id) ?? null;
    if (sameRouteOffset(edge.route_offset, was)) continue;
    commands.push({
      kind: "update_edge",
      edge_id: edge.id,
      update: { route_offset: was },
    });
  }

  const nodes = currentArtifactViewers.nodes.map((viewer) => {
    const was = snapshot.viewerSnapshots.get(viewer.id);
    if (!was) return viewer;
    if (
      samePosition(viewer.position, was.position) &&
      sameWorkflowLayout(viewer.data.layout, was.layout)
    ) {
      return viewer;
    }
    return {
      ...viewer,
      position: was.position,
      data: { ...viewer.data, layout: was.layout },
    };
  });
  const edges = currentArtifactViewers.edges.map((edge) => {
    if (!snapshot.viewerEdgeRouteOffsets.has(edge.id)) return edge;
    const was = snapshot.viewerEdgeRouteOffsets.get(edge.id);
    if (sameRouteOffset(edge.data?.routeOffset, was)) return edge;
    const { routeOffset: _dropped, ...rest } = edge.data ?? {
      sourcePortName: "",
    };
    if (!was) return { ...edge, data: rest };
    return { ...edge, data: { ...rest, routeOffset: was } };
  });
  const annotations = currentArtifactViewers.annotations.map((annotation) => {
    const was = snapshot.annotationSnapshots.get(annotation.id);
    if (!was) return annotation;
    if (
      samePosition(annotation.position, was.position) &&
      annotation.data.layout.width === was.layout.width &&
      annotation.data.layout.height === was.layout.height
    ) {
      return annotation;
    }
    return {
      ...annotation,
      position: was.position,
      data: { ...annotation.data, layout: was.layout },
    };
  });

  const changed =
    commands.length > 0 ||
    nodes.some((node, index) => node !== currentArtifactViewers.nodes[index]) ||
    edges.some((edge, index) => edge !== currentArtifactViewers.edges[index]) ||
    annotations.some(
      (annotation, index) =>
        annotation !== currentArtifactViewers.annotations[index],
    );
  return {
    graphCommands: commands,
    nextArtifactViewers: {
      ...currentArtifactViewers,
      nodes,
      edges,
      annotations,
    },
    changed,
  };
}
