import { describe, expect, it } from "vitest";

import type { ConnectionRoute } from "./connection-routes";
import {
  createWorkflowNodeData,
  type GraphConnection,
  type WorkflowEdge,
} from "./types";
import type { NodeSpec, Port, SavedGraphOrigin } from "@/lib/api";
import {
  collectionModeForConnection,
  collectionModesForConnection,
  connectionRouteTitle,
  isConnectionAccepted,
  mappedInputPortsForNode,
  workflowEdgeRouteOption,
  type GraphAuthoringNode,
} from "./graph-authoring";

function port(
  name: string,
  direction: Port["direction"],
  shape: Port["shape"],
  overrides: Partial<Port> = {},
): Port {
  return {
    name,
    kind: "artifact",
    title: name.replaceAll("_", " "),
    description: null,
    direction,
    artifact_type: { id: "scalar.text", schema_version: 1 },
    artifact_type_variable: null,
    shape,
    accepted_shapes: [shape],
    required: direction === "input",
    variadic: false,
    instance_plugs: false,
    ...overrides,
  };
}

function node(
  id: string,
  inputs: readonly Port[],
  outputs: readonly Port[],
): GraphAuthoringNode {
  const spec: NodeSpec = {
    pack_slugs: [],
    role: "operator",
    operator_id: `test.${id}`,
    operator_version: 1,
    plugin_slug: "test",
    origin: "builtin",
    title: id.replaceAll("_", " "),
    description: `Test node ${id}`,
    catalog_visible: true,
    runnable: true,
    config_schema: {},
    input_schema: {},
    output_schema: {},
    inputs,
    outputs,
  };
  return { id, data: createWorkflowNodeData(spec) };
}

function edge({
  id,
  source,
  target,
  sourcePort = "output",
  targetPort = "input",
  targetPlug,
  enabled = true,
  collectionMode = "direct",
}: {
  id: string;
  source: string;
  target: string;
  sourcePort?: string;
  targetPort?: string;
  targetPlug?: string;
  enabled?: boolean;
  collectionMode?: "direct" | "map";
}): WorkflowEdge {
  return {
    id,
    source,
    sourcePort,
    target,
    targetPort,
    ...(targetPlug ? { targetPlug } : {}),
    data: {
      enabled,
      collectionMode,
      conversionPath: [],
    },
  };
}

function connection({
  source,
  sourcePort,
  target,
  targetPort,
  targetPlug,
}: {
  source: string;
  sourcePort: string;
  target: string;
  targetPort: string;
  targetPlug?: string;
}): GraphConnection {
  return {
    source,
    sourcePort,
    target,
    targetPort,
    ...(targetPlug !== undefined ? { targetPlug } : {}),
  };
}

describe("connection route presentation", () => {
  it("keeps projection, conversion, and generic binding details together", () => {
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
      artifactTypeBinding: {
        endpoint: "target",
        variable: "T",
        artifactType: { id: "scalar.text", schema_version: 1 },
      },
    } satisfies ConnectionRoute;

    // With no catalog, the route carries the type's full identity.
    expect(connectionRouteTitle(route, null)).toBe(
      "Age → Integer to text · scalar.text@1",
    );
    // A catalog title replaces the identity.
    expect(
      connectionRouteTitle(route, [
        {
          key: { id: "scalar.text", schema_version: 1 },
          title: "Text value",
        },
      ]),
    ).toBe("Age → Integer to text · Text value");
    expect(workflowEdgeRouteOption(route)).toEqual({
      projection: { path: ["profile", "age"] },
      conversionPath: [{ id: "builtin.scalar.integer_to_text", version: 1 }],
      projectionTitle: "Age",
      conversionTitles: ["Integer to text"],
    });
  });
});

describe("connection collection policy", () => {
  it("keeps a disabled map edge structurally relevant while hiding it from active state", () => {
    const source = node(
      "source",
      [port("mapped", "input", "one")],
      [port("result", "output", "one")],
    );
    const target = node("target", [port("input", "input", "one")], []);
    const disabledMapEdge = edge({
      id: "driver-source",
      source: "driver",
      target: source.id,
      targetPort: "mapped",
      enabled: false,
      collectionMode: "map",
    });
    const link = connection({
      source: source.id,
      sourcePort: "result",
      target: target.id,
      targetPort: "input",
    });

    expect(mappedInputPortsForNode(source.id, [disabledMapEdge])).toEqual([]);
    expect(mappedInputPortsForNode(source.id, [disabledMapEdge], true)).toEqual(
      ["mapped"],
    );
    expect(
      collectionModeForConnection(link, [source, target], [disabledMapEdge]),
    ).toBe("map");
  });

  it("prefers direct transport when the target explicitly accepts the source shape", () => {
    const source = node("source", [], [port("output", "output", "many")]);
    const target = node(
      "target",
      [
        port("input", "input", "one", {
          accepted_shapes: ["one", "many"],
        }),
      ],
      [],
    );

    expect(
      collectionModeForConnection(
        connection({
          source: source.id,
          sourcePort: "output",
          target: target.id,
          targetPort: "input",
        }),
        [source, target],
        [],
      ),
    ).toBe("direct");
  });

  it("lets a sequence feeding a sequence input pass whole or map each item", () => {
    const source = node("source", [], [port("output", "output", "many")]);
    const target = node("target", [port("items", "input", "many")], []);
    const variadicTarget = node(
      "variadic_target",
      [port("items", "input", "many", { variadic: true })],
      [],
    );
    const link = (targetId: string) =>
      connection({
        source: source.id,
        sourcePort: "output",
        target: targetId,
        targetPort: "items",
      });

    expect(
      collectionModesForConnection(link(target.id), [source, target], []),
    ).toEqual(["direct", "map"]);
    expect(
      collectionModeForConnection(link(target.id), [source, target], []),
    ).toBe("direct");
    expect(
      collectionModesForConnection(
        link(variadicTarget.id),
        [source, variadicTarget],
        [],
      ),
    ).toEqual(["direct"]);
  });

  it("reads a node mapped by an artifact input as producing sequences", () => {
    const mapped = node(
      "mapped",
      [port("input", "input", "one")],
      [port("output", "output", "one")],
    );
    const target = node("target", [port("input", "input", "one")], []);
    const origin: SavedGraphOrigin = {
      id: "origin",
      to_node: mapped.id,
      to_port: "input",
      to_plug: null,
      value: {
        artifact_type: "scalar.text",
        schema_version: 1,
        item_refs: [],
        ordered: true,
        index_key: "order_index",
      },
      collection_mode: "map",
      conversion_path: [],
    };

    expect(mappedInputPortsForNode(mapped.id, [], false, [origin])).toEqual([
      "input",
    ]);
    expect(
      collectionModeForConnection(
        connection({
          source: mapped.id,
          sourcePort: "output",
          target: target.id,
          targetPort: "input",
        }),
        [mapped, target],
        [],
        [origin],
      ),
    ).toBe("map");
  });

  it("does not turn a sequence into map transport for an instance-plug input", () => {
    const source = node("source", [], [port("output", "output", "many")]);
    const target = node(
      "target",
      [port("items", "input", "one", { instance_plugs: true })],
      [],
    );

    expect(
      collectionModeForConnection(
        connection({
          source: source.id,
          sourcePort: "output",
          target: target.id,
          targetPort: "items",
          targetPlug: "item-1",
        }),
        [source, target],
        [],
      ),
    ).toBeNull();
  });
});

describe("connection acceptance policy", () => {
  it("rejects a second OCR provider, including a provider proposed by discovery", () => {
    const output = port("engine", "output", "one", {
      kind: "service",
      artifact_type: null,
      service_contracts: [{ id: "ocr.document", version: 1 }],
    });
    const input = { ...output, direction: "input" as const };
    const mistral = node("mistral", [], [output]);
    const reducto = node("reducto", [], [output]);
    const ocr = node("ocr", [input], [port("markdown", "output", "one")]);
    const existing: WorkflowEdge = {
      id: "first-reader",
      source: "mistral",
      sourcePort: "engine",
      target: "ocr",
      targetPort: "engine",
      data: { enabled: true, collectionMode: "direct" },
    };
    const candidate = connection({
      source: "reducto",
      sourcePort: "engine",
      target: "ocr",
      targetPort: "engine",
    });
    expect(
      isConnectionAccepted(candidate, [mistral, ocr, reducto], [], [], []),
    ).toBe(true);
    expect(
      isConnectionAccepted(
        candidate,
        [mistral, ocr, reducto],
        [existing],
        [],
        [],
      ),
    ).toBe(false);
    expect(
      isConnectionAccepted(candidate, [mistral, ocr, reducto], [], [], []),
    ).toBe(true);
  });

  it("requires a compatible route before accepting an otherwise free input", () => {
    const source = node("source", [], [port("output", "output", "one")]);
    const target = node("target", [port("input", "input", "one")], []);
    const incompatibleTarget = node(
      "incompatible",
      [
        port("input", "input", "one", {
          artifact_type: { id: "scalar.integer", schema_version: 1 },
        }),
      ],
      [],
    );

    expect(
      isConnectionAccepted(
        connection({
          source: source.id,
          sourcePort: "output",
          target: target.id,
          targetPort: "input",
        }),
        [source, target],
        [],
        [],
        [],
      ),
    ).toBe(true);
    expect(
      isConnectionAccepted(
        connection({
          source: source.id,
          sourcePort: "output",
          target: incompatibleTarget.id,
          targetPort: "input",
        }),
        [source, incompatibleTarget],
        [],
        [],
        [],
      ),
    ).toBe(false);
  });

  it("accepts only declared instance plugs and rejects plugs on ordinary ports", () => {
    const source = node("source", [], [port("output", "output", "one")]);
    const collect = node(
      "collect",
      [port("items", "input", "one", { instance_plugs: true })],
      [],
    );
    collect.data.inputPlugs = [{ id: "item-1", portName: "items" }];
    const ordinary = node("ordinary", [port("input", "input", "one")], []);

    for (const targetPlug of [undefined, "missing"] as const) {
      expect(
        isConnectionAccepted(
          connection({
            source: source.id,
            sourcePort: "output",
            target: collect.id,
            targetPort: "items",
            targetPlug,
          }),
          [source, collect],
          [],
          [],
          [],
        ),
      ).toBe(false);
    }

    expect(
      isConnectionAccepted(
        connection({
          source: source.id,
          sourcePort: "output",
          target: collect.id,
          targetPort: "items",
          targetPlug: "item-1",
        }),
        [source, collect],
        [],
        [],
        [],
      ),
    ).toBe(true);
    expect(
      isConnectionAccepted(
        connection({
          source: source.id,
          sourcePort: "output",
          target: ordinary.id,
          targetPort: "input",
          targetPlug: "item-1",
        }),
        [source, ordinary],
        [],
        [],
        [],
      ),
    ).toBe(false);
  });

  it("allows map drivers on different inputs and rejects an occupied input", () => {
    const source = node("source", [], [port("output", "output", "many")]);
    const target = node(
      "target",
      [port("driver", "input", "one"), port("candidate", "input", "one")],
      [],
    );
    const existingMapDriver = edge({
      id: "existing-map",
      source: "other-source",
      target: target.id,
      targetPort: "driver",
      collectionMode: "map",
      enabled: false,
    });

    expect(
      isConnectionAccepted(
        connection({
          source: source.id,
          sourcePort: "output",
          target: target.id,
          targetPort: "candidate",
        }),
        [source, target],
        [existingMapDriver],
        [],
        [],
      ),
    ).toBe(true);
    expect(
      mappedInputPortsForNode(target.id, [existingMapDriver], true),
    ).toEqual(["driver"]);
    expect(
      isConnectionAccepted(
        connection({
          source: source.id,
          sourcePort: "output",
          target: target.id,
          targetPort: "driver",
        }),
        [source, target],
        [existingMapDriver],
        [],
        [],
      ),
    ).toBe(false);
  });

  it("prevents cycles through existing edges, including disabled edges", () => {
    const source = node("leaf", [], [port("output", "output", "one")]);
    const target = node(
      "root",
      [port("input", "input", "one")],
      [port("output", "output", "one")],
    );
    const descendantEdge = edge({
      id: "root-to-leaf",
      source: target.id,
      target: source.id,
      enabled: false,
    });

    expect(
      isConnectionAccepted(
        connection({
          source: source.id,
          sourcePort: "output",
          target: target.id,
          targetPort: "input",
        }),
        [source, target],
        [descendantEdge],
        [],
        [],
      ),
    ).toBe(false);
  });

  it("enforces port and plug occupancy while leaving variadic ports open", () => {
    const source = node("source", [], [port("output", "output", "one")]);
    const ordinary = node("ordinary", [port("input", "input", "one")], []);
    const variadic = node(
      "variadic",
      [port("input", "input", "one", { variadic: true })],
      [],
    );
    const collect = node(
      "collect",
      [port("items", "input", "one", { instance_plugs: true })],
      [],
    );
    collect.data.inputPlugs = [
      { id: "item-1", portName: "items" },
      { id: "item-2", portName: "items" },
    ];
    const ordinaryEdge = edge({
      id: "ordinary-edge",
      source: "other",
      target: ordinary.id,
    });
    const variadicEdge = edge({
      id: "variadic-edge",
      source: "other",
      target: variadic.id,
    });
    const plugEdge = edge({
      id: "plug-edge",
      source: "other",
      target: collect.id,
      targetPort: "items",
      targetPlug: "item-1",
    });

    expect(
      isConnectionAccepted(
        connection({
          source: source.id,
          sourcePort: "output",
          target: ordinary.id,
          targetPort: "input",
        }),
        [source, ordinary],
        [ordinaryEdge],
        [],
        [],
      ),
    ).toBe(false);
    expect(
      isConnectionAccepted(
        connection({
          source: source.id,
          sourcePort: "output",
          target: variadic.id,
          targetPort: "input",
        }),
        [source, variadic],
        [variadicEdge],
        [],
        [],
      ),
    ).toBe(true);

    for (const [plugId, accepted] of [
      ["item-1", false],
      ["item-2", true],
    ] as const) {
      expect(
        isConnectionAccepted(
          connection({
            source: source.id,
            sourcePort: "output",
            target: collect.id,
            targetPort: "items",
            targetPlug: plugId,
          }),
          [source, collect],
          [plugEdge],
          [],
          [],
        ),
      ).toBe(accepted);
    }
  });

  it("excludes the edge being reconnected from cycle and occupancy checks", () => {
    const source = node("source", [], [port("output", "output", "one")]);
    const target = node("target", [port("input", "input", "one")], []);
    const currentEdge = edge({
      id: "current-edge",
      source: source.id,
      target: target.id,
    });
    const link = connection({
      source: source.id,
      sourcePort: "output",
      target: target.id,
      targetPort: "input",
    });

    expect(
      isConnectionAccepted(link, [source, target], [currentEdge], [], []),
    ).toBe(false);
    expect(
      isConnectionAccepted(
        link,
        [source, target],
        [currentEdge],
        [],
        [],
        currentEdge.id,
      ),
    ).toBe(true);

    const previousReverseEdge = edge({
      id: "previous-reverse",
      source: target.id,
      target: source.id,
    });
    expect(
      isConnectionAccepted(
        link,
        [source, target],
        [previousReverseEdge],
        [],
        [],
      ),
    ).toBe(false);
    expect(
      isConnectionAccepted(
        link,
        [source, target],
        [previousReverseEdge],
        [],
        [],
        previousReverseEdge.id,
      ),
    ).toBe(true);
  });
});
