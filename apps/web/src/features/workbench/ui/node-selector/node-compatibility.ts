import type { NodeRegistry, NodeSpec, Port } from "@/lib/api";

import {
  connectionRoutesFor,
  encodeHandleId,
  type ConnectionRoute,
} from "../../canvas/handles";
import {
  acceptedPortShapes,
  portHasInstancePlugs,
  portMetaForPort,
} from "../../canvas/types";
import { catalogNodeKey, sortCatalogNodes } from "../../model/node-catalog";

/**
 * What else in the catalog can be wired to one port of the inspected node, and
 * how: the "Works with" list. Routes come from the same resolver canvas wiring
 * uses, so a suggestion here is an edge the canvas will accept.
 */

export interface CompatibleNode {
  spec: NodeSpec;
  /** "Text → Values · map each item · As text": the first route, in words. */
  routeSummary: string;
  additionalRouteCount: number;
}

interface CompatiblePortPair {
  source: Port;
  target: Port;
  route: ConnectionRoute;
  routeCount: number;
}

function shapesAreCompatible(source: Port, target: Port): boolean {
  const acceptedShapes = acceptedPortShapes(target);
  return (
    acceptedShapes.includes(source.shape) ||
    (!portHasInstancePlugs(target) &&
      source.shape === "many" &&
      acceptedShapes.includes("one"))
  );
}

function routeTitle(route: ConnectionRoute): string | null {
  const conversionTitle = route.conversionPath
    .map((conversion) => conversion.title)
    .join(" → ");
  if (route.kind === "projection") return route.projection.title;
  if (route.kind === "conversion") return conversionTitle;
  if (route.kind === "projection-conversion") {
    return `${route.projection.title} → ${conversionTitle}`;
  }
  return null;
}

function compatiblePortPairs(
  sourceSpec: NodeSpec,
  targetSpec: NodeSpec,
  registry: NodeRegistry,
): CompatiblePortPair[] {
  const pairs: CompatiblePortPair[] = [];
  for (const source of sourceSpec.outputs) {
    for (const target of targetSpec.inputs) {
      if (!shapesAreCompatible(source, target)) continue;
      const routes = connectionRoutesFor(
        {
          sourceHandle: encodeHandleId(portMetaForPort(source)),
          targetHandle: encodeHandleId(portMetaForPort(target)),
        },
        registry.artifact_types,
        registry.artifact_conversions,
      );
      const route = routes[0];
      if (!route) continue;
      pairs.push({ source, target, route, routeCount: routes.length });
    }
  }
  return pairs;
}

function transportLabel(pair: CompatiblePortPair): string {
  if (portHasInstancePlugs(pair.target)) return "direct to ordered input";
  return acceptedPortShapes(pair.target).includes(pair.source.shape)
    ? "direct"
    : "map each item";
}

/** Catalog nodes that connect to `port` of `selected`, in catalog order. */
export function compatibleNodesForPort(
  selected: NodeSpec,
  port: Port,
  registry: NodeRegistry,
): CompatibleNode[] {
  const selectedKey = catalogNodeKey(selected);
  const matches = registry.nodes.flatMap((candidate): CompatibleNode[] => {
    if (catalogNodeKey(candidate) === selectedKey) return [];
    const pairs =
      port.direction === "input"
        ? compatiblePortPairs(candidate, selected, registry).filter(
            (pair) => pair.target.name === port.name,
          )
        : compatiblePortPairs(selected, candidate, registry).filter(
            (pair) => pair.source.name === port.name,
          );
    const first = pairs[0];
    if (!first) return [];

    const routeSummary = [
      `${first.source.title ?? first.source.name} → ${first.target.title ?? first.target.name}`,
      transportLabel(first),
      routeTitle(first.route),
    ]
      .filter((value): value is string => Boolean(value))
      .join(" · ");
    const totalRouteCount = pairs.reduce(
      (count, pair) => count + pair.routeCount,
      0,
    );
    return [
      {
        spec: candidate,
        routeSummary,
        additionalRouteCount: totalRouteCount - 1,
      },
    ];
  });
  const order = new Map(
    sortCatalogNodes(matches.map((match) => match.spec)).map((spec, index) => [
      catalogNodeKey(spec),
      index,
    ]),
  );
  return matches.sort(
    (left, right) =>
      (order.get(catalogNodeKey(left.spec)) ?? 0) -
      (order.get(catalogNodeKey(right.spec)) ?? 0),
  );
}
