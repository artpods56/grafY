/** The ingest notice the Library and Runs keep on a `file.blob@1` card. */

export const BLOB_ARTIFACT_TYPE = "file.blob";
export const BLOB_ARTIFACT_SCHEMA_VERSION = 1;
export const BLOB_ARTIFACT_NOTICE = "Format not recognized, stored as a blob.";

export function isBlobArtifact(artifact: {
  artifact_type: string;
  schema_version: number;
}): boolean {
  return (
    artifact.artifact_type === BLOB_ARTIFACT_TYPE &&
    artifact.schema_version === BLOB_ARTIFACT_SCHEMA_VERSION
  );
}
