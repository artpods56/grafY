import { describe, expect, it } from "vitest";

import type { ConnectionRoute } from "../canvas/handles";
import {
  connectionRouteFeedDescription,
  connectionRouteFeedTitle,
  edgeTransportChipLabel,
  feedChoicesFromRouteOptions,
  orderFeedRoutes,
  preferredWholeFeedRoute,
  routesForHandleFeed,
  routesMatchingProjectionPath,
} from "./connection-feeds";

describe("connection feed presentation", () => {
  it("titles and describes projection-conversion feeds without conversion ids", () => {
    const route = {
      kind: "projection-conversion",
      projection: {
        path: ["profile", "age"],
        target_artifact_type: {
          id: "scalar.integer",
          schema_version: 1,
        },
        title: "Age",
      },
      conversionPath: [
        {
          key: { id: "builtin.scalar.integer_to_text", version: 1 },
          source_artifact_type: {
            id: "scalar.integer",
            schema_version: 1,
          },
          target_artifact_type: { id: "scalar.text", schema_version: 1 },
          title: "Integer to text",
        },
      ],
    } satisfies ConnectionRoute;

    expect(connectionRouteFeedTitle(route)).toBe("Age → Integer to text");
    expect(connectionRouteFeedDescription("payload", route)).toBe(
      "Field payload.profile.age · Integer to text",
    );
  });

  it("builds a single feed list from route options", () => {
    const choices = feedChoicesFromRouteOptions("result", [
      {
        projection: undefined,
        conversionPath: [],
        conversionTitles: [],
      },
      {
        projection: { path: ["body"] },
        conversionPath: [{ id: "normalize_text", version: 2 }],
        projectionTitle: "Body",
        conversionTitles: ["Normalize text"],
      },
    ]);

    expect(choices.map((choice) => choice.title)).toEqual([
      "Whole output",
      "Body → Normalize text",
    ]);
    expect(choices[1]?.description).toBe("result.body · Normalize text");
  });

  it("prefers projection titles on the edge chip", () => {
    expect(
      edgeTransportChipLabel({
        sourcePortName: "result",
        projection: { path: ["profile", "age"] },
        projectionTitle: "Age",
        conversionTitles: ["Integer to text"],
        collectionMode: "map",
        enabled: true,
        compatible: true,
      }),
    ).toBe("Age → Integer to text · each item");
  });

  it("filters routes to a preferred projection path", () => {
    const routes = [
      { kind: "exact", conversionPath: [] },
      {
        kind: "projection",
        projection: {
          path: ["body"],
          target_artifact_type: { id: "scalar.text", schema_version: 1 },
          title: "Body",
        },
        conversionPath: [],
      },
      {
        kind: "projection-conversion",
        projection: {
          path: ["body"],
          target_artifact_type: { id: "scalar.text", schema_version: 1 },
          title: "Body",
        },
        conversionPath: [
          {
            key: { id: "normalize_text", version: 2 },
            source_artifact_type: { id: "scalar.text", schema_version: 1 },
            target_artifact_type: { id: "scalar.text", schema_version: 1 },
            title: "Normalize text",
          },
        ],
      },
    ] satisfies ConnectionRoute[];

    expect(routesMatchingProjectionPath(routes, ["body"])).toHaveLength(2);
    expect(routesMatchingProjectionPath(routes, ["missing"])).toHaveLength(0);
    expect(routesForHandleFeed(routes, { kind: "whole" })).toEqual([routes[0]]);
    expect(
      routesForHandleFeed(routes, { kind: "projection", path: ["body"] }),
    ).toHaveLength(2);
    expect(preferredWholeFeedRoute(routes)?.kind).toBe("exact");
    expect(orderFeedRoutes(routes).map((route) => route.kind)).toEqual([
      "exact",
      "projection",
      "projection-conversion",
    ]);
  });
});
