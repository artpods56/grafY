import { describe, expect, it } from "vitest";

import { encodeHandleId, type ConnectionRoute } from "../canvas/handles";
import { createWorkflowNodeData, type WorkflowEdge } from "../canvas/types";
import type { NodeSpec, Port } from "@/lib/api";
import {
  collectionModeForConnection,
  connectionRouteDescription,
  connectionRouteTitle,
  inputPlugBindingsForNode,
  isConnectionAccepted,
  mappedInputPortForNode,
  nodeAndDescendantIds,
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

function handle(
  portName: string,
  direction: "input" | "output",
  shape: "one" | "many",
  plugId?: string,
  artifactTypeId = "scalar.text",
): string {
  return encodeHandleId({
    portName,
    artifactTypeId,
    schemaVersion: 1,
    shape,
    direction,
    ...(plugId ? { plugId } : {}),
  });
}

function edge({
  id,
  source,
  target,
  sourcePort = "output",
  sourceShape = "one",
  targetPort = "input",
  targetShape = "one",
  targetPlugId,
  enabled = true,
  collectionMode = "direct",
}: {
  id: string;
  source: string;
  target: string;
  sourcePort?: string;
  sourceShape?: "one" | "many";
  targetPort?: string;
  targetShape?: "one" | "many";
  targetPlugId?: string;
  enabled?: boolean;
  collectionMode?: "direct" | "map";
}): WorkflowEdge {
  return {
    id,
    source,
    sourceHandle: handle(sourcePort, "output", sourceShape),
    target,
    targetHandle: handle(targetPort, "input", targetShape, targetPlugId),
    data: {
      enabled,
      collectionMode,
      conversionPath: [],
    },
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

    expect(connectionRouteTitle(route)).toBe(
      "Age → Integer to text · scalar.text@1",
    );
    expect(connectionRouteDescription("payload", route)).toBe(
      "payload.profile.age → Integer to text · builtin.scalar.integer_to_text@1",
    );
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
      sourceShape: "many",
      targetPort: "mapped",
      enabled: false,
      collectionMode: "map",
    });
    const connection = {
      source: source.id,
      sourceHandle: handle("result", "output", "one"),
      target: target.id,
      targetHandle: handle("input", "input", "one"),
    };

    expect(mappedInputPortForNode(source.id, [disabledMapEdge])).toBeNull();
    expect(mappedInputPortForNode(source.id, [disabledMapEdge], true)).toBe(
      "mapped",
    );
    expect(
      collectionModeForConnection(
        connection,
        [source, target],
        [disabledMapEdge],
      ),
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
        {
          source: source.id,
          sourceHandle: handle("output", "output", "many"),
          target: target.id,
          targetHandle: handle("input", "input", "one"),
        },
        [source, target],
        [],
      ),
    ).toBe("direct");
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
        {
          source: source.id,
          sourceHandle: handle("output", "output", "many"),
          target: target.id,
          targetHandle: handle("items", "input", "one", "item-1"),
        },
        [source, target],
        [],
      ),
    ).toBeNull();
  });
});

describe("connection acceptance policy", () => {
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
        {
          source: source.id,
          sourceHandle: handle("output", "output", "one"),
          target: target.id,
          targetHandle: handle("input", "input", "one"),
        },
        [source, target],
        [],
        [],
        [],
      ),
    ).toBe(true);
    expect(
      isConnectionAccepted(
        {
          source: source.id,
          sourceHandle: handle("output", "output", "one"),
          target: incompatibleTarget.id,
          targetHandle: handle(
            "input",
            "input",
            "one",
            undefined,
            "scalar.integer",
          ),
        },
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
    const sourceHandle = handle("output", "output", "one");

    for (const targetHandle of [
      handle("items", "input", "one"),
      handle("items", "input", "one", "missing"),
    ]) {
      expect(
        isConnectionAccepted(
          {
            source: source.id,
            sourceHandle,
            target: collect.id,
            targetHandle,
          },
          [source, collect],
          [],
          [],
          [],
        ),
      ).toBe(false);
    }

    expect(
      isConnectionAccepted(
        {
          source: source.id,
          sourceHandle,
          target: collect.id,
          targetHandle: handle("items", "input", "one", "item-1"),
        },
        [source, collect],
        [],
        [],
        [],
      ),
    ).toBe(true);
    expect(
      isConnectionAccepted(
        {
          source: source.id,
          sourceHandle,
          target: ordinary.id,
          targetHandle: handle("input", "input", "one", "item-1"),
        },
        [source, ordinary],
        [],
        [],
        [],
      ),
    ).toBe(false);
  });

  it("allows only one map driver for a node", () => {
    const source = node("source", [], [port("output", "output", "many")]);
    const target = node(
      "target",
      [
        port("driver", "input", "one"),
        port("candidate", "input", "one", { variadic: true }),
      ],
      [],
    );
    const existingMapDriver = edge({
      id: "existing-map",
      source: "other-source",
      target: target.id,
      sourceShape: "many",
      targetPort: "driver",
      collectionMode: "map",
      enabled: false,
    });

    expect(
      isConnectionAccepted(
        {
          source: source.id,
          sourceHandle: handle("output", "output", "many"),
          target: target.id,
          targetHandle: handle("candidate", "input", "one"),
        },
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
        {
          source: source.id,
          sourceHandle: handle("output", "output", "one"),
          target: target.id,
          targetHandle: handle("input", "input", "one"),
        },
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
      targetPlugId: "item-1",
    });
    const sourceHandle = handle("output", "output", "one");

    expect(
      isConnectionAccepted(
        {
          source: source.id,
          sourceHandle,
          target: ordinary.id,
          targetHandle: handle("input", "input", "one"),
        },
        [source, ordinary],
        [ordinaryEdge],
        [],
        [],
      ),
    ).toBe(false);
    expect(
      isConnectionAccepted(
        {
          source: source.id,
          sourceHandle,
          target: variadic.id,
          targetHandle: handle("input", "input", "one"),
        },
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
          {
            source: source.id,
            sourceHandle,
            target: collect.id,
            targetHandle: handle("items", "input", "one", plugId),
          },
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
    const connection = {
      source: source.id,
      sourceHandle: handle("output", "output", "one"),
      target: target.id,
      targetHandle: handle("input", "input", "one"),
    };

    expect(
      isConnectionAccepted(connection, [source, target], [currentEdge], [], []),
    ).toBe(false);
    expect(
      isConnectionAccepted(
        connection,
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
        connection,
        [source, target],
        [previousReverseEdge],
        [],
        [],
      ),
    ).toBe(false);
    expect(
      isConnectionAccepted(
        connection,
        [source, target],
        [previousReverseEdge],
        [],
        [],
        previousReverseEdge.id,
      ),
    ).toBe(true);
  });
});

describe("input-plug binding presentation", () => {
  it("describes active contributions and omits disabled plug edges", () => {
    const source = node(
      "source_node",
      [],
      [port("output", "output", "one", { title: "Result" })],
    );
    const collect = node(
      "collect",
      [
        port("items", "input", "one", {
          accepted_shapes: ["one", "many"],
          instance_plugs: true,
        }),
      ],
      [port("items", "output", "many")],
    );
    collect.data.inputPlugs = [
      { id: "active", portName: "items" },
      { id: "disabled", portName: "items" },
    ];
    collect.data.run = {
      node_id: collect.id,
      status: "succeeded",
      error: null,
      outputs: [
        {
          port: "items",
          kind: "sequence",
          artifacts: [],
          value: {
            artifact_type: "scalar.text",
            schema_version: 1,
            item_refs: [],
            ordered: true,
            index_key: "order_index",
            metadata: {
              collect_segments: [
                {
                  input_index: 0,
                  start_index: 0,
                  item_count: 2,
                  source_kind: "sequence",
                },
              ],
            },
          },
        },
      ],
    };
    const active = edge({
      id: "active-edge",
      source: source.id,
      target: collect.id,
      targetPort: "items",
      targetPlugId: "active",
    });
    active.data = {
      ...active.data,
      enabled: true,
      collectionMode: "direct",
      projection: { path: ["body"] },
      conversionPath: [{ id: "normalize_text", version: 2 }],
    };
    const disabled = edge({
      id: "disabled-edge",
      source: source.id,
      target: collect.id,
      targetPort: "items",
      targetPlugId: "disabled",
      enabled: false,
    });

    expect(
      inputPlugBindingsForNode(
        collect,
        [source, collect],
        [active, disabled],
        [
          {
            key: { id: "normalize_text", version: 2 },
            title: "Normalize text",
          },
        ],
        [
          {
            key: { id: "scalar.text", schema_version: 1 },
            title: "Text",
            bundle: { format: "inline-json", version: 1 },
            payload_schema: {},
            field_projections: [
              {
                path: ["body"],
                target_artifact_type: {
                  id: "scalar.text",
                  schema_version: 1,
                },
                title: "Body",
              },
            ],
          },
        ],
      ),
    ).toEqual({
      active: {
        sourceLabel: "source node · Result",
        sourceShape: "one",
        conversionLabel: "Body → Normalize text",
        contributionLabel: "output 1–2",
      },
    });
  });
});

describe("authoring invalidation traversal", () => {
  it("follows active descendants, ignores disabled branches, and tolerates cycles", () => {
    const edges = [
      edge({ id: "root-active", source: "root", target: "active" }),
      edge({
        id: "root-disabled",
        source: "root",
        target: "disabled",
        enabled: false,
      }),
      edge({ id: "active-leaf", source: "active", target: "leaf" }),
      edge({ id: "cycle", source: "leaf", target: "root" }),
    ];

    expect([...nodeAndDescendantIds("root", edges)]).toEqual([
      "root",
      "active",
      "leaf",
    ]);
  });
});
