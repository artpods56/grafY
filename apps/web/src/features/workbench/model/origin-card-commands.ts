import type { SavedGraphOrigin } from "@/lib/api";
import {
  artifactCardValue,
  cardArtifactRefs,
  type ArtifactCardValue,
} from "../canvas/artifact-card";
import type { GraphCommand } from "./graph-document";

/** Replace just these cards' contributions, preserving other copies and their order. */
export function changeOriginCardReferences(
  origin: SavedGraphOrigin,
  cardIds: ReadonlySet<string>,
  replacement: ArtifactCardValue | null = null,
): GraphCommand[] {
  const owners = origin.source_card_ids;
  const replacementRefs = cardArtifactRefs(replacement);
  if (owners == null) {
    const value = artifactCardValue(replacementRefs, origin.value);
    return value
      ? [{ kind: "update_origin", origin_id: origin.id, update: { value } }]
      : [{ kind: "remove_origins", origin_ids: [origin.id] }];
  }
  const refs = cardArtifactRefs(origin.value);
  const nextRefs: typeof refs = [];
  const nextOwners: (string | null)[] = [];
  let replaced = false;
  for (const [index, owner] of owners.entries()) {
    if (owner !== null && cardIds.has(owner)) {
      if (!replaced) {
        nextRefs.push(...replacementRefs);
        nextOwners.push(...replacementRefs.map(() => owner));
        replaced = true;
      }
    } else {
      const ref = refs[index];
      if (ref) {
        nextRefs.push(ref);
        nextOwners.push(owner);
      }
    }
  }
  if (!replaced) return [];
  const value = artifactCardValue(nextRefs, origin.value);
  return value
    ? [
        {
          kind: "update_origin",
          origin_id: origin.id,
          update: { value, source_card_ids: nextOwners },
        },
      ]
    : [{ kind: "remove_origins", origin_ids: [origin.id] }];
}
