import type { ArtifactRef, SavedGraphOrigin } from "@/lib/api";
import { createUuid } from "@/features/workbench/model/uuid";

/**
 * What one canvas artifact card presents: a single artifact, or an ordered run
 * of artifacts of the same type. It is the same value shape an origin carries,
 * so what a card shows and what a card passes on are one thing.
 */
export type ArtifactCardValue = SavedGraphOrigin["value"];

/** Card width when it is placed and has never been resized. */
export const DEFAULT_ARTIFACT_CARD_WIDTH = 264;

/** The card's artifacts in the order it presents and passes them. */
export function cardArtifactRefs(
  value: ArtifactCardValue | null | undefined,
): ArtifactRef[] {
  if (!value) return [];
  return "item_refs" in value ? [...value.item_refs] : [value];
}

/**
 * The value that presents exactly these artifacts, or null when they cannot sit
 * on one card: two artifacts of different types never share a sequence, so a
 * mixed card has no honest representation.
 */
export function artifactCardValue(
  refs: readonly ArtifactRef[],
  previous?: ArtifactCardValue | null,
): ArtifactCardValue | null {
  if (refs.length === 0) return null;
  const first = refs[0];
  const mixedType = refs.some(
    (ref) =>
      ref.artifact_type !== first.artifact_type ||
      ref.schema_version !== first.schema_version,
  );
  if (mixedType) return null;
  if (refs.length === 1) return first;
  return {
    artifact_type: first.artifact_type,
    schema_version: first.schema_version,
    item_refs: refs.map((ref) => ({ ...ref })),
    ordered: true,
    index_key: "order_index",
    sequence_id:
      previous && "sequence_id" in previous && previous.sequence_id
        ? previous.sequence_id
        : createUuid(),
  };
}

/**
 * The value that presents the target card's artifacts followed by the dropped
 * ones, keeping an artifact that is already on the card in its first position.
 */
export function mergedArtifactCardValue(
  target: ArtifactCardValue | null | undefined,
  dropped: ArtifactCardValue | null | undefined,
): ArtifactCardValue | null {
  const targetRefs = cardArtifactRefs(target);
  const seen = new Set(targetRefs.map((ref) => ref.artifact_id));
  const added = cardArtifactRefs(dropped).filter(
    (ref) => !seen.has(ref.artifact_id),
  );
  if (added.length === 0) return null;
  return artifactCardValue([...targetRefs, ...added], target ?? null);
}

/** These cards may sit together: merging them leaves a value a card can hold. */
export function canMergeIntoCard(
  target: ArtifactCardValue | null | undefined,
  dropped: ArtifactCardValue | null | undefined,
): boolean {
  return mergedArtifactCardValue(target, dropped) !== null;
}

/** These artifacts may join one card: they share one artifact type. */
export function shareOneArtifactType(
  a: ArtifactRef,
  b: ArtifactRef,
): boolean {
  return (
    a.artifact_type === b.artifact_type &&
    a.schema_version === b.schema_version
  );
}

/** The same artifacts with the one at `index` moved `delta` places, clamped. */
export function moveArtifactCardRef(
  refs: readonly ArtifactRef[],
  index: number,
  delta: number,
): ArtifactRef[] {
  const target = Math.min(refs.length - 1, Math.max(0, index + delta));
  if (index < 0 || index >= refs.length || index === target) return [...refs];
  const next = [...refs];
  const [moved] = next.splice(index, 1);
  next.splice(target, 0, moved);
  return next;
}

/**
 * Artifact types the browser can paint directly. A card without a library
 * entry has no content type to ask, so it falls back on the declared type.
 */
const IMAGE_ARTIFACT_TYPES = new Set([
  "image.raster",
  "image.pixmap",
  "geo.raster_scan",
  "file.png",
  "file.jpeg",
  "file.tiff",
  "file.webp",
  "file.bmp",
]);

/** Whether a card paints this artifact as a picture. */
export function isImageArtifact(
  ref: ArtifactRef,
  contentType?: string | null,
): boolean {
  if (contentType) return contentType.toLowerCase().startsWith("image/");
  return IMAGE_ARTIFACT_TYPES.has(ref.artifact_type);
}

/** Whether a presentation viewer carries artifacts of its own, so it is a card. */
export function presentsArtifacts(
  value: ArtifactCardValue | null | undefined,
): value is ArtifactCardValue {
  return value !== null && value !== undefined;
}

/** The artifact ids a card presents. */
export function cardArtifactIds(
  value: ArtifactCardValue | null | undefined,
): string[] {
  return cardArtifactRefs(value).map((ref) => ref.artifact_id);
}

/**
 * Whether an origin's value carries what this card presents, which is how a
 * card learns it is already passed into an input. The card owns the order, so
 * reordering it rewrites the origin that carries it.
 */
export function originCarriesCardArtifacts(
  originValue: ArtifactCardValue,
  cardValue: ArtifactCardValue | null | undefined,
): boolean {
  const cardIds = new Set(cardArtifactIds(cardValue));
  if (cardIds.size === 0) return false;
  const originRefs = cardArtifactRefs(originValue);
  return (
    originRefs.length > 0 &&
    originRefs.every((ref) => cardIds.has(ref.artifact_id))
  );
}

/** The contract line a card shows: `file.jpg@1`, or `file.jpg@1 · 3 items`. */
export function artifactCardContract(value: ArtifactCardValue | null): string {
  const refs = cardArtifactRefs(value);
  if (refs.length === 0) return "";
  const contract = `${refs[0].artifact_type}@${refs[0].schema_version}`;
  return refs.length === 1 ? contract : `${contract} · ${refs.length} items`;
}
