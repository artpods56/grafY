/**
 * The cards that follow a graph rather than author it: agent boxes, artifact
 * cards, and annotations.
 *
 * None of these sizes comes from a node layout. An artifact card is sized by
 * the picture it paints, an annotation by the frame the author drew, and an
 * agent by its own box, so each keeps its own bounds and its own way back to
 * the saved document.
 */
import type {
  ArtifactRef,
  ArtifactTypeKey,
  ArtifactTypeSpec,
  NodeRegistry,
  NodeSpec,
  SavedGraphDocument,
} from "@/lib/api";

import {
  DEFAULT_ARTIFACT_CARD_WIDTH,
  DEFAULT_ARTIFACT_MAP_BODY_HEIGHT,
  DEFAULT_ARTIFACT_MAP_CARD_WIDTH,
  DEFAULT_ARTIFACT_TABLE_BODY_HEIGHT,
  DEFAULT_ARTIFACT_TABLE_CARD_WIDTH,
  artifactTypeFor,
} from "../artifacts/artifact-card";
import type { AuthoredGraphDocument } from "../authoring/graph-document";

import type {
  AnnotationColorToken,
  ArtifactCardSurfaceData,
  ArtifactPreviewKind,
  ArtifactStackItem,
  CellCardSurfaceData,
} from "./cell-contracts";
import {
  DEFAULT_ARTIFACT_HEIGHT_CELLS,
  DEFAULT_ARTIFACT_WIDTH_CELLS,
  DEFAULT_FREE_MAX_CELLS,
  MAX_ARTIFACT_HEIGHT_CELLS,
  MAX_ARTIFACT_WIDTH_CELLS,
  MAX_AUTO_ARTIFACT_HEIGHT_CELLS,
  MAX_SCHEMA_LAYOUT_CELLS,
  MIN_AGENT_HEIGHT_CELLS,
  MIN_ARTIFACT_HEIGHT_CELLS,
  MIN_ARTIFACT_WIDTH_CELLS,
  MIN_ANNOTATION_HEIGHT_CELLS,
  MIN_ANNOTATION_WIDTH_CELLS,
  MIN_CARD_WIDTH_CELLS,
  cellOriginFromWorld,
  collectionTypeLabel,
  portArtifactType,
  snapPixelsToCell,
} from "./cell-adapter-shared";
import {
  CARD_PLATE_BOTTOM_INSET,
  CARD_PLATE_INSET_X,
  CARD_PLATE_TOP,
  CELL_SIZE,
  STRIP_FIRST_PORT_ROW,
  type CellCardModel,
  type CellPort,
  artifactCardOutputRow,
} from "./cell-model";

type PresentationViewers = NonNullable<
  SavedGraphDocument["presentation"]
>["viewers"];
type PresentationAnnotations = NonNullable<
  SavedGraphDocument["presentation"]
>["annotations"];
type PresentationLinks = NonNullable<
  SavedGraphDocument["presentation"]
>["links"];

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

/**
 * Preview kind when a unit test hands the adapter an empty catalog.
 * A populated catalog is the source of truth, including a missing type.
 */
function fallbackPreviewKind(artifactTypeId: string): ArtifactPreviewKind {
  switch (artifactTypeId) {
    case "file.tiff":
      return "tiff";
    case "ocr.tiff_text_regions":
    case "ocr.tiff_recognized_text":
      return "tiff-text";
    case "html.page":
      return "html-page";
    case "text.markdown":
      return "markdown";
    case "geo.feature_collection":
    case "geo.raster_scan":
    case "geo.map_layer":
    case "geo.map_document":
      return "map";
    case "table.data":
      return "table";
    case "scalar.text":
    case "scalar.integer":
    case "image.regions":
    case "json.schema":
    case "prompt.message":
    case "llm.completion":
    case "file.json":
    case "file.geojson":
    case "file.txt":
      return "text";
    default: {
      const lower = artifactTypeId.toLowerCase();
      if (
        lower.startsWith("image.") ||
        /^file\.(png|jpe?g|webp|bmp)$/.test(lower)
      ) {
        return "image";
      }
      if (lower.startsWith("table.") || lower.includes("tabular")) {
        return "table";
      }
      if (lower.startsWith("geo.")) return "map";
      if (lower.startsWith("text.") || lower.startsWith("prompt.")) {
        return "markdown";
      }
      return "file";
    }
  }
}

function previewKindFor(
  artifactKey: ArtifactTypeKey | null,
  artifactTypes: readonly ArtifactTypeSpec[],
): ArtifactPreviewKind {
  if (artifactTypes.length === 0) {
    return fallbackPreviewKind(artifactKey?.id ?? "");
  }
  if (!artifactKey) return "file";
  return (
    artifactTypeFor(
      {
        artifact_type: artifactKey.id,
        schema_version: artifactKey.schema_version,
      },
      artifactTypes,
    )?.preview_kind ?? "file"
  );
}

/** Pixel size a non-picture card opens at when its author has not sized it. */
function defaultCardPixels(previewKind: ArtifactPreviewKind): {
  width: number;
  height: number;
} {
  switch (previewKind) {
    case "table":
      return {
        width: DEFAULT_ARTIFACT_TABLE_CARD_WIDTH,
        height: DEFAULT_ARTIFACT_TABLE_BODY_HEIGHT,
      };
    case "map":
      return {
        width: DEFAULT_ARTIFACT_MAP_CARD_WIDTH,
        height: DEFAULT_ARTIFACT_MAP_BODY_HEIGHT,
      };
    default:
      return { width: DEFAULT_ARTIFACT_CARD_WIDTH, height: 150 };
  }
}

/** Agent cards: the graph's own boxes, sized in the document, never derived. */
export function buildAgentCardsAndSurfaces(document: AuthoredGraphDocument): {
  cards: CellCardModel[];
  surfaces: Map<string, CellCardSurfaceData>;
} {
  const cards: CellCardModel[] = [];
  const surfaces = new Map<string, CellCardSurfaceData>();
  for (const agent of document.agents) {
    const modelLabel =
      agent.model?.kind === "custom" ? agent.model.model : "Deployment model";
    const widthCells = Math.max(
      MIN_CARD_WIDTH_CELLS,
      snapPixelsToCell(agent.width || 360),
    );
    const heightCells = Math.max(
      MIN_AGENT_HEIGHT_CELLS,
      snapPixelsToCell(agent.height || 200),
    );
    cards.push({
      id: agent.id,
      kind: "agent",
      title: agent.name || "Agent",
      subtitle: modelLabel,
      ...cellOriginFromWorld(agent.position ?? { x: 0, y: 0 }),
      widthCells,
      heightCells,
      ports: [],
      resizable: true,
      resizeBounds: {
        minWidthCells: MIN_CARD_WIDTH_CELLS,
        maxWidthCells: Math.min(
          MAX_SCHEMA_LAYOUT_CELLS,
          Math.max(DEFAULT_FREE_MAX_CELLS, widthCells),
        ),
        minHeightCells: MIN_AGENT_HEIGHT_CELLS,
        maxHeightCells: Math.min(
          MAX_SCHEMA_LAYOUT_CELLS,
          Math.max(DEFAULT_FREE_MAX_CELLS, heightCells),
        ),
      },
    });
    surfaces.set(agent.id, {
      kind: "agent",
      modelLabel,
      linkedToolCount: agent.tools.length,
      agentStatus: "idle",
      lastMessageSnippet: agent.instructions || undefined,
    });
  }
  return { cards, surfaces };
}

/**
 * Artifact cards: what each following card shows, sized by the picture it
 * paints or the layout its author left it at.
 */
export function buildViewerCardsAndSurfaces(
  document: AuthoredGraphDocument,
  registry: NodeRegistry,
  specsByNode: ReadonlyMap<string, NodeSpec | undefined>,
  options: {
    viewers: PresentationViewers;
    links: PresentationLinks;
    viewerOutputValues?: ReadonlyMap<
      string,
      { artifactTypeId: string; schemaVersion?: number; shape: "one" | "many" }
    >;
    viewerImages?: ReadonlyMap<string, CellViewerImages>;
    viewerMetadata?: ReadonlyMap<string, CellViewerMetadata>;
    /** Set with `viewerArtifacts` so a live renderer can read the workspace. */
    workspaceId?: string;
    /** Lead artifact of each card, when the caller has resolved one. */
    viewerArtifacts?: ReadonlyMap<string, ArtifactRef>;
    viewerTiffWindows?: ReadonlyMap<
      string,
      NonNullable<ArtifactCardSurfaceData["tiffWindow"]>
    >;
    viewerTiffTexts?: ReadonlyMap<
      string,
      NonNullable<ArtifactCardSurfaceData["tiffText"]>
    >;
  },
): { cards: CellCardModel[]; surfaces: Map<string, CellCardSurfaceData> } {
  const cards: CellCardModel[] = [];
  const surfaces = new Map<string, CellCardSurfaceData>();
  for (const viewer of options.viewers) {
    if (
      !viewer?.id ||
      typeof viewer.position?.x !== "number" ||
      !Number.isFinite(viewer.position.x) ||
      typeof viewer.position?.y !== "number" ||
      !Number.isFinite(viewer.position.y)
    ) {
      continue;
    }
    const feedLink = options.links.find(
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
    const liveOutput = options.viewerOutputValues?.get(viewer.id);
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
    const previewKind = previewKindFor(artifactKey, registry.artifact_types);
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
    const images = options.viewerImages?.get(viewer.id);
    const minHeightCells = feedLink
      ? STRIP_FIRST_PORT_ROW + 2
      : MIN_ARTIFACT_HEIGHT_CELLS;
    const picture =
      previewKind === "image" ||
      previewKind === "tiff" ||
      previewKind === "tiff-text";
    const defaults = defaultCardPixels(previewKind);
    const rawCells = picture
      ? cellArtifactImageCells(images?.naturalSize, viewer.layout)
      : {
          widthCells: Math.min(
            MAX_ARTIFACT_WIDTH_CELLS,
            Math.max(
              MIN_ARTIFACT_WIDTH_CELLS,
              snapPixelsToCell(viewer.layout?.width ?? defaults.width),
            ),
          ),
          heightCells: Math.min(
            MAX_ARTIFACT_HEIGHT_CELLS,
            Math.max(
              minHeightCells,
              snapPixelsToCell(viewer.layout?.body_height ?? defaults.height),
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
    const metadata = options.viewerMetadata?.get(viewer.id);
    const artifact = options.viewerArtifacts?.get(viewer.id);
    const tiffWindow = options.viewerTiffWindows?.get(viewer.id);
    const tiffText = options.viewerTiffTexts?.get(viewer.id);
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
      ...((previewKind === "image" || previewKind === "tiff") && images
        ? {
            imageUrl: images.imageUrl,
            ...(images.stackImageUrls.length
              ? { stackImageUrls: images.stackImageUrls }
              : {}),
          }
        : {}),
      ...(options.workspaceId && (artifact || tiffText)
        ? { workspaceId: options.workspaceId }
        : {}),
      ...(artifact ? { artifact } : {}),
      ...(tiffWindow ? { tiffWindow } : {}),
      ...(tiffText ? { tiffText } : {}),
    });
  }
  return { cards, surfaces };
}

/** Notes and frames: the author's sticky layer, drawn under every card. */
export function buildAnnotationCardsAndSurfaces(
  annotations: PresentationAnnotations,
): { cards: CellCardModel[]; surfaces: Map<string, CellCardSurfaceData> } {
  const cards: CellCardModel[] = [];
  const surfaces = new Map<string, CellCardSurfaceData>();
  for (const annotation of annotations) {
    const isNote = annotation.kind === "text";
    const widthCells = Math.max(
      MIN_ANNOTATION_WIDTH_CELLS,
      snapPixelsToCell(annotation.layout.width),
    );
    const heightCells = Math.max(
      MIN_ANNOTATION_HEIGHT_CELLS,
      snapPixelsToCell(annotation.layout.height),
    );
    cards.push({
      id: annotation.id,
      kind: "annotation",
      title: isNote ? "Note" : "Frame",
      subtitle: annotation.kind,
      ...cellOriginFromWorld(annotation.position),
      widthCells,
      heightCells,
      ports: [],
      resizable: true,
      resizeBounds: {
        minWidthCells: MIN_ANNOTATION_WIDTH_CELLS,
        maxWidthCells: Math.min(
          MAX_SCHEMA_LAYOUT_CELLS,
          Math.max(DEFAULT_FREE_MAX_CELLS, widthCells),
        ),
        minHeightCells: MIN_ANNOTATION_HEIGHT_CELLS,
        maxHeightCells: Math.min(
          MAX_SCHEMA_LAYOUT_CELLS,
          Math.max(DEFAULT_FREE_MAX_CELLS, heightCells),
        ),
      },
    });
    surfaces.set(annotation.id, {
      kind: "annotation",
      variant: isNote ? "note" : "frame",
      color: annotationColor(annotation.color),
      bodyText: annotation.text ?? "",
      layer: "under-cards",
    });
  }
  return { cards, surfaces };
}
