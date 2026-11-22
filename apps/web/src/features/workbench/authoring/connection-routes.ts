import type {
  ArtifactConversionInput,
  ArtifactConversionSpec,
  ArtifactTypeKey,
  ArtifactTypeSpec,
  FieldProjection,
  ServiceContractKey,
} from "@/lib/api";

import { artifactTypeKey } from "../artifacts/artifact-type-key";
import { serviceContractKey } from "./service-contract-key";
import type { HandleFeedIntent, PortMeta } from "./types";

export type { HandleFeedIntent };

/** Type guard for a service port's structured endpoint metadata. */
export function isServicePortMeta(
  port: PortMeta,
): port is Extract<
  PortMeta,
  { serviceContracts: readonly ServiceContractKey[] }
> {
  return (
    Array.isArray(port.serviceContracts) && port.serviceContracts.length > 0
  );
}

/** Concrete artifact type carried by a port, or null for unbound generic / service ports. */
export function portMetaArtifactType(port: PortMeta): ArtifactTypeKey | null {
  if (
    typeof port.artifactTypeId !== "string" ||
    typeof port.schemaVersion !== "number"
  ) {
    return null;
  }
  return {
    id: port.artifactTypeId,
    schema_version: port.schemaVersion,
  };
}

/** Every artifact type an input port accepts: its primary type plus `alsoAccepts`. */
export function acceptedPortMetaArtifactTypes(
  port: PortMeta,
): readonly ArtifactTypeKey[] {
  const primary = portMetaArtifactType(port);
  if (!primary) return [];
  const accepted: ArtifactTypeKey[] = [primary];
  const seen = new Set([artifactTypeKey(primary)]);
  for (const extra of port.alsoAccepts ?? []) {
    const key = artifactTypeKey(extra);
    if (seen.has(key)) continue;
    seen.add(key);
    accepted.push(extra);
  }
  return accepted;
}

function serviceContractsOverlap(
  source: readonly ServiceContractKey[],
  target: readonly ServiceContractKey[],
): boolean {
  const targetKeys = new Set(target.map(serviceContractKey));
  return source.some((contract) =>
    targetKeys.has(serviceContractKey(contract)),
  );
}

function portAcceptsArtifactType(
  port: PortMeta,
  artifactType: ArtifactTypeKey,
): boolean {
  return acceptedPortMetaArtifactTypes(port).some(
    (candidate) => artifactTypeKey(candidate) === artifactTypeKey(artifactType),
  );
}

/** Direct (exact-shape, no conversion) compatibility between two structured port endpoints. */
export function portsCanConnect(source: PortMeta, target: PortMeta): boolean {
  if (source.direction !== "output" || target.direction !== "input") {
    return false;
  }
  if (source.shape !== target.shape) return false;

  const sourceService = isServicePortMeta(source);
  const targetService = isServicePortMeta(target);
  if (sourceService || targetService) {
    return (
      sourceService &&
      targetService &&
      serviceContractsOverlap(source.serviceContracts, target.serviceContracts)
    );
  }

  const sourceArtifactType = portMetaArtifactType(source);
  const targetArtifactType = portMetaArtifactType(target);
  if (!sourceArtifactType && !targetArtifactType) return false;
  return (
    !sourceArtifactType ||
    !targetArtifactType ||
    portAcceptsArtifactType(target, sourceArtifactType)
  );
}

export type ConnectionRoute =
  | ({
      kind: "exact";
      conversionPath: readonly ArtifactConversionSpec[];
    } & ConnectionRouteBinding)
  | ({
      kind: "projection";
      projection: FieldProjection;
      conversionPath: readonly ArtifactConversionSpec[];
    } & ConnectionRouteBinding)
  | ({
      kind: "conversion";
      conversionPath: readonly ArtifactConversionSpec[];
    } & ConnectionRouteBinding)
  | ({
      kind: "projection-conversion";
      projection: FieldProjection;
      conversionPath: readonly ArtifactConversionSpec[];
    } & ConnectionRouteBinding);

export interface ConnectionArtifactTypeBinding {
  endpoint: "source" | "target";
  variable: string;
  artifactType: ArtifactTypeKey;
}

interface ConnectionRouteBinding {
  artifactTypeBinding?: ConnectionArtifactTypeBinding;
}

export interface ConnectionRouteSelection {
  projection?: { path: readonly string[] };
  conversionPath: readonly ArtifactConversionInput[];
}

export const MAX_CONVERSION_PATH_LENGTH = 8;
export const MAX_CONVERSION_SEARCH_STATES = 4_096;
export const MAX_CONVERSION_PATH_CANDIDATES = 256;

function artifactTypeMatches(
  artifactType: { id: string; schema_version: number },
  id: string,
  schemaVersion: number,
): boolean {
  return (
    artifactType.id === id && artifactType.schema_version === schemaVersion
  );
}

function compareConversions(
  left: ArtifactConversionSpec,
  right: ArtifactConversionSpec,
): number {
  return (
    left.key.id.localeCompare(right.key.id) ||
    left.key.version - right.key.version
  );
}

function compareConversionPaths(
  left: readonly ArtifactConversionSpec[],
  right: readonly ArtifactConversionSpec[],
): number {
  const length = Math.min(left.length, right.length);
  for (let index = 0; index < length; index += 1) {
    const step = left[index];
    const other = right[index];
    if (!step || !other) break;
    const comparison = compareConversions(step, other);
    if (comparison !== 0) return comparison;
  }
  return left.length - right.length;
}

function shortestConversionPaths(
  source: { id: string; schema_version: number },
  target: { id: string; schema_version: number },
  conversions: readonly ArtifactConversionSpec[],
): ArtifactConversionSpec[][] | null {
  if (artifactTypeKey(source) === artifactTypeKey(target)) return [[]];

  const sortedConversions = [...conversions].sort(compareConversions);
  const conversionsBySource = new Map<string, ArtifactConversionSpec[]>();
  for (const conversion of sortedConversions) {
    const sourceKey = artifactTypeKey(conversion.source_artifact_type);
    const outgoing = conversionsBySource.get(sourceKey) ?? [];
    outgoing.push(conversion);
    conversionsBySource.set(sourceKey, outgoing);
  }
  let expandedStates = 0;
  let frontier: Array<{
    artifactType: { id: string; schema_version: number };
    conversionPath: ArtifactConversionSpec[];
    visitedArtifactTypes: ReadonlySet<string>;
  }> = [
    {
      artifactType: source,
      conversionPath: [],
      visitedArtifactTypes: new Set([artifactTypeKey(source)]),
    },
  ];

  for (let depth = 0; depth < MAX_CONVERSION_PATH_LENGTH; depth += 1) {
    const completed: ArtifactConversionSpec[][] = [];
    const nextFrontier: typeof frontier = [];
    for (const state of frontier) {
      for (const conversion of conversionsBySource.get(
        artifactTypeKey(state.artifactType),
      ) ?? []) {
        const nextArtifactType = conversion.target_artifact_type;
        const nextArtifactTypeKey = artifactTypeKey(nextArtifactType);
        if (state.visitedArtifactTypes.has(nextArtifactTypeKey)) continue;

        const conversionPath = [...state.conversionPath, conversion];
        expandedStates += 1;
        if (expandedStates > MAX_CONVERSION_SEARCH_STATES) return null;
        if (nextArtifactTypeKey === artifactTypeKey(target)) {
          completed.push(conversionPath);
          if (completed.length > MAX_CONVERSION_PATH_CANDIDATES) return null;
          continue;
        }

        nextFrontier.push({
          artifactType: nextArtifactType,
          conversionPath,
          visitedArtifactTypes: new Set([
            ...state.visitedArtifactTypes,
            nextArtifactTypeKey,
          ]),
        });
      }
    }

    if (completed.length) return completed.sort(compareConversionPaths);
    if (!nextFrontier.length) return [];
    frontier = nextFrontier;
  }

  // Reaching the hop bound leaves the registry search incomplete, so no route
  // is advertised instead of guessing that a longer chain is safe.
  return [];
}

export function shortestConversionPathsToAny(
  source: { id: string; schema_version: number },
  targets: readonly { id: string; schema_version: number }[],
  conversions: readonly ArtifactConversionSpec[],
): ArtifactConversionSpec[][] | null {
  const paths: ArtifactConversionSpec[][] = [];
  for (const target of targets) {
    const targetPaths = shortestConversionPaths(source, target, conversions);
    if (targetPaths === null) return null;
    paths.push(...targetPaths);
  }
  return paths;
}

function connectionRoute(
  projection: FieldProjection | undefined,
  conversionPath: readonly ArtifactConversionSpec[],
  artifactTypeBinding?: ConnectionArtifactTypeBinding,
): ConnectionRoute {
  const binding = artifactTypeBinding ? { artifactTypeBinding } : {};
  if (projection) {
    return conversionPath.length
      ? {
          kind: "projection-conversion",
          projection,
          conversionPath,
          ...binding,
        }
      : {
          kind: "projection",
          projection,
          conversionPath,
          ...binding,
        };
  }
  return conversionPath.length
    ? { kind: "conversion", conversionPath, ...binding }
    : { kind: "exact", conversionPath, ...binding };
}

function sortedConversionTargetTypes(
  conversions: readonly ArtifactConversionSpec[],
): ArtifactTypeKey[] {
  const byKey = new Map<string, ArtifactTypeKey>();
  for (const conversion of conversions) {
    byKey.set(
      artifactTypeKey(conversion.target_artifact_type),
      conversion.target_artifact_type,
    );
  }
  return [...byKey.values()].sort((left, right) =>
    artifactTypeKey(left).localeCompare(artifactTypeKey(right)),
  );
}

function genericTargetRoutesFrom(
  sourceArtifactType: ArtifactTypeKey,
  projection: FieldProjection | undefined,
  variable: string,
  conversions: readonly ArtifactConversionSpec[],
): ConnectionRoute[] | null {
  const routes = [
    connectionRoute(projection, [], {
      endpoint: "target",
      variable,
      artifactType: sourceArtifactType,
    }),
  ];
  for (const targetArtifactType of sortedConversionTargetTypes(conversions)) {
    if (
      artifactTypeKey(sourceArtifactType) ===
      artifactTypeKey(targetArtifactType)
    ) {
      continue;
    }
    const conversionPaths = shortestConversionPaths(
      sourceArtifactType,
      targetArtifactType,
      conversions,
    );
    if (conversionPaths === null) return null;
    for (const conversionPath of conversionPaths) {
      routes.push(
        connectionRoute(projection, conversionPath, {
          endpoint: "target",
          variable,
          artifactType: targetArtifactType,
        }),
      );
      if (routes.length > MAX_CONVERSION_PATH_CANDIDATES) return null;
    }
  }
  return routes;
}

/** Shortest simple conversion paths for the whole output and each projection. */
export function connectionRoutesForPorts(
  source: PortMeta,
  target: PortMeta,
  artifactTypes: readonly ArtifactTypeSpec[],
  conversions: readonly ArtifactConversionSpec[],
): ConnectionRoute[] {
  if (source.direction !== "output" || target.direction !== "input") {
    return [];
  }

  const sourceService = isServicePortMeta(source);
  const targetService = isServicePortMeta(target);
  if (sourceService || targetService) {
    if (
      !sourceService ||
      !targetService ||
      !serviceContractsOverlap(source.serviceContracts, target.serviceContracts)
    ) {
      return [];
    }
    return [{ kind: "exact", conversionPath: [] }];
  }

  const sourceArtifactType = portMetaArtifactType(source);
  const targetArtifactType = portMetaArtifactType(target);
  const sourceVariable = source.artifactTypeVariable;
  const targetVariable = target.artifactTypeVariable;
  if (!sourceArtifactType && !targetArtifactType) return [];
  if (!sourceArtifactType && targetArtifactType && sourceVariable) {
    return [
      connectionRoute(undefined, [], {
        endpoint: "source",
        variable: sourceVariable,
        artifactType: targetArtifactType,
      }),
    ];
  }
  if (sourceArtifactType && !targetArtifactType && targetVariable) {
    const routes = genericTargetRoutesFrom(
      sourceArtifactType,
      undefined,
      targetVariable,
      conversions,
    );
    if (routes === null) return [];

    const sourceArtifact = artifactTypes.find(
      (artifact) =>
        artifactTypeKey(artifact.key) === artifactTypeKey(sourceArtifactType),
    );
    const projections = [...(sourceArtifact?.field_projections ?? [])].sort(
      (left, right) =>
        left.path.join(".").localeCompare(right.path.join(".")) ||
        left.title.localeCompare(right.title),
    );
    for (const projection of projections) {
      const projectionRoutes = genericTargetRoutesFrom(
        projection.target_artifact_type,
        projection,
        targetVariable,
        conversions,
      );
      if (
        projectionRoutes === null ||
        routes.length + projectionRoutes.length > MAX_CONVERSION_PATH_CANDIDATES
      ) {
        return [];
      }
      routes.push(...projectionRoutes);
    }
    return routes;
  }
  if (!sourceArtifactType || !targetArtifactType) return [];

  const targetArtifactTypes = acceptedPortMetaArtifactTypes(target);
  if (
    targetArtifactTypes.some(
      (candidate) =>
        artifactTypeKey(candidate) === artifactTypeKey(sourceArtifactType),
    )
  ) {
    return [{ kind: "exact", conversionPath: [] }];
  }

  const sourceArtifact = artifactTypes.find(
    (artifact) =>
      artifactTypeKey(artifact.key) === artifactTypeKey(sourceArtifactType),
  );
  const wholeOutputPaths = shortestConversionPathsToAny(
    sourceArtifactType,
    targetArtifactTypes,
    conversions,
  );
  if (wholeOutputPaths === null) return [];
  const routes = wholeOutputPaths.map((conversionPath) =>
    connectionRoute(undefined, conversionPath),
  );
  if (routes.length > MAX_CONVERSION_PATH_CANDIDATES) return [];

  const projections = [...(sourceArtifact?.field_projections ?? [])].sort(
    (left, right) =>
      left.path.join(".").localeCompare(right.path.join(".")) ||
      left.title.localeCompare(right.title),
  );
  for (const projection of projections) {
    const conversionPaths = shortestConversionPathsToAny(
      projection.target_artifact_type,
      targetArtifactTypes,
      conversions,
    );
    if (conversionPaths === null) return [];
    const projectionRoutes = conversionPaths.map((conversionPath) =>
      connectionRoute(projection, conversionPath),
    );
    if (
      routes.length + projectionRoutes.length >
      MAX_CONVERSION_PATH_CANDIDATES
    ) {
      return [];
    }
    routes.push(...projectionRoutes);
  }

  return routes;
}

/** Replay one exact persisted selection without replacing it with a shorter path. */
export function connectionRouteForPortSelection(
  source: PortMeta,
  target: PortMeta,
  artifactTypes: readonly ArtifactTypeSpec[],
  conversions: readonly ArtifactConversionSpec[],
  selection: ConnectionRouteSelection,
): ConnectionRoute | null {
  if (isServicePortMeta(source) || isServicePortMeta(target)) {
    if (selection.projection || selection.conversionPath.length > 0) {
      return null;
    }
    return (
      connectionRoutesForPorts(source, target, artifactTypes, conversions)[0] ??
      null
    );
  }
  const sourceArtifactType = portMetaArtifactType(source);
  const targetArtifactType = portMetaArtifactType(target);
  if (
    !sourceArtifactType ||
    !targetArtifactType ||
    source.direction !== "output" ||
    target.direction !== "input" ||
    selection.conversionPath.length > MAX_CONVERSION_PATH_LENGTH
  ) {
    return null;
  }

  const sourceArtifact = artifactTypes.find(
    (artifact) =>
      artifactTypeKey(artifact.key) === artifactTypeKey(sourceArtifactType),
  );
  const projection = selection.projection
    ? sourceArtifact?.field_projections.find(
        (candidate) =>
          candidate.path.length === selection.projection?.path.length &&
          candidate.path.every(
            (segment, index) => segment === selection.projection?.path[index],
          ),
      )
    : undefined;
  if (selection.projection && !projection) return null;

  let currentArtifactType = projection?.target_artifact_type ?? {
    id: sourceArtifactType.id,
    schema_version: sourceArtifactType.schema_version,
  };
  const visitedArtifactTypes = new Set([artifactTypeKey(currentArtifactType)]);
  const conversionPath: ArtifactConversionSpec[] = [];
  for (const requestedConversion of selection.conversionPath) {
    const conversion = conversions.find(
      (candidate) =>
        candidate.key.id === requestedConversion.id &&
        candidate.key.version === requestedConversion.version,
    );
    if (
      !conversion ||
      artifactTypeKey(conversion.source_artifact_type) !==
        artifactTypeKey(currentArtifactType)
    ) {
      return null;
    }
    const nextArtifactTypeKey = artifactTypeKey(
      conversion.target_artifact_type,
    );
    if (visitedArtifactTypes.has(nextArtifactTypeKey)) return null;
    visitedArtifactTypes.add(nextArtifactTypeKey);
    conversionPath.push(conversion);
    currentArtifactType = conversion.target_artifact_type;
  }

  if (
    !acceptedPortMetaArtifactTypes(target).some((candidate) =>
      artifactTypeMatches(
        currentArtifactType,
        candidate.id,
        candidate.schema_version,
      ),
    )
  ) {
    return null;
  }
  return connectionRoute(projection, conversionPath);
}

export function connectionRouteSelection(
  route: ConnectionRoute,
): ConnectionRouteSelection {
  const projection =
    route.kind === "projection" || route.kind === "projection-conversion"
      ? { path: [...route.projection.path] }
      : undefined;
  const conversionPath = route.conversionPath.map((conversion) => ({
    id: conversion.key.id,
    version: conversion.key.version,
  }));
  return { projection, conversionPath };
}

/** Artifact type a route hands to the input, or null when it feeds the output as-is. */
export function connectionRouteDeliveredArtifactType(
  route: ConnectionRoute,
): ArtifactTypeKey | null {
  const lastConversion = route.conversionPath.at(-1);
  if (lastConversion) return lastConversion.target_artifact_type;
  return route.kind === "projection"
    ? route.projection.target_artifact_type
    : null;
}

export function connectionRouteMatchesSelection(
  route: ConnectionRoute,
  selection: ConnectionRouteSelection,
): boolean {
  const candidate = connectionRouteSelection(route);
  const projectionMatches = candidate.projection
    ? Boolean(
        selection.projection &&
        candidate.projection.path.length === selection.projection.path.length &&
        candidate.projection.path.every(
          (segment, index) => segment === selection.projection?.path[index],
        ),
      )
    : selection.projection === undefined;
  const conversionPathMatches =
    candidate.conversionPath.length === selection.conversionPath.length &&
    candidate.conversionPath.every(
      (conversion, index) =>
        conversion.id === selection.conversionPath[index]?.id &&
        conversion.version === selection.conversionPath[index]?.version,
    );
  return projectionMatches && conversionPathMatches;
}
