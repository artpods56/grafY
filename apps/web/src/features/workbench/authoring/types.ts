import type {
  ArtifactConversionInput,
  ArtifactConversionPathInput,
  ArtifactTypeKey,
  InputPlugInput,
  NodeSpec,
  Port,
  RunEdgeCollectionMode,
  RunEdgeProjectionInput,
  RunNodeInput,
  RunNodeResult,
  SavedGraphNode,
  ServiceContractKey,
} from "@/lib/api";
import { initialInputPlugs, type WorkflowInputPlug } from "./input-plugs";
import type { WorkflowNodeLayout } from "./node-layout";
import type { CollectionMember } from "./collection-member";

export type { WorkflowInputPlug } from "./input-plugs";
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

export interface WorkflowEdgeData {
  enabled: boolean;
  collectionMode: RunEdgeCollectionMode;
  projection?: WorkflowEdgeProjection;
  conversionPath?: WorkflowEdgeConversionPath;
  /** Visual routing adjustment from the edge's natural midpoint. */
  routeOffset?: WorkflowEdgeRouteOffset;
  /** Registry compatibility failures disable editing and in-scope execution. */
  compatibilityIssues?: readonly string[];
  conversionTitles?: readonly string[];
  routeOptions?: readonly WorkflowEdgeRouteOption[];
  allowedCollectionModes?: readonly RunEdgeCollectionMode[];
}

export type XYPosition = { x: number; y: number };

/** Structured endpoint pair connecting one workflow node output to one input (or plug). */
export interface GraphConnection {
  readonly source: string;
  readonly sourcePort: string;
  readonly target: string;
  readonly targetPort: string;
  readonly targetPlug?: string | null;
}

export interface CanvasFitViewOptions {
  padding: number;
  maxZoom: number;
  nodes?: readonly { id: string }[];
}

export interface WorkflowNode {
  id: string;
  position: XYPosition;
  data: WorkflowNodeData;
  selected?: boolean;
}

export interface WorkflowEdge {
  id: string;
  source: string;
  sourcePort: string;
  target: string;
  targetPort: string;
  targetPlug?: string | null;
  selected?: boolean;
  data?: WorkflowEdgeData;
}

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
    projection: data?.projection ? { path: [...data.projection.path] } : null,
    conversion_path: (data?.conversionPath ?? []).map((conversion) => ({
      id: conversion.id,
      version: conversion.version,
    })),
  };
}

/** Connect-time feed intent on output catalog satellite handles. */
export type HandleFeedIntent =
  { kind: "whole" } | { kind: "projection"; path: readonly string[] };

interface PortMetaBase {
  portName: string;
  shape: Port["shape"];
  direction: "input" | "output";
  plugId?: string;
  /** Connect-time only; catalog satellites. Never persisted on saved edges. */
  feed?: HandleFeedIntent;
  /** Additional artifact types an input port accepts, after the primary one. */
  alsoAccepts?: readonly ArtifactTypeKey[];
}

/** Structured port metadata used for typed connection routing and discovery. */
export type PortMeta = PortMetaBase &
  (
    | {
        artifactTypeId: string;
        schemaVersion: number;
        artifactTypeVariable?: never;
        serviceContracts?: never;
      }
    | {
        artifactTypeId?: never;
        schemaVersion?: never;
        artifactTypeVariable: string;
        serviceContracts?: never;
      }
    | {
        artifactTypeId?: never;
        schemaVersion?: never;
        artifactTypeVariable?: never;
        serviceContracts: readonly ServiceContractKey[];
      }
  );

export type WorkflowArtifactTypeBindings = Readonly<
  Record<string, ArtifactTypeKey>
>;

export interface WorkflowArtifactTypeBindingInput {
  variable: string;
  artifact_type: ArtifactTypeKey;
}

export type WorkflowNodeConfig = Record<string, unknown>;

export type NodeExecutionStatus =
  | "idle"
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

export interface WorkflowNodeData {
  spec: NodeSpec;
  compatibility: WorkflowNodeCompatibility;
  /** Persisted concrete choices for artifact type variables declared by ports. */
  artifactTypeBindings: WorkflowArtifactTypeBindings;
  /** Ordered, serializable input instances. Their ids remain stable on reorder. */
  inputPlugs: readonly WorkflowInputPlug[];
  /** Derived from incoming map edges/origins; never persisted as node configuration. */
  mappedInputPorts: readonly string[];
  config: WorkflowNodeConfig;
  /** Canvas chrome sizes; persisted with the saved graph, not with run transport. */
  layout: WorkflowNodeLayout | null;
  run: RunNodeResult | null;
  execution: NodeExecution;
  /** Bounded, ephemeral live telemetry; never serialized with the graph. */
  progress: WorkflowNodeProgress | null;
  /** A collection's members in plug order; derived, never persisted. */
  collectionMembers?: readonly CollectionMember[];
}

export const GIS_COMPOSE_MAP_OPERATOR_ID = "gis.map.compose";

export function workflowNodeIsSupported(data: WorkflowNodeData): boolean {
  return data.compatibility.status === "supported";
}

export function resolveInstancePortShapes(
  spec: NodeSpec,
  config: WorkflowNodeConfig,
): NodeSpec {
  if (![...spec.inputs, ...spec.outputs].some((port) => port.shape_field))
    return spec;
  const resolve = (port: Port): Port => {
    const shape = port.shape_field ? config[port.shape_field] : undefined;
    return shape === "one" || shape === "many"
      ? { ...port, shape, accepted_shapes: [shape] }
      : port;
  };
  return {
    ...spec,
    inputs: spec.inputs.map(resolve),
    outputs: spec.outputs.map(resolve),
  };
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

export function defaultNodeConfig(spec: NodeSpec): WorkflowNodeConfig {
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

  return config;
}

export function createWorkflowNodeData(
  spec: NodeSpec,
  savedInputPlugs?: readonly InputPlugInput[],
): WorkflowNodeData {
  const inputPlugs = savedInputPlugs
    ? savedInputPlugs.map((plug) => ({
        id: plug.id,
        portName: plug.port,
      }))
    : initialInputPlugs(spec);
  const config = defaultNodeConfig(spec);
  return {
    spec,
    compatibility: { status: "supported" },
    artifactTypeBindings: {},
    inputPlugs,
    mappedInputPorts: [],
    config,
    layout: defaultNodeLayout(spec),
    run: null,
    execution: { status: "idle" },
    progress: null,
  };
}

export function serializeRunNode(
  id: string,
  data: WorkflowNodeData,
  activeInputPlugIds?: ReadonlySet<string>,
): RunNodeInput {
  if (!workflowNodeIsSupported(data)) {
    throw new Error(
      `Cannot serialize unsupported node ${id} (${data.spec.operator_id}@${data.spec.operator_version}) for execution`,
    );
  }
  const inputPlugs = serializeInputPlugs(data);
  return {
    kind: "builtin",
    id,
    position: { x: 0, y: 0 },
    operator_id: data.spec.operator_id,
    operator_version: data.spec.operator_version,
    config: data.config,
    input_plugs: activeInputPlugIds
      ? inputPlugs.filter((plug) => activeInputPlugIds.has(plug.id))
      : inputPlugs,
    artifact_type_bindings: serializeArtifactTypeBindings(data),
  };
}

export function serializeInputPlugs(data: WorkflowNodeData): InputPlugInput[] {
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

export function effectivePortShape(
  data: WorkflowNodeData,
  port: Port,
): Port["shape"] {
  if (!data.mappedInputPorts.length) return port.shape;
  if (port.direction === "output") {
    return port.kind === "service" ? port.shape : "many";
  }
  return data.mappedInputPorts.includes(port.name) ? "many" : port.shape;
}

export function portIsService(port: Port): boolean {
  return port.kind === "service";
}

/** A provider node: every output is a service port (no stored artifact). */
export function isServiceProviderNode(spec: NodeSpec): boolean {
  return (
    spec.outputs.length > 0 && spec.outputs.every((port) => portIsService(port))
  );
}

export function portMetaForPort(
  port: Port,
  shape: Port["shape"] = port.shape,
  plugId?: string,
  artifactTypeBindings: WorkflowArtifactTypeBindings = {},
): PortMeta {
  const base = {
    portName: port.name,
    shape,
    direction: port.direction,
    ...(plugId ? { plugId } : {}),
  };
  if (portIsService(port)) {
    const serviceContracts = port.service_contracts ?? [];
    if (!serviceContracts.length) {
      throw new Error(
        `Cannot describe service port ${port.name}: it names no service contract`,
      );
    }
    return {
      ...base,
      serviceContracts,
    };
  }

  const artifactType = resolvedPortArtifactType(port, artifactTypeBindings);
  if (artifactType) {
    const alsoAccepts = port.also_accepts ?? [];
    return {
      ...base,
      artifactTypeId: artifactType.id,
      schemaVersion: artifactType.schema_version,
      ...(alsoAccepts.length ? { alsoAccepts } : {}),
    };
  }

  const variable = portArtifactTypeVariable(port);
  if (!variable) {
    throw new Error(
      `Cannot describe port ${port.name}: it has no artifact type or artifact type variable`,
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
  return variable ? (artifactTypeBindings[variable] ?? null) : null;
}

export function acceptedPortShapes(port: Port): readonly Port["shape"][] {
  return port.accepted_shapes?.length ? port.accepted_shapes : [port.shape];
}

export function portHasInstancePlugs(port: Port): boolean {
  return port.direction === "input" && port.instance_plugs === true;
}

/**
 * Collection modes an artifact input may use, the default first. A many-only
 * port takes one artifact by holding it as a sequence of one. A sequence on a
 * port that takes one item maps the node over its items; on a port that takes
 * a sequence it may also be mapped, one sequence of one per item.
 */
export function originCollectionModes(
  port: Port,
  shape: Port["shape"],
): RunEdgeCollectionMode[] {
  const accepted = acceptedPortShapes(port);
  const modes: RunEdgeCollectionMode[] = [];
  if (
    accepted.includes(shape) ||
    (shape === "one" && accepted.includes("many"))
  )
    modes.push("direct");
  if (
    shape === "many" &&
    !port.variadic &&
    !portHasInstancePlugs(port) &&
    (port.shape === "many" || !accepted.includes("many"))
  )
    modes.push("map");
  return modes;
}

/**
 * Collection modes an edge may use from a source of `sourceShape` into
 * `targetPort`, whose effective shape is `targetShape`; the default comes first.
 * A sequence feeding a non-variadic sequence input may be passed whole or
 * mapped, in which case each invocation receives a sequence of one.
 */
export function collectionModesForShapes(
  sourceShape: Port["shape"],
  targetPort: Port,
  targetShape: Port["shape"],
): RunEdgeCollectionMode[] {
  const modes: RunEdgeCollectionMode[] = [];
  const instancePlugs = portHasInstancePlugs(targetPort);
  if (
    acceptedPortShapes(targetPort).includes(sourceShape) ||
    (!instancePlugs && sourceShape === targetShape)
  ) {
    modes.push("direct");
  }
  if (
    sourceShape === "many" &&
    !instancePlugs &&
    ((targetShape === "one" &&
      !acceptedPortShapes(targetPort).includes("many")) ||
      (targetPort.shape === "many" && !targetPort.variadic))
  ) {
    modes.push("map");
  }
  return modes;
}
