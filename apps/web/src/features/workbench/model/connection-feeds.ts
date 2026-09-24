import type { RunEdgeCollectionMode } from "@/lib/api";

import type { ConnectionRoute } from "../canvas/handles";
import type {
  WorkflowEdgeData,
  WorkflowEdgeRoute,
  WorkflowEdgeRouteOption,
} from "../canvas/types";
import { connectionRouteTitle } from "./graph-authoring";

export interface ConnectionFeedChoice {
  key: string;
  title: string;
  description: string;
  route: WorkflowEdgeRouteOption;
}

export function projectionsEqual(
  left: WorkflowEdgeRoute["projection"],
  right: WorkflowEdgeRoute["projection"],
): boolean {
  if (!left || !right) return left === right;
  return (
    left.path.length === right.path.length &&
    left.path.every((segment, index) => segment === right.path[index])
  );
}

export function conversionPathsEqual(
  left: WorkflowEdgeRoute["conversionPath"],
  right: WorkflowEdgeRoute["conversionPath"],
): boolean {
  return (
    left.length === right.length &&
    left.every(
      (conversion, index) =>
        conversion.id === right[index]?.id &&
        conversion.version === right[index]?.version,
    )
  );
}

export function routesMatchingProjectionPath(
  routes: readonly ConnectionRoute[],
  path: readonly string[],
): ConnectionRoute[] {
  return routes.filter((route) => {
    if (route.kind !== "projection" && route.kind !== "projection-conversion") {
      return false;
    }
    return (
      route.projection.path.length === path.length &&
      route.projection.path.every((segment, index) => segment === path[index])
    );
  });
}

/** Prefer routes that match a catalog satellite's feed intent. */
export function routesForHandleFeed(
  routes: readonly ConnectionRoute[],
  feed:
    | { kind: "whole" }
    | { kind: "projection"; path: readonly string[] }
    | undefined,
): ConnectionRoute[] {
  if (!feed) return [...routes];
  if (feed.kind === "whole") {
    const whole = routes.filter(
      (route) => route.kind === "exact" || route.kind === "conversion",
    );
    return whole.length ? whole : [...routes];
  }
  const matching = routesMatchingProjectionPath(routes, feed.path);
  return matching.length ? matching : [...routes];
}

function isWholeFeedRoute(route: ConnectionRoute): boolean {
  return route.kind === "exact" || route.kind === "conversion";
}

/** Prefer whole-output feeds when connecting first. */
export function preferredWholeFeedRoute(
  routes: readonly ConnectionRoute[],
): ConnectionRoute | undefined {
  return routes.find(isWholeFeedRoute) ?? routes[0];
}

/** Whole feeds first, then field projections — stable for the picker. */
export function orderFeedRoutes(
  routes: readonly ConnectionRoute[],
): ConnectionRoute[] {
  return [...routes].sort((left, right) => {
    const leftWhole = isWholeFeedRoute(left) ? 0 : 1;
    const rightWhole = isWholeFeedRoute(right) ? 0 : 1;
    if (leftWhole !== rightWhole) return leftWhole - rightWhole;
    return connectionRouteFeedTitle(left).localeCompare(
      connectionRouteFeedTitle(right),
    );
  });
}

/** Human title for a feed choice (projection ± conversion). */
export function feedTitleForRouteOption(
  route: WorkflowEdgeRouteOption,
): string {
  const conversionTitle = route.conversionTitles.join(" → ");
  if (route.projection) {
    const projectionTitle =
      route.projectionTitle ?? route.projection.path.join(".");
    return conversionTitle
      ? `${projectionTitle} → ${conversionTitle}`
      : projectionTitle;
  }
  if (conversionTitle) return `Whole output → ${conversionTitle}`;
  return "Whole output";
}

export function feedDescriptionForRouteOption(
  sourcePortName: string,
  route: WorkflowEdgeRouteOption,
): string {
  const path = route.projection?.path.length
    ? `${sourcePortName}.${route.projection.path.join(".")}`
    : sourcePortName;
  if (!route.conversionPath.length) {
    return route.projection
      ? `Field ${path}`
      : `Entire ${sourcePortName} output`;
  }
  return `${path} · ${route.conversionTitles.join(" → ") || "converted"}`;
}

export function feedChoicesFromRouteOptions(
  sourcePortName: string,
  routeOptions: readonly WorkflowEdgeRouteOption[],
): ConnectionFeedChoice[] {
  const choices: ConnectionFeedChoice[] = [];
  for (const route of routeOptions) {
    if (
      choices.some(
        (choice) =>
          projectionsEqual(choice.route.projection, route.projection) &&
          conversionPathsEqual(
            choice.route.conversionPath,
            route.conversionPath,
          ),
      )
    ) {
      continue;
    }
    choices.push({
      key: [
        route.projection?.path.join(".") ?? "whole",
        route.conversionPath
          .map((conversion) => `${conversion.id}@${conversion.version}`)
          .join("|") || "none",
      ].join("::"),
      title: feedTitleForRouteOption(route),
      description: feedDescriptionForRouteOption(sourcePortName, route),
      route,
    });
  }
  return choices;
}

/** Compact midpoint chip copy — titles over raw paths. */
export function edgeTransportChipLabel(params: {
  sourcePortName: string;
  projection: WorkflowEdgeData["projection"];
  projectionTitle?: string;
  conversionTitles?: readonly string[];
  collectionMode: RunEdgeCollectionMode;
  enabled: boolean;
  compatible: boolean;
}): string {
  const {
    sourcePortName,
    projection,
    projectionTitle,
    conversionTitles = [],
    collectionMode,
    enabled,
    compatible,
  } = params;

  let label = projection?.path.length
    ? (projectionTitle ?? projection.path.join("."))
    : sourcePortName;
  if (conversionTitles.length) {
    label = `${label} → ${conversionTitles.join(" → ")}`;
  }
  if (collectionMode === "map") label = `${label} · each item`;
  if (!enabled) label = `${label} · disabled`;
  if (!compatible) label = `${label} · unavailable`;
  return label;
}

export function connectionRouteFeedTitle(route: ConnectionRoute): string {
  return connectionRouteTitle(route);
}

export function connectionRouteFeedDescription(
  sourcePortName: string,
  route: ConnectionRoute,
): string {
  if (route.kind === "exact") return `Entire ${sourcePortName} output`;
  if (route.kind === "projection") {
    return `Field ${sourcePortName}.${route.projection.path.join(".")}`;
  }
  if (route.kind === "conversion") {
    return `Entire ${sourcePortName} · ${route.conversionPath
      .map((conversion) => conversion.title)
      .join(" → ")}`;
  }
  return `Field ${sourcePortName}.${route.projection.path.join(".")} · ${route.conversionPath
    .map((conversion) => conversion.title)
    .join(" → ")}`;
}
