import type { Edge } from "@xyflow/react";

import type {
  AgentDraftProgress,
  ArtifactConversionInput,
  ArtifactConversionPathInput,
  ArtifactTypeKey,
  ImageUploadItem,
  InputPlugInput,
  NodeSpec,
  Port,
  RunEdgeCollectionMode,
  RunEdgeProjectionInput,
  RunNodeInput,
  RunNodeResult,
  SavedGraphEdge,
  SavedGraphNode,
} from "@/lib/api";
import {
  initialInputPlugs,
  type WorkflowInputPlug,
  type WorkflowInputPlugBinding,
} from "./input-plugs";
import type { WorkflowNodeLayout } from "./node-layout";
import {
  ARTIFACT_QUERY_OPERATOR_ID,
  ARTIFACT_QUERY_RELATIONS_PORT,
  createArtifactQueryRelation,
  reconcileArtifactQueryRelationInputPlugs,
  type ArtifactQueryRelation,
} from "./query-artifact-tables";
import type { SchemaBuilderField } from "./schema-builder";
import type { WorkflowNodeSecretStatuses } from "./node-secrets";

export type { WorkflowInputPlug, WorkflowInputPlugBinding } from "./input-plugs";
export type { WorkflowNodeLayout } from "./node-layout";

export type WorkflowEdgeProjection = RunEdgeProjectionInput;
export type WorkflowEdgeConversion = ArtifactConversionInput;
export type WorkflowEdgeConversionPath = readonly WorkflowEdgeConversion[];

export interface WorkflowEdgeRoute {
  projection?: WorkflowEdgeProjection;
  conversionPath: WorkflowEdgeConversionPath;
}

export interface WorkflowEdgeRouteOption extends WorkflowEdgeRoute {
  projectionTitle?: string;
  conversionTitles: readonly string[];
}

export interface WorkflowEdgeRouteOffset {
  x: number;
  y: number;
}

export interface WorkflowEdgeUpdate {
  enabled?: boolean;
  collectionMode?: RunEdgeCollectionMode;
  route?: WorkflowEdgeRoute;
}

export interface WorkflowEdgeData extends Record<string, unknown> {
  enabled: boolean;
  collectionMode: RunEdgeCollectionMode;
  projection?: WorkflowEdgeProjection;
  conversionPath?: WorkflowEdgeConversionPath;
  /** Visual routing adjustment from the edge's natural midpoint. */
  routeOffset?: WorkflowEdgeRouteOffset;
  /** Persisted endpoint names remain authoritative when a live port is unavailable. */
  sourcePortName?: string;
  targetPortName?: string;
  targetPlugId?: string | null;
  /** Exact API transport retained for a lossless compatibility round trip. */
  persistedEdge?: SavedGraphEdge;
  /** Registry compatibility failures disable editing and in-scope execution. */
  compatibilityIssues?: readonly string[];
  conversionTitles?: readonly string[];
  routeOptions?: readonly WorkflowEdgeRouteOption[];
  allowedCollectionModes?: readonly RunEdgeCollectionMode[];
  onUpdate?: (edgeId: string, update: WorkflowEdgeUpdate) => void;
  onRouteOffsetChange?: (
    edgeId: string,
    offset: WorkflowEdgeRouteOffset,
  ) => void;
}

export type WorkflowEdge = Edge<WorkflowEdgeData>;

export interface WorkflowEdgeTransport {
  collection_mode: RunEdgeCollectionMode;
  projection: RunEdgeProjectionInput | null;
  conversion_path: ArtifactConversionPathInput;
}

export function serializeWorkflowEdgeTransport(
  data: WorkflowEdgeData | undefined,
): WorkflowEdgeTransport {
  return {
    collection_mode: data?.collectionMode ?? "direct",
    projection: data?.projection
      ? { path: [...data.projection.path] }
      : null,
    conversion_path: (data?.conversionPath ?? []).map((conversion) => ({
      id: conversion.id,
      version: conversion.version,
    })),
  };
}

/** Connect-time feed intent on output catalog satellite handles. */
export type HandleFeedIntent =
  | { kind: "whole" }
  | { kind: "projection"; path: readonly string[] };

interface PortMetaBase {
  portName: string;
  shape: Port["shape"];
  direction: "input" | "output";
  plugId?: string;
  /** Connect-time only; catalog satellites. Never persisted on saved edges. */
  feed?: HandleFeedIntent;
}

/** Metadata encoded into React Flow handle ids for typed connections. */
export type PortMeta = PortMetaBase &
  (
    | {
        artifactTypeId: string;
        schemaVersion: number;
        artifactTypeVariable?: never;
      }
    | {
        artifactTypeId?: never;
        schemaVersion?: never;
        artifactTypeVariable: string;
      }
  );

export type WorkflowArtifactTypeBindings = Readonly<
  Record<string, ArtifactTypeKey>
>;

export interface WorkflowArtifactTypeBindingInput {
  variable: string;
  artifact_type: ArtifactTypeKey;
}

export type WorkflowNodeConfig = Record<string, unknown> & {
  uploads?: ImageUploadItem[];
};

export type NodeExecutionStatus =
  | "idle"
  | "uploading"
  | "queued"
  | "running"
  | "cancelling"
  | "cancelled"
  | "succeeded"
  | "failed"
  | "skipped";

export interface NodeExecution {
  status: NodeExecutionStatus;
  error?: string;
}

export interface WorkflowNodeProgressEntry {
  sequence: number;
  message: string;
  current: number | null;
  total: number | null;
  sourceNodePath: readonly string[];
  invocationIndex: number | null;
  invocationPath: readonly number[];
}

export interface WorkflowNodeProgress {
  entries: readonly WorkflowNodeProgressEntry[];
  omittedCount: number;
}

export interface WorkflowNodeHistoryContext {
  workspaceId: string;
  graphId: string | null;
  isDirty: boolean;
}

/** Durable authoring state fetched separately from the saved graph document. */
export type GeneratedNodeDraftSummary = AgentDraftProgress & {
  pendingAction?: "approving" | "publishing" | null;
};

export interface WorkflowCompatibilityEndpoint {
  portName: string;
  plugId?: string;
}

export type WorkflowNodeCompatibility =
  | {
      status: "supported";
    }
  | {
      status: "unsupported" | "invalid";
      issues: readonly string[];
      inputs: readonly WorkflowCompatibilityEndpoint[];
      outputs: readonly WorkflowCompatibilityEndpoint[];
      /** Exact API transport retained while the live contract is unavailable. */
      persistedNode: SavedGraphNode;
    };

export interface WorkflowNodeData extends Record<string, unknown> {
  spec: NodeSpec;
  compatibility: WorkflowNodeCompatibility;
  /** Persisted concrete choices for artifact type variables declared by ports. */
  artifactTypeBindings: WorkflowArtifactTypeBindings;
  /** Ordered, serializable input instances. Their ids remain stable on reorder. */
  inputPlugs: readonly WorkflowInputPlug[];
  /** Edge- and result-derived display data; never persisted. */
  inputPlugBindings: Readonly<Record<string, WorkflowInputPlugBinding>>;
  /** Derived from incoming map edges; never persisted as node configuration. */
  mappedInputPort: string | null;
  /** Server-reported write-only state; never persisted with the graph. */
  secretStatuses: WorkflowNodeSecretStatuses;
  /** Per-input match against its saved operator and declared config dependencies. */
  secretInputReadiness: Readonly<Record<string, boolean>>;
  /** Derived lifecycle scope for clearing unapplied write-only input values. */
  secretInputScope: string;
  config: WorkflowNodeConfig;
  /** Canvas chrome sizes; persisted with the saved graph, not with run transport. */
  layout: WorkflowNodeLayout | null;
  run: RunNodeResult | null;
  execution: NodeExecution;
  /** Bounded, ephemeral live telemetry; never serialized with the graph. */
  progress: WorkflowNodeProgress | null;
  /** Saved-graph identity and authoring state; never serialized with the graph. */
  historyContext: WorkflowNodeHistoryContext | null;
  /** Agent-authored definition state; never serialized with the graph. */
  generation?: GeneratedNodeDraftSummary | null;
  /** Ephemeral collaborator selection tint; never persisted. */
  remoteSelectionColor?: string | null;
  onImagesSelected?: (nodeId: string, files: File[]) => void;
  onConfigChange?: (nodeId: string, name: string, value: unknown) => void;
  onLayoutChange?: (nodeId: string, layout: WorkflowNodeLayout | null) => void;
  onRemoveNode?: (nodeId: string) => void;
  onRemoveImageUpload?: (nodeId: string, index: number) => void;
  onAddInputPlug?: (nodeId: string, portName: string) => void;
  onRemoveInputPlug?: (nodeId: string, plugId: string) => void;
  onReorderInputPlug?: (
    nodeId: string,
    portName: string,
    plugId: string,
    toIndex: number,
  ) => void;
  onSchemaBuilderFieldsChange?: (
    nodeId: string,
    fields: readonly SchemaBuilderField[],
    inputPlugs: readonly WorkflowInputPlug[],
  ) => void;
  onArtifactQueryRelationsChange?: (
    nodeId: string,
    relations: readonly ArtifactQueryRelation[],
    inputPlugs: readonly WorkflowInputPlug[],
  ) => void;
  onApplyNodeSecret?: (
    nodeId: string,
    name: string,
    value: string,
  ) => Promise<boolean>;
  onRemoveNodeSecret?: (
    nodeId: string,
    name: string,
  ) => Promise<boolean>;
  onResetArtifactTypeBinding?: (nodeId: string, variable: string) => void;
  onHandlesMeasured?: (
    nodeId: string,
    artifactTypeBindings: WorkflowArtifactTypeBindings,
  ) => void;
  onOpenModuleSource?: (graphId: string) => void;
  /** When set, the pinned Module call can upgrade to this library release. */
  moduleUpgradeRelease?: number | null;
  onUpgradeModuleCall?: (nodeId: string) => void;
  onOpenExecutionHistory?: (nodeId: string, executionId?: string) => void;
  onReviewGeneratedNode?: (
    nodeId: string,
    draft: GeneratedNodeDraftSummary,
  ) => void;
  onIterateGeneratedNode?: (
    nodeId: string,
    draft: GeneratedNodeDraftSummary,
  ) => void;
}

export const WORKFLOW_NODE_TYPE = "grafyWorkflowNode";
export const WORKFLOW_EDGE_TYPE = "grafyWorkflowEdge";
export const IMAGE_UPLOAD_OPERATOR_ID = "image.upload";
export const TABLE_FILE_IMPORT_OPERATOR_ID = "table.file.import";
export const GEOJSON_UPLOAD_OPERATOR_ID = "gis.geojson.upload";
export const GEOTIFF_UPLOAD_OPERATOR_ID = "gis.geotiff.upload";
export const GIS_COMPOSE_MAP_OPERATOR_ID = "gis.map.compose";
export const GIS_VECTOR_LAYER_OPERATOR_ID = "gis.map.vector_layer";

export function workflowNodeIsSupported(data: WorkflowNodeData): boolean {
  return data.compatibility.status === "supported";
}

export function workflowNodeIsRunnable(data: WorkflowNodeData): boolean {
  return workflowNodeIsSupported(data) &&
    data.spec.agent_authoring?.runnable !== false;
}

export function compatibilityHandleId(
  direction: "input" | "output",
  endpoint: WorkflowCompatibilityEndpoint,
): string {
  const plugId = endpoint.plugId
    ? encodeURIComponent(endpoint.plugId)
    : "";
  return [
    "$compatibility",
    direction,
    encodeURIComponent(endpoint.portName),
    plugId,
  ].join("::");
}

export function isFileUploadOperator(operatorId: string): boolean {
  return operatorId === IMAGE_UPLOAD_OPERATOR_ID ||
    operatorId === TABLE_FILE_IMPORT_OPERATOR_ID ||
    operatorId === GEOJSON_UPLOAD_OPERATOR_ID ||
    operatorId === GEOTIFF_UPLOAD_OPERATOR_ID;
}

export function defaultNodeLayout(spec: NodeSpec): WorkflowNodeLayout | null {
  return spec.operator_id === GIS_COMPOSE_MAP_OPERATOR_ID
    ? { width: 620, appendixHeight: 420 }
    : null;
}

function schemaRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

export function defaultNodeConfig(
  spec: NodeSpec,
): WorkflowNodeConfig {
  const schema = schemaRecord(spec.config_schema);
  const properties = schemaRecord(schema?.properties);
  const config: WorkflowNodeConfig = {};

  if (properties) {
    for (const [name, propertyValue] of Object.entries(properties)) {
      const property = schemaRecord(propertyValue);
      if (property && "default" in property) {
        config[name] = property.default;
      }
    }
  }

  if (isFileUploadOperator(spec.operator_id)) {
    config.uploads = [];
  }
  return config;
}

export function createWorkflowNodeData(
  spec: NodeSpec,
  savedInputPlugs?: readonly InputPlugInput[],
): WorkflowNodeData {
  let inputPlugs = savedInputPlugs
    ? savedInputPlugs.map((plug) => ({
        id: plug.id,
        portName: plug.port,
      }))
    : initialInputPlugs(spec);
  const config = defaultNodeConfig(spec);
  if (
    !savedInputPlugs &&
    spec.operator_id === ARTIFACT_QUERY_OPERATOR_ID
  ) {
    const relationPlug = inputPlugs.find(
      (plug) => plug.portName === ARTIFACT_QUERY_RELATIONS_PORT,
    );
    const relation = relationPlug
      ? createArtifactQueryRelation(0, relationPlug.id)
      : createArtifactQueryRelation(0);
    config.relations = [relation];
    inputPlugs = reconcileArtifactQueryRelationInputPlugs(
      inputPlugs,
      [relation],
    );
  }
  return {
    spec,
    compatibility: { status: "supported" },
    artifactTypeBindings: {},
    inputPlugs,
    inputPlugBindings: {},
    mappedInputPort: null,
    secretStatuses: {},
    secretInputReadiness: {},
    secretInputScope: "unsaved:none",
    config,
    layout: defaultNodeLayout(spec),
    run: null,
    execution: { status: "idle" },
    progress: null,
    historyContext: null,
    generation: null,
  };
}

export function serializeRunNode(
  id: string,
  data: WorkflowNodeData,
  activeInputPlugIds?: ReadonlySet<string>,
): RunNodeInput {
  if (!workflowNodeIsRunnable(data)) {
    throw new Error(
      `Cannot serialize unavailable node ${id} (${data.spec.operator_id}@${data.spec.operator_version}) for execution`,
    );
  }
  const inputPlugs = serializeInputPlugs(data);
  return {
    id,
    operator_id: data.spec.operator_id,
    operator_version: data.spec.operator_version,
    config: data.config,
    input_plugs: activeInputPlugIds
      ? inputPlugs.filter((plug) => activeInputPlugIds.has(plug.id))
      : inputPlugs,
    artifact_type_bindings: serializeArtifactTypeBindings(data),
  };
}

export function serializeInputPlugs(
  data: WorkflowNodeData,
): InputPlugInput[] {
  return data.inputPlugs.map((plug) => ({
    id: plug.id,
    port: plug.portName,
  }));
}

export function serializeArtifactTypeBindings(
  data: WorkflowNodeData,
): WorkflowArtifactTypeBindingInput[] {
  return Object.entries(data.artifactTypeBindings)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([variable, artifactType]) => ({
      variable,
      artifact_type: {
        id: artifactType.id,
        schema_version: artifactType.schema_version,
      },
    }));
}

export function declaredArtifactTypeVariables(
  spec: NodeSpec,
): readonly string[] {
  return [
    ...new Set(
      [...spec.inputs, ...spec.outputs].flatMap((port) => {
        const variable = portArtifactTypeVariable(port);
        return variable ? [variable] : [];
      }),
    ),
  ];
}

export function resetArtifactTypeBinding(
  data: WorkflowNodeData,
  variable: string,
  hasIncidentEdges: boolean,
): WorkflowNodeData {
  if (hasIncidentEdges || !(variable in data.artifactTypeBindings)) {
    return data;
  }

  const bindings = { ...data.artifactTypeBindings };
  delete bindings[variable];
  return {
    ...data,
    artifactTypeBindings: bindings,
    run: null,
    execution: { status: "idle" },
    progress: null,
  };
}

export function bindArtifactTypeVariable(
  data: WorkflowNodeData,
  variable: string,
  artifactType: ArtifactTypeKey,
): WorkflowNodeData {
  if (!declaredArtifactTypeVariables(data.spec).includes(variable)) {
    throw new Error(
      `Cannot bind artifact type variable ${variable}: it is not declared by ${data.spec.operator_id}@${data.spec.operator_version}`,
    );
  }
  return {
    ...data,
    artifactTypeBindings: {
      ...data.artifactTypeBindings,
      [variable]: {
        id: artifactType.id,
        schema_version: artifactType.schema_version,
      },
    },
  };
}

export function imageUploads(data: WorkflowNodeData): ImageUploadItem[] {
  return Array.isArray(data.config.uploads) ? data.config.uploads : [];
}

export function replaceImageUploads(
  data: WorkflowNodeData,
  uploads: readonly ImageUploadItem[],
): WorkflowNodeData {
  return {
    ...data,
    config: {
      ...data.config,
      uploads: [...uploads],
    },
  };
}

export function removeImageUpload(
  data: WorkflowNodeData,
  index: number,
): WorkflowNodeData {
  return {
    ...data,
    config: {
      ...data.config,
      uploads: imageUploads(data).filter(
        (_, itemIndex) => itemIndex !== index,
      ),
    },
  };
}

export function updateNodeRun(
  data: WorkflowNodeData,
  run: RunNodeResult | null,
): WorkflowNodeData {
  return {
    ...data,
    run,
    execution: run
      ? { status: run.status, error: run.error ?? undefined }
      : data.execution,
  };
}

interface WorkflowNodeState {
  id: string;
  data: WorkflowNodeData;
}

interface WorkflowConnectionState {
  source: string;
  target: string;
  data?: {
    enabled?: boolean;
  };
}

export function invalidateWorkflowNodeRuns<NodeType extends WorkflowNodeState>(
  nodes: readonly NodeType[],
  edges: readonly WorkflowConnectionState[],
  changedTargetNodeIds: readonly string[],
): NodeType[] {
  const invalidatedNodeIds = new Set(changedTargetNodeIds);
  const pendingNodeIds = [...invalidatedNodeIds];

  while (pendingNodeIds.length) {
    const sourceNodeId = pendingNodeIds.shift();
    if (sourceNodeId === undefined) continue;
    for (const edge of edges) {
      if (
        edge.data?.enabled === false ||
        edge.source !== sourceNodeId ||
        invalidatedNodeIds.has(edge.target)
      ) {
        continue;
      }
      invalidatedNodeIds.add(edge.target);
      pendingNodeIds.push(edge.target);
    }
  }

  return nodes.map((node) => {
    if (!invalidatedNodeIds.has(node.id)) return node;
    return {
      ...node,
      data: {
        ...node.data,
        run: null,
        execution: { status: "idle" },
        progress: null,
      },
    };
  });
}

export function effectivePortShape(
  data: WorkflowNodeData,
  port: Port,
): Port["shape"] {
  if (!data.mappedInputPort) return port.shape;
  if (port.direction === "output") return "many";
  return data.mappedInputPort === port.name ? "many" : port.shape;
}

export function portMetaForPort(
  port: Port,
  shape: Port["shape"] = port.shape,
  plugId?: string,
  artifactTypeBindings: WorkflowArtifactTypeBindings = {},
): PortMeta {
  const artifactType = resolvedPortArtifactType(port, artifactTypeBindings);
  const base = {
    portName: port.name,
    shape,
    direction: port.direction,
    ...(plugId ? { plugId } : {}),
  };
  if (artifactType) {
    return {
      ...base,
      artifactTypeId: artifactType.id,
      schemaVersion: artifactType.schema_version,
    };
  }

  const variable = portArtifactTypeVariable(port);
  if (!variable) {
    throw new Error(
      `Cannot encode port ${port.name}: it has no artifact type or artifact type variable`,
    );
  }
  return {
    ...base,
    artifactTypeVariable: variable,
  };
}

export function portArtifactType(port: Port): ArtifactTypeKey | null {
  return port.artifact_type ?? null;
}

export function portArtifactTypeVariable(port: Port): string | null {
  return port.artifact_type_variable ?? null;
}

export function resolvedPortArtifactType(
  port: Port,
  artifactTypeBindings: WorkflowArtifactTypeBindings = {},
): ArtifactTypeKey | null {
  const artifactType = portArtifactType(port);
  if (artifactType) return artifactType;

  const variable = portArtifactTypeVariable(port);
  return variable ? artifactTypeBindings[variable] ?? null : null;
}

export function acceptedPortShapes(port: Port): readonly Port["shape"][] {
  return port.accepted_shapes?.length ? port.accepted_shapes : [port.shape];
}

export function portHasInstancePlugs(port: Port): boolean {
  return port.direction === "input" && port.instance_plugs === true;
}

export function portTypeLabel(
  port: Port,
  artifactTypeBindings: WorkflowArtifactTypeBindings = {},
): string {
  const artifactType = resolvedPortArtifactType(port, artifactTypeBindings);
  return artifactType
    ? `${artifactType.id}@${artifactType.schema_version}`
    : "Any artifact";
}

export function portSummary(port: Port): string {
  const extras = [port.shape, port.variadic ? "variadic" : null].filter(
    Boolean,
  );

  return `${portTypeLabel(port)}${
    extras.length ? ` · ${extras.join(" · ")}` : ""
  }`;
}

export function portCountLabel(spec: NodeSpec): string {
  return `${spec.inputs.length} in · ${spec.outputs.length} out`;
}

export function groupLabel(group: string): string {
  return group.charAt(0).toUpperCase() + group.slice(1);
}

export function imageUploadSizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} kB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
