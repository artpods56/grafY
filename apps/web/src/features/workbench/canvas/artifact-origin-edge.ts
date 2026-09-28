import type { Edge } from "@xyflow/react";

export const ARTIFACT_ORIGIN_EDGE_TYPE = "grafyArtifactOriginEdge";

interface ArtifactOriginEdgeData extends Record<string, unknown> {
  originId: string;
  onDisconnect?: (originId: string) => void;
}

export type ArtifactOriginEdge = Edge<
  ArtifactOriginEdgeData,
  typeof ARTIFACT_ORIGIN_EDGE_TYPE
> & { data: ArtifactOriginEdgeData };
