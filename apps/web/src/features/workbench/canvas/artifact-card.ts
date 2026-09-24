import type { ArtifactRef, SavedGraphOrigin } from "@/lib/api";
import { createUuid } from "@/features/workbench/model/uuid";

/**
 * What one canvas artifact card presents: a single artifact, or an ordered run
 * of artifacts of the same type. It is the same value shape an origin carries,
 * so what a card shows and what a card passes on are one thing.
 */
export type ArtifactCardValue = SavedGraphOrigin["value"];

/** Card width when placed: five lattice cells at the default cell size. */
export const DEFAULT_ARTIFACT_CARD_WIDTH = 250;

/**
 * Width a file or PDF card opens at: three lattice cells. It has no pixels to
 * fill, so it takes the narrowest card that still reads as a document.
 */
export const DEFAULT_ARTIFACT_FILE_CARD_WIDTH = 150;

/**
 * Narrowest a card may be snapped. Workflow nodes floor at `NODE_WIDTH_MIN`,
 * which would bump the five-cell card default up to six, so a card declares
 * its own narrower lattice floor.
 */
export const ARTIFACT_CARD_WIDTH_MIN = 150;

/** A card's media box is 4:3 until the operator shapes it. */
export const ARTIFACT_CARD_MEDIA_ASPECT = 3 / 4;

/** The height an unresized card's media box takes at a given width. */
export function artifactCardMediaHeight(width: number): number {
  return Math.round(width * ARTIFACT_CARD_MEDIA_ASPECT);
}

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
  if (refs.length === 1 && !(previous && "item_refs" in previous)) return first;
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

/** Order selected canvas artifacts for collection, without repeating a ref. */
export function collectArtifactCardRefs(
  cards: readonly {
    position: { x: number; y: number };
    value: ArtifactCardValue;
  }[],
): ArtifactRef[] | null {
  if (cards.length < 2) return null;
  const seen = new Set<string>();
  const refs = [...cards]
    .sort(
      (left, right) =>
        left.position.y - right.position.y ||
        left.position.x - right.position.x,
    )
    .flatMap((card) => cardArtifactRefs(card.value))
    .filter((ref) => {
      if (seen.has(ref.artifact_id)) return false;
      seen.add(ref.artifact_id);
      return true;
    });
  if (refs.length < 2) return null;
  const first = refs[0];
  return refs.every((ref) => shareOneArtifactType(ref, first)) ? refs : null;
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
export function shareOneArtifactType(a: ArtifactRef, b: ArtifactRef): boolean {
  return (
    a.artifact_type === b.artifact_type && a.schema_version === b.schema_version
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

/** The value contract, including sequence shape even for one item. */
export function artifactCardContract(value: ArtifactCardValue | null): string {
  if (!value) return "";
  const contract = `${value.artifact_type}@${value.schema_version}`;
  return "item_refs" in value ? `Sequence<${contract}>` : contract;
}
