import type { ArtifactTypeSpec } from "@/lib/api";
import {
  artifactTypeKey,
  type ArtifactTypeIdentity,
} from "./artifact-type-key";

/**
 * Anything that names artifact types — `registry.artifact_types` or a subset of
 * it. A call site with no registry passes `null` on purpose and gets full
 * identities back, never a bare id.
 */
export type ArtifactTypeCatalog =
  readonly Pick<ArtifactTypeSpec, "key" | "title">[] | null;

/** The catalog's name for a type, or `null` when the catalog does not list it. */
function catalogTitle(
  artifactType: ArtifactTypeIdentity,
  artifactTypes: ArtifactTypeCatalog,
): string | null {
  const title = artifactTypes?.find(
    (candidate) =>
      candidate.key.id === artifactType.id &&
      candidate.key.schema_version === artifactType.schema_version,
  )?.title;
  return title?.trim() || null;
}

/**
 * The name the catalog gives a type. `@1` is a backend identity detail that
 * never changes for a shipped primitive, so it is not part of a person-facing
 * name — but a type the catalog does not list has no name to lose, so it falls
 * back to its full identity (`scalar.text@1`) rather than a bare id.
 */
export function artifactTypeTitle(
  artifactType: ArtifactTypeIdentity,
  artifactTypes: ArtifactTypeCatalog,
): string {
  return (
    catalogTitle(artifactType, artifactTypes) ?? artifactTypeKey(artifactType)
  );
}

/**
 * What a person reads for one artifact type: `"Text value"`, or
 * `"Text value · v2"` once the schema has actually moved past its first
 * version — the same separator the node catalog uses. An unnamed type is shown
 * as its identity, which already carries the version.
 */
export function formatArtifactTypeLabel(
  artifactType: ArtifactTypeIdentity,
  artifactTypes: ArtifactTypeCatalog,
): string {
  const title = catalogTitle(artifactType, artifactTypes);
  if (title === null) return artifactTypeKey(artifactType);
  return artifactType.schema_version > 1
    ? `${title} · v${artifactType.schema_version}`
    : title;
}

/** A label wrapped in the sequence shape: `Sequence<Text value>`. */
export function formatArtifactTypeSequence(label: string): string {
  return `Sequence<${label}>`;
}

/**
 * One type, or a sequence of it, in the shape a card or port reads its contract
 * in: `Text value` / `Sequence<Text value>`.
 */
export function formatArtifactTypeContract(
  artifactType: ArtifactTypeIdentity,
  artifactTypes: ArtifactTypeCatalog,
  many = false,
): string {
  const label = formatArtifactTypeLabel(artifactType, artifactTypes);
  return many ? formatArtifactTypeSequence(label) : label;
}

/**
 * The full identity behind a label, kept where it is still useful: a tooltip or
 * the type inspector. `"scalar.text@1"`.
 */
export function formatArtifactTypeTooltip(
  artifactType: ArtifactTypeIdentity,
): string {
  return artifactTypeKey(artifactType);
}

/** The full identity of a sequence: `Sequence<scalar.text@1>`. */
export function formatArtifactTypeSequenceTooltip(
  artifactType: ArtifactTypeIdentity,
): string {
  return formatArtifactTypeSequence(formatArtifactTypeTooltip(artifactType));
}
