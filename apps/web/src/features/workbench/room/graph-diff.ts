import type { CollaborativeHead } from "@/lib/api";

import { presentationFromCollaborativeHead } from "../canvas/artifact-viewer";
import type { GraphDiff, GraphEntityChange } from "./protocol";

/**
 * Apply one collection of the diff: entities the head already holds keep their
 * position and are replaced by `after` (or dropped when `after` is null), and
 * entities with a new id are appended in the diff's key order.
 */
function applyEntityChanges<T extends { readonly id: string }>(
  items: readonly T[],
  changes: Readonly<Record<string, GraphEntityChange<T>>>,
): T[] {
  // `hasOwn` everywhere so an entity id like "constructor" never matches an
  // inherited Object member.
  const held = new Set(items.map((item) => item.id));
  const next: T[] = [];
  for (const item of items) {
    if (!Object.hasOwn(changes, item.id)) {
      next.push(item);
      continue;
    }
    const change = changes[item.id]!;
    if (change.after !== null) next.push(change.after);
  }
  for (const key of Object.keys(changes)) {
    if (held.has(key) || !Object.hasOwn(changes, key)) continue;
    const change = changes[key]!;
    if (change.after !== null) next.push(change.after);
  }
  return next;
}

/**
 * The confirmed head with one accepted batch's entity diff applied: pure data,
 * no graph rules, so it cannot disagree with the server about the result.
 */
export function applyGraphDiffToHead(
  head: CollaborativeHead,
  diff: GraphDiff,
  sequence: number,
): CollaborativeHead {
  const presentation = presentationFromCollaborativeHead(head);
  return {
    ...head,
    name: diff.name === null ? head.name : diff.name.after,
    collaboration_sequence: sequence,
    document: {
      ...head.document,
      nodes: applyEntityChanges(head.document.nodes, diff.nodes),
      edges: applyEntityChanges(head.document.edges, diff.edges),
      origins: applyEntityChanges(head.document.origins, diff.origins),
      presentation: {
        viewers: applyEntityChanges(presentation.viewers, diff.viewers),
        links: applyEntityChanges(presentation.links, diff.links),
        bindings: applyEntityChanges(presentation.bindings, diff.bindings),
        annotations: applyEntityChanges(
          presentation.annotations,
          diff.annotations,
        ),
      },
    },
  };
}

/** JSON with object keys in sorted order, so key order cannot differ. */
function stableStringify(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableStringify(item)).join(",")}]`;
  }
  if (typeof value === "object" && value !== null) {
    const members = Object.entries(value as Record<string, unknown>)
      // JSON.stringify drops an object member whose value is undefined.
      .filter(([, item]) => item !== undefined)
      .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
      .map(([key, item]) => `${JSON.stringify(key)}:${stableStringify(item)}`);
    return `{${members.join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

/** Equality of canonical JSON: same values regardless of object key order. */
export function sameCanonicalJson(left: unknown, right: unknown): boolean {
  return stableStringify(left) === stableStringify(right);
}
