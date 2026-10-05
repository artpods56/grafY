import type { ArtifactRef } from "@/lib/api";

/**
 * One member of a collection, as the card shows it. Kept apart from
 * `model/collection` because the node data in `canvas/types` carries it, and
 * `model/collection` reads that data.
 */
export type CollectionMember =
  | {
      readonly plugId: string;
      readonly kind: "library";
      readonly originId: string;
      readonly refs: readonly ArtifactRef[];
    }
  | {
      readonly plugId: string;
      readonly kind: "output";
      readonly edgeId: string;
      readonly sourceNodeId: string;
      readonly sourcePortName: string;
      /** "Resize image → Resized". */
      readonly label: string;
      /** The producer's latest output, or null until it has run. */
      readonly refs: readonly ArtifactRef[] | null;
    }
  | {
      readonly plugId: string;
      readonly kind: "empty";
    };
