import type { Edge, Node } from "@xyflow/react";

import type { CollaborativeHead, SavedGraphDocument } from "@/lib/api";

import {
  annotationsFromPresentation,
  serializeAnnotations,
  type AnnotationNode,
} from "./annotations";
import {
  hydrateNodeLayout,
  serializeNodeLayout,
  type WorkflowNodeLayout,
} from "./node-layout";
import {
  WORKFLOW_NODE_TYPE,
  type WorkflowEdge,
  type WorkflowEdgeProjection,
  type WorkflowEdgeRouteOffset,
  type WorkflowEdgeRouteOption,
  type WorkflowNodeData,
} from "./types";
import type {
  ArtifactInteractionField,
  ArtifactKeySelection,
  ArtifactViewerActivity,
  ArtifactViewerBinding,
  ArtifactViewerIncomingBinding,
} from "./artifact-interactions";

export type GraphPresentation = NonNullable<
  SavedGraphDocument["presentation"]
>;

export const ARTIFACT_VIEWER_NODE_TYPE = "grafyArtifactViewerNode";
export const ARTIFACT_VIEWER_EDGE_TYPE = "grafyArtifactViewerEdge";
export const ARTIFACT_VIEWER_INTERACTION_EDGE_TYPE =
  "grafyArtifactViewerInteractionEdge";
export const ARTIFACT_VIEWER_INPUT_HANDLE = "artifact-viewer-input";
export const ARTIFACT_VIEWER_INTERACTION_INPUT_HANDLE =
  "artifact-viewer-interaction-input";
export const ARTIFACT_VIEWER_INTERACTION_OUTPUT_HANDLE =
  "artifact-viewer-interaction-output";

export interface ArtifactViewerNodeData extends Record<string, unknown> {
  layout: WorkflowNodeLayout | null;
  mode: string | null;
  outgoingFields?: string[];
  selection?: ArtifactKeySelection;
  incomingBindings?: ArtifactViewerIncomingBinding[];
  fields?: ArtifactInteractionField[];
  onLayoutChange?: (
    nodeId: string,
    layout: WorkflowNodeLayout | null,
  ) => void;
  onModeChange?: (nodeId: string, mode: string) => void;
  onSelectionChange?: (
    nodeId: string,
    selection: ArtifactKeySelection,
  ) => void;
  onFieldsChange?: (
    nodeId: string,
    fields: ArtifactInteractionField[],
  ) => void;
  onActivityChange?: (
    nodeId: string,
    activity: ArtifactViewerActivity | null,
  ) => void;
  onRemoveNode?: (nodeId: string) => void;
  /** Ephemeral collaborator selection tint; never persisted. */
  remoteSelectionColor?: string | null;
}

export type ArtifactViewerNode = Node<
  ArtifactViewerNodeData,
  typeof ARTIFACT_VIEWER_NODE_TYPE
>;

export interface ArtifactViewerEdgeUpdate {
  projection?: WorkflowEdgeProjection | null;
}

export interface ArtifactViewerEdgeData extends Record<string, unknown> {
  sourcePortName: string;
  projection?: WorkflowEdgeProjection;
  projectionTitle?: string;
  routeOffset?: WorkflowEdgeRouteOffset;
  routeOptions?: readonly WorkflowEdgeRouteOption[];
  onUpdate?: (edgeId: string, update: ArtifactViewerEdgeUpdate) => void;
  onRouteOffsetChange?: (
    edgeId: string,
    offset: WorkflowEdgeRouteOffset,
  ) => void;
}

export type ArtifactViewerEdge = Edge<
  ArtifactViewerEdgeData,
  typeof ARTIFACT_VIEWER_EDGE_TYPE
>;

export interface ArtifactViewerInteractionEdgeData
  extends Record<string, unknown> {
  binding: ArtifactViewerBinding;
  sourceFields?: ArtifactInteractionField[];
  targetFields?: ArtifactInteractionField[];
  onBindingChange?: (
    bindingId: string,
    binding: ArtifactViewerBinding,
  ) => void;
}

export type ArtifactViewerInteractionEdge = Edge<
  ArtifactViewerInteractionEdgeData,
  typeof ARTIFACT_VIEWER_INTERACTION_EDGE_TYPE
>;

export type CanvasWorkflowNode = Node<
  WorkflowNodeData,
  typeof WORKFLOW_NODE_TYPE
>;
export type CanvasNode =
  | CanvasWorkflowNode
  | ArtifactViewerNode
  | AnnotationNode;
export type CanvasEdge =
  | WorkflowEdge
  | ArtifactViewerEdge
  | ArtifactViewerInteractionEdge;

export interface ArtifactViewerCanvasState {
  graphId: string | null;
  nodes: ArtifactViewerNode[];
  edges: ArtifactViewerEdge[];
  bindings: ArtifactViewerBinding[];
  annotations: AnnotationNode[];
}

export function emptyGraphPresentation(): GraphPresentation {
  return { viewers: [], links: [], bindings: [], annotations: [] };
}

export function presentationFromArtifactViewers(
  state: Pick<
    ArtifactViewerCanvasState,
    "nodes" | "edges" | "bindings" | "annotations"
  >,
): GraphPresentation {
  return {
    viewers: state.nodes.map((node) => ({
      id: node.id,
      position: { x: node.position.x, y: node.position.y },
      layout: serializeNodeLayout(node.data.layout),
      mode: node.data.mode,
    })),
    links: state.edges.map((edge) => ({
      id: edge.id,
      source_node_id: edge.source,
      source_port_name: edge.data?.sourcePortName ?? "",
      target_viewer_id: edge.target,
      projection: edge.data?.projection
        ? { path: [...edge.data.projection.path] }
        : null,
      route_offset: edge.data?.routeOffset
        ? { x: edge.data.routeOffset.x, y: edge.data.routeOffset.y }
        : null,
    })),
    bindings: state.bindings.map((binding) => ({
      id: binding.id,
      source_viewer_id: binding.sourceViewerId,
      target_viewer_id: binding.targetViewerId,
      mappings: binding.mappings.flatMap((mapping) => {
        const sourceField = mapping.sourceField.trim();
        const targetField = mapping.targetField.trim();
        if (!sourceField || !targetField) return [];
        return [{ source_field: sourceField, target_field: targetField }];
      }),
      effects: [...binding.effects],
      empty_selection: binding.emptySelection,
    })),
    annotations: serializeAnnotations(state.annotations),
  };
}

export function artifactViewersFromPresentation(
  graphId: string,
  presentation: GraphPresentation | null | undefined,
): ArtifactViewerCanvasState {
  const viewers = presentation?.viewers ?? [];
  const nodes: ArtifactViewerNode[] = [];
  const nodeIds = new Set<string>();
  for (const viewer of viewers) {
    if (!viewer.id || nodeIds.has(viewer.id)) continue;
    const x = viewer.position?.x;
    const y = viewer.position?.y;
    if (
      typeof x !== "number" ||
      !Number.isFinite(x) ||
      typeof y !== "number" ||
      !Number.isFinite(y)
    ) {
      continue;
    }
    nodeIds.add(viewer.id);
    nodes.push({
      id: viewer.id,
      type: ARTIFACT_VIEWER_NODE_TYPE,
      position: { x, y },
      data: {
        layout: hydrateNodeLayout(viewer.layout ?? null),
        mode: viewer.mode ?? null,
      },
    });
  }

  const edges: ArtifactViewerEdge[] = [];
  const edgeIds = new Set<string>();
  const connectedViewerIds = new Set<string>();
  for (const link of presentation?.links ?? []) {
    if (
      !link.id ||
      edgeIds.has(link.id) ||
      !link.source_node_id ||
      !link.source_port_name ||
      !nodeIds.has(link.target_viewer_id) ||
      connectedViewerIds.has(link.target_viewer_id)
    ) {
      continue;
    }
    edgeIds.add(link.id);
    connectedViewerIds.add(link.target_viewer_id);
    const projectionPath = link.projection?.path;
    const routeOffset = link.route_offset;
    edges.push({
      id: link.id,
      type: ARTIFACT_VIEWER_EDGE_TYPE,
      source: link.source_node_id,
      target: link.target_viewer_id,
      targetHandle: ARTIFACT_VIEWER_INPUT_HANDLE,
      data: {
        sourcePortName: link.source_port_name,
        ...(projectionPath?.length
          ? { projection: { path: [...projectionPath] } }
          : {}),
        ...(routeOffset &&
        typeof routeOffset.x === "number" &&
        typeof routeOffset.y === "number"
          ? { routeOffset: { x: routeOffset.x, y: routeOffset.y } }
          : {}),
      },
    });
  }

  const bindings: ArtifactViewerBinding[] = [];
  const bindingIds = new Set<string>();
  for (const binding of presentation?.bindings ?? []) {
    if (
      !binding.id ||
      bindingIds.has(binding.id) ||
      !nodeIds.has(binding.source_viewer_id) ||
      !nodeIds.has(binding.target_viewer_id) ||
      binding.source_viewer_id === binding.target_viewer_id
    ) {
      continue;
    }
    const mappings = (binding.mappings ?? []).flatMap((mapping) =>
      mapping.source_field && mapping.target_field
        ? [{
            sourceField: mapping.source_field,
            targetField: mapping.target_field,
          }]
        : [],
    );
    const effects = [...new Set(binding.effects ?? [])].filter(
      (effect): effect is ArtifactViewerBinding["effects"][number] =>
        effect === "filter" ||
        effect === "highlight" ||
        effect === "focus",
    );
    if (effects.length === 0) continue;
    bindingIds.add(binding.id);
    bindings.push({
      id: binding.id,
      sourceViewerId: binding.source_viewer_id,
      targetViewerId: binding.target_viewer_id,
      mappings,
      effects,
      emptySelection: binding.empty_selection ?? "show_all",
    });
  }

  const annotations = annotationsFromPresentation(presentation);

  return { graphId, nodes, edges, bindings, annotations };
}

export function presentationFromCollaborativeHead(
  head: Pick<CollaborativeHead, "document">,
): GraphPresentation {
  const presentation = head.document.presentation;
  if (!presentation) return emptyGraphPresentation();
  return {
    viewers: [...(presentation.viewers ?? [])],
    links: [...(presentation.links ?? [])],
    bindings: [...(presentation.bindings ?? [])],
    annotations: [...(presentation.annotations ?? [])],
  };
}
