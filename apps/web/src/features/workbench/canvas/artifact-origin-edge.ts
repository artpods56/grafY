import type { Edge } from "@xyflow/react";
import type { SavedGraphOrigin } from "@/lib/api";

export const ARTIFACT_ORIGIN_EDGE_TYPE = "grafyArtifactOriginEdge";

type OriginCollectionMode = SavedGraphOrigin["collection_mode"];

interface ArtifactOriginEdgeData extends Record<string, unknown> {
  originId: string;
  collectionMode?: OriginCollectionMode;
  allowedCollectionModes?: readonly OriginCollectionMode[];
  onDisconnect?: (originId: string) => void;
  onCollectionModeChange?: (
    originId: string,
    collectionMode: OriginCollectionMode,
  ) => void;
}

export type ArtifactOriginEdge = Edge<
  ArtifactOriginEdgeData,
  typeof ARTIFACT_ORIGIN_EDGE_TYPE
> & { data: ArtifactOriginEdgeData };
