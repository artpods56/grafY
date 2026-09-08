import { createUuid } from "@/features/workbench/model/uuid";
import type { WorkflowInputPlug } from "./input-plugs";

export const ARTIFACT_QUERY_OPERATOR_ID = "sql.artifacts.query";
export const ARTIFACT_QUERY_RELATIONS_PORT = "relations";

export interface ArtifactQueryRelation {
  id: string;
  alias: string;
}

function objectRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

/** Reads persisted relation config without manufacturing new plug identities. */
export function artifactQueryRelations(value: unknown): ArtifactQueryRelation[] {
  if (!Array.isArray(value)) return [];

  const seenIds = new Set<string>();
  const relations: ArtifactQueryRelation[] = [];
  for (const item of value) {
    const relation = objectRecord(item);
    if (
      !relation ||
      typeof relation.id !== "string" ||
      relation.id.length === 0 ||
      seenIds.has(relation.id) ||
      typeof relation.alias !== "string"
    ) {
      continue;
    }

    relations.push({ id: relation.id, alias: relation.alias });
    seenIds.add(relation.id);
  }
  return relations;
}

export function createArtifactQueryRelation(
  index: number,
  id: string = createUuid(),
  existingRelations: readonly ArtifactQueryRelation[] = [],
): ArtifactQueryRelation {
  const aliases = new Set(
    existingRelations.map((relation) => relation.alias.toLowerCase()),
  );
  let aliasNumber = index + 1;
  while (aliases.has(`relation_${aliasNumber}`)) aliasNumber += 1;

  return { id, alias: `relation_${aliasNumber}` };
}

/** A query requires at least one relation, so its last row cannot be removed. */
export function removeArtifactQueryRelation(
  relations: readonly ArtifactQueryRelation[],
  relationId: string,
): ArtifactQueryRelation[] {
  if (relations.length <= 1) return [...relations];
  return relations.filter((relation) => relation.id !== relationId);
}

export function moveArtifactQueryRelation(
  relations: readonly ArtifactQueryRelation[],
  relationId: string,
  toIndex: number,
): ArtifactQueryRelation[] {
  const fromIndex = relations.findIndex(
    (relation) => relation.id === relationId,
  );
  if (fromIndex === -1 || relations.length < 2) return [...relations];

  const boundedIndex = Math.max(0, Math.min(toIndex, relations.length - 1));
  if (fromIndex === boundedIndex) return [...relations];

  const reordered = [...relations];
  const [movedRelation] = reordered.splice(fromIndex, 1);
  reordered.splice(boundedIndex, 0, movedRelation);
  return reordered;
}

/**
 * Aligns relation plugs with their owning relation ids and config order.
 * Plugs for unrelated ports retain their relative order.
 */
export function reconcileArtifactQueryRelationInputPlugs(
  inputPlugs: readonly WorkflowInputPlug[],
  relations: readonly ArtifactQueryRelation[],
): WorkflowInputPlug[] {
  const desiredPlugs = relations.map((relation) => ({
    id: relation.id,
    portName: ARTIFACT_QUERY_RELATIONS_PORT,
  }));
  const firstPortIndex = inputPlugs.findIndex(
    (plug) => plug.portName === ARTIFACT_QUERY_RELATIONS_PORT,
  );
  const withoutPort = inputPlugs.filter(
    (plug) => plug.portName !== ARTIFACT_QUERY_RELATIONS_PORT,
  );
  const insertionIndex =
    firstPortIndex === -1
      ? withoutPort.length
      : inputPlugs
          .slice(0, firstPortIndex)
          .filter((plug) => plug.portName !== ARTIFACT_QUERY_RELATIONS_PORT)
          .length;

  return [
    ...withoutPort.slice(0, insertionIndex),
    ...desiredPlugs,
    ...withoutPort.slice(insertionIndex),
  ];
}
