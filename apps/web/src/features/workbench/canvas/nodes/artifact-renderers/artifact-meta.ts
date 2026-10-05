import type { ArtifactSummary } from "@/lib/api";

export function artifactMeta(
  artifact: ArtifactSummary,
): Record<string, unknown> {
  return {
    type: `${artifact.artifact_type}@${artifact.schema_version}`,
    content_type: artifact.content_type,
    ...(artifact.byte_size != null ? { byte_size: artifact.byte_size } : {}),
    ...(artifact.text ? { text: artifact.text } : {}),
    artifact_id: artifact.artifact_id,
  };
}
