import type { SavedGraphOrigin } from "@/lib/api";

export const ARTIFACT_ORIGIN_EDGE_TYPE = "grafyArtifactOriginEdge";

type OriginCollectionMode = SavedGraphOrigin["collection_mode"];

interface ArtifactOriginEdgeData {
  originId: string;
  collectionMode?: OriginCollectionMode;
  allowedCollectionModes?: readonly OriginCollectionMode[];
}

export interface ArtifactOriginEdge {
  id: string;
  type?: typeof ARTIFACT_ORIGIN_EDGE_TYPE;
  source: string;
  target: string;
  targetPort: string;
  targetPlug?: string | null;
  selected?: boolean;
  data: ArtifactOriginEdgeData;
}
