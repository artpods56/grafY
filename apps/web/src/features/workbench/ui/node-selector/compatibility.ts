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
import type { NodeRegistry, NodeSpec, Port } from "@/lib/api";
import { catalogNodeKey, sortCatalogNodes } from "../../model/node-catalog";

export const MODULE_PLUGIN_SLUG = "graph.module";

export interface CompatibleNode {
  spec: NodeSpec;
  routeSummary: string;
  additionalRouteCount: number;
}

export interface CompatiblePortPair {
  source: Port;
  target: Port;
  route: ConnectionRoute;
  routeCount: number;
}

export function nodeKey(spec: NodeSpec): string {
  return catalogNodeKey(spec);
}

export function pluginFor(
  registry: NodeRegistry,
  slug: string,
): NodeRegistry["plugins"][number] {
  const plugin = registry.plugins.find((candidate) => candidate.slug === slug);
  if (!plugin) {
    throw new Error(`Node registry is missing owner plugin "${slug}".`);
  }
  return plugin;
}

export function shapesAreCompatible(source: Port, target: Port): boolean {
  const acceptedShapes = acceptedPortShapes(target);
  return (
    acceptedShapes.includes(source.shape) ||
    (!portHasInstancePlugs(target) &&
      source.shape === "many" &&
      acceptedShapes.includes("one"))
  );
}

export function routeTitle(route: ConnectionRoute): string | null {
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

export function compatiblePortPairs(
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

export function compatibleNodesForPort(
  selected: NodeSpec,
  port: Port,
  registry: NodeRegistry,
): CompatibleNode[] {
  const selectedKey = nodeKey(selected);
  const matches = registry.nodes.flatMap((candidate) => {
    if (nodeKey(candidate) === selectedKey) return [];
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

    const transport = portHasInstancePlugs(first.target)
      ? "direct to ordered input"
      : acceptedPortShapes(first.target).includes(first.source.shape)
        ? "direct"
        : "map each item";
    const transformation = routeTitle(first.route);
    const routeSummary = [
      `${first.source.title ?? first.source.name} → ${first.target.title ?? first.target.name}`,
      transport,
      transformation,
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
      nodeKey(spec),
      index,
    ]),
  );
  return matches.sort(
    (left, right) =>
      (order.get(nodeKey(left.spec)) ?? 0) -
      (order.get(nodeKey(right.spec)) ?? 0),
  );
}
