/**
 * The scene root: an authored graph document in, a cell graph out.
 *
 * Each card kind is built by the module that owns it — nodes by
 * `cell-operator-adapter`, agents, artifacts and annotations by
 * `cell-artifact-adapter`, connections by `cell-pipe-adapter` — and this module
 * only composes them in the order the canvas stacks its layers: nodes, agents,
 * artifact cards, then annotations underneath. It is also the adapters' public
 * face, so callers keep importing one module whatever the split looks like
 * inside.
 */
import type { NodeRegistry, SavedGraphDocument } from "@/lib/api";

import type { AuthoredGraphDocument } from "../authoring/graph-document";

import type { CellCardSurfaceData } from "./cell-contracts";
import type { CellGraph } from "./cell-model";
import {
  buildAgentCardsAndSurfaces,
  buildAnnotationCardsAndSurfaces,
  buildViewerCardsAndSurfaces,
  type CellViewerImages,
  type CellViewerMetadata,
} from "./cell-artifact-adapter";
import {
  buildOperatorCardsAndSurfaces,
  type CellNodeRunState,
} from "./cell-operator-adapter";
import {
  buildCellPipes,
  type CellOriginLink,
  type CellPipeMetadata,
} from "./cell-pipe-adapter";

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
  const operators = buildOperatorCardsAndSurfaces(document, registry, {
    nodeRunState: options?.nodeRunState,
    collapsedAppendices: options?.collapsedAppendices,
  });
  const agents = buildAgentCardsAndSurfaces(document);
  const presentation = options?.presentation ?? null;
  const viewers = presentation?.viewers ?? [];
  const presentationLinks = presentation?.links ?? [];
  const artifacts = buildViewerCardsAndSurfaces(
    document,
    registry,
    operators.specsByNode,
    {
      viewers,
      links: presentationLinks,
      viewerOutputValues: options?.viewerOutputValues,
      viewerImages: options?.viewerImages,
      viewerMetadata: options?.viewerMetadata,
    },
  );
  const annotations = buildAnnotationCardsAndSurfaces(
    presentation?.annotations ?? [],
  );

  const cards = [
    ...operators.cards,
    ...agents.cards,
    ...artifacts.cards,
    ...annotations.cards,
  ];
  const surfaces = new Map([
    ...operators.surfaces,
    ...agents.surfaces,
    ...artifacts.surfaces,
    ...annotations.surfaces,
  ]);

  return {
    graph: {
      cards,
      pipes: buildCellPipes(
        document,
        viewers,
        presentationLinks,
        new Set(cards.map((card) => card.id)),
        {
          originLinks: options?.originLinks,
          pipeMetadataById: options?.pipeMetadataById,
        },
      ),
    },
    surfaceById: Object.fromEntries(surfaces),
  };
}

export {
  annotationHexFromToken,
  cellArtifactImageCells,
} from "./cell-artifact-adapter";
export { cellOriginFromWorld, snapPixelsToCell } from "./cell-adapter-shared";
export {
  graphCommandsFromCellAddPlug,
  graphCommandsFromCellConfigChange,
  graphCommandsFromCellDelete,
  graphCommandsFromCellDeleteForDocument,
  graphCommandsFromCellMoves,
  graphCommandsFromCellMovesForDocument,
  graphCommandsFromCellRemovePlug,
  graphCommandsFromCellResize,
  graphCommandsFromCellResizeForDocument,
} from "./cell-operator-adapter";
export { graphCommandsFromCellConnect } from "./cell-pipe-adapter";

export type {
  CellViewerImages,
  CellViewerMetadata,
} from "./cell-artifact-adapter";
export type { CellNodeRunState } from "./cell-operator-adapter";
export type { CellOriginLink, CellPipeMetadata } from "./cell-pipe-adapter";
