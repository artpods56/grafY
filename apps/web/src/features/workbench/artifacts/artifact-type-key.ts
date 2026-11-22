/**
 * An artifact type as the backend names it: its id and schema version. This is
 * identity, not a label — port compatibility, saved bindings, and API payloads
 * all compare this string. People read
 * `artifact-type-label.ts`'s titles instead.
 */
export interface ArtifactTypeIdentity {
  id: string;
  schema_version: number;
}

/** The shape of an identity: an id, `@`, and a schema version. */
export type ArtifactTypeId = `${string}@${number}`;

/** `scalar.text@1`. */
export function artifactTypeKey(
  artifactType: ArtifactTypeIdentity,
): ArtifactTypeId {
  return `${artifactType.id}@${artifactType.schema_version}`;
}
