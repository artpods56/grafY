/**
 * Pipes: the edges between cards, the artifact origins that feed a plug, and
 * the presentation links that wire a node output to an artifact card.
 *
 * A pipe is only ever a routing problem's input, so this module reads card ids
 * and never sizes or paints anything: it turns the document's connections into
 * the endpoints the cell router expects, and turns one drop into the command
 * that adds an edge.
 */
import type { SavedGraphDocument } from "@/lib/api";

import { cardArtifactRefs } from "../artifacts/artifact-card";
import type {
  AuthoredGraphDocument,
  GraphCommand,
} from "../authoring/graph-document";

import type { CellPipeModel } from "./cell-model";
import { PLUG_SEPARATOR, targetPortId } from "./cell-adapter-shared";

type PresentationViewers = NonNullable<
  SavedGraphDocument["presentation"]
>["viewers"];
type PresentationLinks = NonNullable<
  SavedGraphDocument["presentation"]
>["links"];

/** A card-to-card origin the caller has already resolved to concrete cards. */
export interface CellOriginLink {
  id: string;
  originId: string;
  sourceCardId: string;
  targetCardId: string;
  targetPortId: string;
  collectionMode: "direct" | "map";
  conversionCount?: number;
}

/** How the caller would word a pipe's labels, and whether it can carry at all. */
export interface CellPipeMetadata {
  projectionLabel?: string | null;
  conversionLabel?: string | null;
  sourcePortLabel?: string;
  incompatible?: boolean;
}

/**
 * Every pipe in the scene. Origins become artifact-card-to-plug pipes unless
 * the caller named its own links; edges and presentation links only survive
 * when both of their ends are cards on the canvas.
 */
export function buildCellPipes(
  document: AuthoredGraphDocument,
  viewers: PresentationViewers,
  presentationLinks: PresentationLinks,
  cardIds: ReadonlySet<string>,
  options?: {
    originLinks?: readonly CellOriginLink[];
    pipeMetadataById?: ReadonlyMap<string, CellPipeMetadata>;
  },
): CellPipeModel[] {
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

  return [
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
}

/**
 * The edge a port drop adds. A plug's port id carries its plug after
 * {@link PLUG_SEPARATOR}, which is how the canvas names one drop target per
 * plug; the document keeps the two halves apart.
 */
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
