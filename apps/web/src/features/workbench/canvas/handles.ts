import type {
  ArtifactConversionInput,
  ArtifactConversionSpec,
  ArtifactTypeKey,
  ArtifactTypeSpec,
  FieldProjection,
} from "@/lib/api";
import type { HandleFeedIntent, PortMeta } from "./types";

export type { HandleFeedIntent };

const HANDLE_FEED_PREFIX = "feed=";
const HANDLE_ALSO_ACCEPTS_PREFIX = "also=";

function encodeHandleFeedSegment(feed: HandleFeedIntent): string {
  if (feed.kind === "whole") return `${HANDLE_FEED_PREFIX}whole`;
  return `${HANDLE_FEED_PREFIX}proj/${feed.path.map(encodeURIComponent).join("/")}`;
}

/** Encode the additional accepted artifact types of one input port handle. */
function encodeHandleAlsoAcceptsSegment(
  accepted: readonly ArtifactTypeKey[],
): string {
  return `${HANDLE_ALSO_ACCEPTS_PREFIX}${accepted
    .map((key) => encodeURIComponent(`${key.id}@${key.schema_version}`))
    .join(",")}`;
}

function decodeHandleAlsoAcceptsSegment(
  segment: string,
): ArtifactTypeKey[] | null {
  const body = segment.slice(HANDLE_ALSO_ACCEPTS_PREFIX.length);
  if (!body) return null;
  try {
    return body.split(",").map((entry) => {
      const decoded = decodeURIComponent(entry);
      const separator = decoded.lastIndexOf("@");
      const id = decoded.slice(0, separator);
      const schemaVersion = Number(decoded.slice(separator + 1));
      if (separator <= 0 || !id || !Number.isInteger(schemaVersion)) {
        throw new Error("invalid accepted artifact type");
      }
      return { id, schema_version: schemaVersion };
    });
  } catch {
    return null;
  }
}

function isHandleAlsoAcceptsSegment(segment: string | undefined): boolean {
  return (
    typeof segment === "string" &&
    segment.startsWith(HANDLE_ALSO_ACCEPTS_PREFIX)
  );
}

function decodeHandleFeedSegment(segment: string): HandleFeedIntent | null {
  if (!segment.startsWith(HANDLE_FEED_PREFIX)) return null;
  const body = segment.slice(HANDLE_FEED_PREFIX.length);
  if (body === "whole") return { kind: "whole" };
  if (!body.startsWith("proj/")) return null;
  try {
    const path = body
      .slice("proj/".length)
      .split("/")
      .filter(Boolean)
      .map((segment) => decodeURIComponent(segment));
    if (!path.length) return null;
    return { kind: "projection", path };
  } catch {
    return null;
  }
}

function isHandleFeedSegment(segment: string | undefined): boolean {
  return typeof segment === "string" && segment.startsWith(HANDLE_FEED_PREFIX);
}

/**
 * Encode port type information into the React Flow handle id so that
 * `isValidConnection` can enforce typed artifact flow without extra
 * lookups. Optional {@link PortMeta.feed} marks catalog satellites.
 */
export function encodeHandleId(port: PortMeta): string {
  const parts = port.artifactTypeVariable
    ? [
        port.portName,
        encodeURIComponent(port.artifactTypeVariable),
        "$generic",
        port.shape,
        port.direction,
      ]
    : [
        port.portName,
        port.artifactTypeId,
        port.schemaVersion,
        port.shape,
        port.direction,
      ];
  if (port.plugId) parts.push(port.plugId);
  if (port.alsoAccepts?.length) {
    parts.push(encodeHandleAlsoAcceptsSegment(port.alsoAccepts));
  }
  if (port.feed) parts.push(encodeHandleFeedSegment(port.feed));
  return parts.join("::");
}

/** Drop connect-time feed intent; persisted edges keep the canonical port handle. */
export function canonicalHandleId(
  id: string | null | undefined,
): string | null {
  const decoded = decodeHandleId(id);
  if (!decoded) return id ?? null;
  if (!decoded.feed) return id ?? null;
  return encodeHandleId({ ...decoded, feed: undefined });
}

interface DecodedHandleBase {
  portName: string;
  shape: PortMeta["shape"];
  direction: PortMeta["direction"];
  plugId?: string;
  feed?: HandleFeedIntent;
  alsoAccepts?: ArtifactTypeKey[];
}

interface DecodedConcreteHandle extends DecodedHandleBase {
  artifactTypeId: string;
  schemaVersion: number;
  artifactTypeVariable?: never;
}

interface DecodedGenericHandle extends DecodedHandleBase {
  artifactTypeId?: never;
  schemaVersion?: never;
  artifactTypeVariable: string;
}

export type DecodedHandle = DecodedConcreteHandle | DecodedGenericHandle;

export function decodeHandleId(
  id: string | null | undefined,
): DecodedHandle | null {
  if (!id) return null;
  const p = id.split("::");
  if (p.length < 5 || p.length > 8) return null;
  const shape = p[3];
  const direction = p[4];
  if (shape !== "one" && shape !== "many") return null;
  if (direction !== "input" && direction !== "output") return null;

  let plugId: string | undefined;
  let feed: HandleFeedIntent | undefined;
  let alsoAccepts: ArtifactTypeKey[] | undefined;
  for (const segment of p.slice(5)) {
    if (isHandleFeedSegment(segment)) {
      if (feed) return null;
      const decodedFeed = decodeHandleFeedSegment(segment);
      if (!decodedFeed) return null;
      feed = decodedFeed;
      continue;
    }
    if (isHandleAlsoAcceptsSegment(segment)) {
      if (alsoAccepts) return null;
      const decodedAccepted = decodeHandleAlsoAcceptsSegment(segment);
      if (!decodedAccepted) return null;
      alsoAccepts = decodedAccepted;
      continue;
    }
    if (!segment || plugId) return null;
    plugId = segment;
  }

  if (p[2] === "$generic") {
    try {
      const artifactTypeVariable = decodeURIComponent(p[1]);
      if (!artifactTypeVariable) return null;
      return {
        portName: p[0],
        artifactTypeVariable,
        shape,
        direction,
        ...(plugId ? { plugId } : {}),
        ...(feed ? { feed } : {}),
      };
    } catch {
      return null;
    }
  }

  const schemaVersion = Number(p[2]);
  if (!Number.isInteger(schemaVersion)) return null;
  return {
    portName: p[0],
    artifactTypeId: p[1],
    schemaVersion,
    shape,
    direction,
    ...(plugId ? { plugId } : {}),
    ...(alsoAccepts ? { alsoAccepts } : {}),
    ...(feed ? { feed } : {}),
  };
}

export function decodedHandleArtifactType(
  handle: DecodedHandle,
): ArtifactTypeKey | null {
  if (
    typeof handle.artifactTypeId !== "string" ||
    typeof handle.schemaVersion !== "number"
  ) {
    return null;
  }
  return {
    id: handle.artifactTypeId,
    schema_version: handle.schemaVersion,
  };
}

/** Concrete artifact types one decoded handle accepts, primary type first. */
export function acceptedHandleArtifactTypes(
  handle: DecodedHandle,
): ArtifactTypeKey[] {
  const primary = decodedHandleArtifactType(handle);
  if (!primary) return [];
  return [primary, ...(handle.alsoAccepts ?? [])];
}

function handleAcceptsArtifactType(
  handle: DecodedHandle,
  artifactType: ArtifactTypeKey,
): boolean {
  return acceptedHandleArtifactTypes(handle).some(
    (candidate) => artifactTypeKey(candidate) === artifactTypeKey(artifactType),
  );
}

/** A connection is valid when the output and input share an artifact contract. */
export function connectionIsValid(connection: {
  sourceHandle?: string | null;
  targetHandle?: string | null;
}): boolean {
  const s = decodeHandleId(connection.sourceHandle);
  const t = decodeHandleId(connection.targetHandle);
  if (!s || !t) return false;
  const sourceArtifactType = decodedHandleArtifactType(s);
  const targetArtifactType = decodedHandleArtifactType(t);
  if (!sourceArtifactType && !targetArtifactType) return false;
  return (
    s.direction === "output" &&
    t.direction === "input" &&
    (!sourceArtifactType ||
      !targetArtifactType ||
      handleAcceptsArtifactType(t, sourceArtifactType)) &&
    s.shape === t.shape
  );
}

/** Artifact identity compatibility without collection-shape handling. */
export function connectionArtifactContractIsValid(connection: {
  sourceHandle?: string | null;
  targetHandle?: string | null;
}): boolean {
  const source = decodeHandleId(connection.sourceHandle);
  const target = decodeHandleId(connection.targetHandle);
  if (!source || !target) return false;
  const sourceArtifactType = decodedHandleArtifactType(source);
  const targetArtifactType = decodedHandleArtifactType(target);
  if (!sourceArtifactType || !targetArtifactType) return false;
  return (
    source.direction === "output" &&
    target.direction === "input" &&
    handleAcceptsArtifactType(target, sourceArtifactType)
  );
}

/** Declared source-field projections that can satisfy a typed connection. */
export function projectionCandidatesForConnection(
  connection: {
    sourceHandle?: string | null;
    targetHandle?: string | null;
  },
  artifactTypes: readonly ArtifactTypeSpec[],
): FieldProjection[] {
  const source = decodeHandleId(connection.sourceHandle);
  const target = decodeHandleId(connection.targetHandle);
  const sourceArtifactType = source
    ? decodedHandleArtifactType(source)
    : null;
  const targetArtifactType = target
    ? decodedHandleArtifactType(target)
    : null;
  if (
    !source ||
    !target ||
    !sourceArtifactType ||
    !targetArtifactType ||
    source.direction !== "output" ||
    target.direction !== "input" ||
    handleAcceptsArtifactType(target, sourceArtifactType)
  ) {
    return [];
  }

  const sourceArtifact = artifactTypes.find(
    (artifact) =>
      artifactTypeKey(artifact.key) === artifactTypeKey(sourceArtifactType),
  );
  if (!sourceArtifact?.field_projections) return [];

  return sourceArtifact.field_projections.filter((projection) =>
    handleAcceptsArtifactType(target, projection.target_artifact_type),
  );
}

export type ConnectionRoute =
  | ({ kind: "exact"; conversionPath: readonly ArtifactConversionSpec[] } &
      ConnectionRouteBinding)
  | {
      kind: "projection";
      projection: FieldProjection;
      conversionPath: readonly ArtifactConversionSpec[];
    } & ConnectionRouteBinding
  | {
      kind: "conversion";
      conversionPath: readonly ArtifactConversionSpec[];
    } & ConnectionRouteBinding
  | {
      kind: "projection-conversion";
      projection: FieldProjection;
      conversionPath: readonly ArtifactConversionSpec[];
    } & ConnectionRouteBinding;

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
  return artifactType.id === id && artifactType.schema_version === schemaVersion;
}

function artifactTypeKey(
  artifactType: { id: string; schema_version: number },
): string {
  return `${artifactType.id}@${artifactType.schema_version}`;
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
    const comparison = compareConversions(left[index], right[index]);
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
      for (const conversion of
        conversionsBySource.get(artifactTypeKey(state.artifactType)) ?? []) {
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

function shortestConversionPathsToAny(
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
      artifactTypeKey(sourceArtifactType) === artifactTypeKey(targetArtifactType)
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
export function connectionRoutesFor(
  connection: {
    sourceHandle?: string | null;
    targetHandle?: string | null;
  },
  artifactTypes: readonly ArtifactTypeSpec[],
  conversions: readonly ArtifactConversionSpec[],
): ConnectionRoute[] {
  const source = decodeHandleId(connection.sourceHandle);
  const target = decodeHandleId(connection.targetHandle);
  if (
    !source ||
    !target ||
    source.direction !== "output" ||
    target.direction !== "input"
  ) {
    return [];
  }

  const sourceArtifactType = decodedHandleArtifactType(source);
  const targetArtifactType = decodedHandleArtifactType(target);
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
        routes.length + projectionRoutes.length >
          MAX_CONVERSION_PATH_CANDIDATES
      ) {
        return [];
      }
      routes.push(...projectionRoutes);
    }
    return routes;
  }
  if (!sourceArtifactType || !targetArtifactType) return [];

  const targetArtifactTypes = acceptedHandleArtifactTypes(target);
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
export function connectionRouteForSelection(
  connection: {
    sourceHandle?: string | null;
    targetHandle?: string | null;
  },
  artifactTypes: readonly ArtifactTypeSpec[],
  conversions: readonly ArtifactConversionSpec[],
  selection: ConnectionRouteSelection,
): ConnectionRoute | null {
  const source = decodeHandleId(connection.sourceHandle);
  const target = decodeHandleId(connection.targetHandle);
  const sourceArtifactType = source
    ? decodedHandleArtifactType(source)
    : null;
  const targetArtifactType = target
    ? decodedHandleArtifactType(target)
    : null;
  if (
    !source ||
    !target ||
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
            (segment, index) =>
              segment === selection.projection?.path[index],
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
    !acceptedHandleArtifactTypes(target).some((candidate) =>
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
