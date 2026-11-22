/**
 * The vocabulary the cell adapters share: the grid bounds every card kind may
 * be sized to, plus the pure lookups more than one of them needs.
 *
 * This module is a leaf. It never imports an adapter, so `cell-operator-adapter`,
 * `cell-artifact-adapter` and `cell-pipe-adapter` can each depend on it without
 * closing a cycle, and `cell-document-adapter` stays the only module that knows
 * all of them.
 */
import type { ArtifactTypeKey, NodeRegistry, Port } from "@/lib/api";

import {
  ARTIFACT_CARD_HEIGHT_MAX,
  ARTIFACT_CARD_HEIGHT_MIN,
  ARTIFACT_CARD_WIDTH_MAX,
  ARTIFACT_CARD_WIDTH_MIN,
  DEFAULT_ARTIFACT_CARD_WIDTH,
} from "../artifacts/artifact-card";
import {
  BODY_HEIGHT_MIN,
  LAYOUT_DIMENSION_MAX,
  NODE_WIDTH_MIN,
} from "../authoring/node-layout";
import type { AuthoredGraphNode } from "../authoring/graph-document";

import { CELL_SIZE, type CellCoord } from "./cell-model";

/** Joins a plug's port name and its plug id into one port id. */
export const PLUG_SEPARATOR = "::";

/**
 * A workflow node is never narrower than the API's `GraphNodeLayout` floor:
 * 260px is 10.4 cells, so it takes eleven to clear it.
 */
export const MIN_CARD_WIDTH_CELLS = Math.ceil(NODE_WIDTH_MIN / CELL_SIZE);
/** 1200px: wide enough for two config shelves, and a fraction of the schema ceiling. */
export const MAX_CARD_WIDTH_CELLS = 48;
/** An operator never shrinks below its header and one port row. */
export const MIN_OPERATOR_HEIGHT_CELLS = Math.ceil(BODY_HEIGHT_MIN / CELL_SIZE);
/** Agent cards always render at least 8 cells tall (200px). */
export const MIN_AGENT_HEIGHT_CELLS = 8;
/** Default drag ceiling (2000px) matching the free-resize canvas cap. */
export const DEFAULT_FREE_MAX_CELLS = 80;
/** Schema ceiling in whole cells (`Math.floor(16384 / 25) = 655`). */
export const MAX_SCHEMA_LAYOUT_CELLS = Math.floor(
  LAYOUT_DIMENSION_MAX / CELL_SIZE,
);
/** 1500px of port rows, config shelves and appendix: a node at its tallest useful. */
export const MAX_CARD_HEIGHT_CELLS = 60;
/** Annotation floors a note stays readable at; the ceiling is a node's. */
export const MIN_ANNOTATION_WIDTH_CELLS = 6;
export const MIN_ANNOTATION_HEIGHT_CELLS = 4;
/** Artifact card bounds derived directly from the shared pixel floor/ceiling (6×3..48×48 cells). */
export const MIN_ARTIFACT_WIDTH_CELLS = Math.ceil(
  ARTIFACT_CARD_WIDTH_MIN / CELL_SIZE,
);
export const MAX_ARTIFACT_WIDTH_CELLS = Math.floor(
  ARTIFACT_CARD_WIDTH_MAX / CELL_SIZE,
);
export const MIN_ARTIFACT_HEIGHT_CELLS = Math.ceil(
  ARTIFACT_CARD_HEIGHT_MIN / CELL_SIZE,
);
export const MAX_ARTIFACT_HEIGHT_CELLS = Math.floor(
  ARTIFACT_CARD_HEIGHT_MAX / CELL_SIZE,
);
/** Default height for unsized artifact cards when natural dimensions are unknown. */
export const DEFAULT_ARTIFACT_HEIGHT_CELLS = 6;
/** Tall unsized portraits cap at 350px (14 cells) so they stay thumbnail-sized. */
export const MAX_AUTO_ARTIFACT_HEIGHT_CELLS = 14;
export const DEFAULT_ARTIFACT_WIDTH_CELLS = Math.max(
  MIN_ARTIFACT_WIDTH_CELLS,
  Math.round(DEFAULT_ARTIFACT_CARD_WIDTH / CELL_SIZE),
);

export function snapPixelsToCell(px: number): number {
  const cells = Math.round(px / CELL_SIZE);
  return Object.is(cells, -0) ? 0 : cells;
}

export function cellOriginFromWorld(pos: { x: number; y: number }): CellCoord {
  return { col: snapPixelsToCell(pos.x), row: snapPixelsToCell(pos.y) };
}

export function targetPortId(
  port: string,
  plug: string | null | undefined,
): string {
  return plug ? `${port}${PLUG_SEPARATOR}${plug}` : port;
}

/** The catalogued spec a node was placed from, falling back to its operator id. */
export function nodeSpec(node: AuthoredGraphNode, registry: NodeRegistry) {
  return (
    registry.nodes.find(
      (spec) =>
        spec.operator_id === node.operator_id &&
        spec.operator_version === node.operator_version,
    ) ?? registry.nodes.find((spec) => spec.operator_id === node.operator_id)
  );
}

/** The artifact type a port carries once the node's variable bindings resolve. */
export function portArtifactType(
  node: AuthoredGraphNode,
  port: Port | undefined,
) {
  const variable = port?.artifact_type_variable;
  const binding = variable
    ? node.artifact_type_bindings.find(
        (candidate) => candidate.variable === variable,
      )
    : undefined;
  return binding?.artifact_type ?? port?.artifact_type;
}

export function portTypeId(node: AuthoredGraphNode, port: Port): string {
  return (
    portArtifactType(node, port)?.id ??
    port.artifact_type_variable ??
    "artifact"
  );
}

/** The catalogued name of an artifact type, its version appended when it has one. */
export function collectionTypeLabel(
  artifactType: ArtifactTypeKey | null | undefined,
  catalog: NodeRegistry["artifact_types"],
): string {
  if (!artifactType) return "Artifact";
  const { id, schema_version: version } = artifactType;
  const title = catalog
    .find(
      (entry) => entry.key.id === id && entry.key.schema_version === version,
    )
    ?.title.trim();
  if (!title) return `${id}@${version}`;
  return version > 1 ? `${title} · v${version}` : title;
}
