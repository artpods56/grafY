import { describe, expect, it } from "vitest";

import type { CreateSavedGraphRequest, SavedGraphDocument } from "@/lib/api";
import {
  applyGraphCommand,
  authoredGraphDocument,
  createSavedGraphRequest,
  executionInvalidatedNodeIds,
  type AuthoredGraphDocument,
} from "./graph-document";

const node = (id: string) => ({
  id,
  kind: "builtin" as const,
  operator_id: `test.${id}`,
  operator_version: 1,
  config: { label: id },
  input_plugs: [],
  artifact_type_bindings: [],
  plugin_release_pin: null,
  position: { x: 0, y: 0 },
  layout: null,
});

const edge = {
  id: "edge-1",
  from_node: "source",
  from_port: "output",
  to_node: "target",
  to_port: "input",
  to_plug: null,
  enabled: true,
  collection_mode: "direct" as const,
  projection: null,
  conversion_path: [],
  route_offset: null,
};

function document(): AuthoredGraphDocument {
  return authoredGraphDocument(createSavedGraphRequest({
    name: "Draft",
    nodes: [node("source"), node("target")],
    edges: [edge],
    origins: [],
  }));
}

describe("authored graph document", () => {
  it("round-trips only saved graph fields", () => {
    const value = document();
    const request = createSavedGraphRequest(value);

    expect(request).toEqual({
      name: value.name,
      document: {
        schema_version: 7,
        nodes: value.nodes,
        edges: value.edges,
        origins: [],
        presentation: {
          viewers: [],
          links: [],
          bindings: [],
          annotations: [],
        },
      },
    });
    expect(JSON.stringify(value)).not.toContain("callback");
    expect(JSON.stringify(value)).not.toContain("selection");
    expect(JSON.stringify(value)).not.toContain("viewport");
    expect(JSON.stringify(value)).not.toContain("privateFieldDraft");
    expect(JSON.stringify(value)).not.toContain("presence");
    expect(JSON.stringify(value)).not.toContain("execution");
  });

  it("round-trips the complete normalized durable graph payload", () => {
    const input: CreateSavedGraphRequest = {
      name: "Operator-agnostic graph",
      document: {
        schema_version: 7,
        nodes: [
          {
            id: "legacy-node",
            kind: "builtin",
            operator_id: "unavailable.operator",
            operator_version: 7,
            config: {
              nested: {
                ordered: ["first", { value: 2 }],
                arbitrary: true,
              },
            },
            input_plugs: [
              { id: "plug-first", port: "items" },
              { id: "plug-second", port: "items" },
            ],
            artifact_type_bindings: [
              {
                variable: "Z",
                artifact_type: { id: "artifact.z", schema_version: 3 },
              },
              {
                variable: "A",
                artifact_type: { id: "artifact.a", schema_version: 1 },
              },
            ],
            position: { x: 120, y: 240 },
            layout: { width: 420, body_height: 180, appendix_height: 320 },
          },
        ],
        edges: [
          {
            id: "legacy-edge",
            from_node: "legacy-node",
            from_port: "output",
            to_node: "target-node",
            to_port: "items",
            to_plug: "plug-second",
            enabled: false,
            collection_mode: "map",
            projection: { path: ["properties", "value"] },
            conversion_path: [
              { id: "convert-a", version: 1 },
              { id: "convert-b", version: 2 },
            ],
            route_offset: { x: 18, y: -6 },
          },
        ],
        origins: [],
        presentation: {
          viewers: [],
          links: [],
          bindings: [],
          annotations: [],
        },
      },
    };

    const canonical = authoredGraphDocument(input);

    expect(createSavedGraphRequest(canonical)).toEqual({
      name: "Operator-agnostic graph",
      document: {
        schema_version: 7,
        nodes: [
        {
          id: "legacy-node",
          kind: "builtin",
          operator_id: "unavailable.operator",
          operator_version: 7,
          config: {
            nested: {
              ordered: ["first", { value: 2 }],
              arbitrary: true,
            },
          },
          input_plugs: [
            { id: "plug-first", port: "items" },
            { id: "plug-second", port: "items" },
          ],
          artifact_type_bindings: [
            {
              variable: "Z",
              artifact_type: { id: "artifact.z", schema_version: 3 },
            },
            {
              variable: "A",
              artifact_type: { id: "artifact.a", schema_version: 1 },
            },
          ],
          plugin_release_pin: null,
          position: { x: 120, y: 240 },
          layout: { width: 420, body_height: 180, appendix_height: 320 },
        },
        ],
        edges: [
        {
          id: "legacy-edge",
          from_node: "legacy-node",
          from_port: "output",
          to_node: "target-node",
          to_port: "items",
          to_plug: "plug-second",
          enabled: false,
          collection_mode: "map",
          projection: { path: ["properties", "value"] },
          conversion_path: [
            { id: "convert-a", version: 1 },
            { id: "convert-b", version: 2 },
          ],
          route_offset: { x: 18, y: -6 },
        },
        ],
        origins: [],
        presentation: {
          viewers: [],
          links: [],
          bindings: [],
          annotations: [],
        },
      },
    });
  });

  it("projects adversarial React Flow runtime fields at both durable boundaries", () => {
    const runtimeNode = {
      ...node("source"),
      config: { nested: { result: "legitimate config content" } },
      selected: true,
      width: 480,
      height: 220,
      internals: { handleBounds: { source: [] } },
      onConfigChange: () => undefined,
      execution: { status: "failed" },
      progress: { entries: [] },
      run: { status: "succeeded" },
      result: { payload: "runtime result" },
      presence: { userId: "other-user" },
      privateFieldDraft: "draft-only value",
    };
    const runtimeEdge = {
      ...edge,
      selected: true,
      sourceX: 480,
      sourceY: 220,
      internals: { z: 1 },
      onUpdate: () => undefined,
      execution: { status: "failed" },
      progress: { entries: [] },
      run: { status: "succeeded" },
      result: { payload: "runtime result" },
      presence: { userId: "other-user" },
      privateFieldDraft: "draft-only value",
    };
    const input: CreateSavedGraphRequest = {
      name: "Adversarial graph",
      document: {
        schema_version: 7,
        nodes: [
          runtimeNode as unknown as SavedGraphDocument["nodes"][number],
        ],
        edges: [
          runtimeEdge as unknown as SavedGraphDocument["edges"][number],
        ],
        origins: [],
        presentation: {
          viewers: [],
          links: [],
          bindings: [],
          annotations: [],
        },
      },
    };

    const canonical = authoredGraphDocument(input);
    const request = createSavedGraphRequest(canonical);
    const serialized = JSON.stringify({ canonical, request });

    expect(canonical.nodes[0]?.config).toEqual({
      nested: { result: "legitimate config content" },
    });
    expect(canonical.nodes[0]).not.toHaveProperty("selected");
    expect(canonical.nodes[0]).not.toHaveProperty("internals");
    expect(canonical.nodes[0]).not.toHaveProperty("onConfigChange");
    expect(canonical.nodes[0]).not.toHaveProperty("execution");
    expect(canonical.edges[0]).not.toHaveProperty("sourceX");
    expect(canonical.edges[0]).not.toHaveProperty("onUpdate");
    expect(canonical.edges[0]).not.toHaveProperty("presence");
    expect(serialized).not.toContain("runtime result");
    expect(serialized).not.toContain("draft-only value");
    expect(serialized).not.toContain("other-user");
  });

  it("projects cloneable runtime fields at every structural command boundary", () => {
    const runtimeFields = [
      "selected",
      "execution",
      "dimensions",
      "internals",
      "callbackLike",
      "progress",
      "run",
      "result",
      "presence",
      "privateFieldDraft",
    ];
    const expectNoRuntimeFields = (value: object) => {
      for (const field of runtimeFields) {
        expect(value).not.toHaveProperty(field);
      }
    };
    const runtimeNode = {
      ...node("added-node"),
      selected: true,
      execution: { status: "failed" },
      dimensions: { width: 480, height: 220 },
      internals: { handleBounds: { source: [] } },
      callbackLike: { name: "onConfigChange" },
      progress: { entries: [] },
      run: { status: "succeeded" },
      result: { payload: "runtime result" },
      presence: { userId: "other-user" },
      privateFieldDraft: "draft-only value",
      layout: {
        width: 480,
        body_height: 220,
        appendix_height: 80,
        selected: true,
        internals: { measured: true },
      },
      input_plugs: [
        {
          id: "added-plug",
          port: "items",
          selected: true,
          callbackLike: { name: "onPlugChange" },
        },
      ],
      artifact_type_bindings: [
        {
          variable: "T",
          artifact_type: {
            id: "artifact.t",
            schema_version: 2,
            selected: true,
            execution: { status: "failed" },
          },
        },
      ],
    };
    const runtimeEdge = {
      ...edge,
      id: "added-edge",
      selected: true,
      dimensions: { width: 480, height: 220 },
      internals: { sourceX: 1 },
      callbackLike: { name: "onEdgeChange" },
      execution: { status: "failed" },
      progress: { entries: [] },
      run: { status: "succeeded" },
      result: { payload: "runtime result" },
      presence: { userId: "other-user" },
      privateFieldDraft: "draft-only value",
      projection: { path: ["value"], selected: true },
      conversion_path: [{ id: "convert", version: 1, selected: true }],
      route_offset: { x: 4, y: 8, selected: true },
    };

    let result = applyGraphCommand(document(), {
      kind: "add_node",
      node: runtimeNode as never,
    });
    const addedNode = result.nodes.find(
      (candidate) => candidate.id === "added-node",
    );
    expect(addedNode).toBeDefined();
    expectNoRuntimeFields(addedNode as object);
    expect(addedNode?.layout).toEqual({
      width: 480,
      body_height: 220,
      appendix_height: 80,
    });
    expect(addedNode?.input_plugs).toEqual([
      { id: "added-plug", port: "items" },
    ]);
    expect(addedNode?.artifact_type_bindings).toEqual([
      {
        variable: "T",
        artifact_type: { id: "artifact.t", schema_version: 2 },
      },
    ]);
    expectNoRuntimeFields(addedNode?.layout as object);
    expectNoRuntimeFields(addedNode?.input_plugs?.[0] as object);
    expectNoRuntimeFields(addedNode?.artifact_type_bindings?.[0] as object);
    expectNoRuntimeFields(
      addedNode?.artifact_type_bindings?.[0]?.artifact_type as object,
    );

    result = applyGraphCommand(result, {
      kind: "add_edge",
      edge: runtimeEdge as never,
    });
    const addedEdge = result.edges.find(
      (candidate) => candidate.id === "added-edge",
    );
    expect(addedEdge).toBeDefined();
    expectNoRuntimeFields(addedEdge as object);
    expect(addedEdge?.projection).toEqual({ path: ["value"] });
    expect(addedEdge?.conversion_path).toEqual([{ id: "convert", version: 1 }]);
    expect(addedEdge?.route_offset).toEqual({ x: 4, y: 8 });
    expectNoRuntimeFields(addedEdge?.projection as object);
    expectNoRuntimeFields(addedEdge?.conversion_path?.[0] as object);
    expectNoRuntimeFields(addedEdge?.route_offset as object);

    result = applyGraphCommand(result, {
      kind: "update_edge",
      edge_id: "edge-1",
      update: {
        projection: { path: ["updated"], selected: true } as never,
        conversion_path: [
          { id: "updated", version: 2, execution: { status: "failed" } },
        ] as never,
        route_offset: { x: 12, y: 14, dimensions: { width: 2 } } as never,
        enabled: false,
      },
    });
    const updatedEdge = result.edges.find(
      (candidate) => candidate.id === "edge-1",
    );
    expect(updatedEdge?.projection).toEqual({ path: ["updated"] });
    expect(updatedEdge?.conversion_path).toEqual([
      { id: "updated", version: 2 },
    ]);
    expect(updatedEdge?.route_offset).toEqual({ x: 12, y: 14 });
    expectNoRuntimeFields(updatedEdge as object);
    expectNoRuntimeFields(updatedEdge?.projection as object);
    expectNoRuntimeFields(updatedEdge?.conversion_path?.[0] as object);
    expectNoRuntimeFields(updatedEdge?.route_offset as object);

    result = applyGraphCommand(result, {
      kind: "update_node_layout",
      node_id: "source",
      layout: {
        width: 500,
        body_height: 240,
        appendix_height: 90,
        selected: true,
        callbackLike: { name: "onLayoutChange" },
      } as never,
    });
    result = applyGraphCommand(result, {
      kind: "add_input_plug",
      node_id: "source",
      plug: {
        id: "source-plug",
        port: "items",
        dimensions: { width: 1 },
        callbackLike: { name: "onPlugChange" },
      } as never,
    });
    result = applyGraphCommand(result, {
      kind: "bind_artifact_type",
      node_id: "source",
      variable: "Bound",
      artifact_type: {
        id: "artifact.bound",
        schema_version: 4,
        selected: true,
        presence: { userId: "other-user" },
      } as never,
    });
    result = applyGraphCommand(result, {
      kind: "update_node_configuration_and_input_plugs",
      node_id: "source",
      config: { nested: { arbitrary: "content" } },
      input_plugs: [
        {
          id: "compound-plug",
          port: "items",
          selected: true,
          execution: { status: "failed" },
        },
      ] as never,
    });
    const source = result.nodes.find((candidate) => candidate.id === "source");
    expect(source?.layout).toEqual({
      width: 500,
      body_height: 240,
      appendix_height: 90,
    });
    expect(source?.input_plugs).toEqual([
      { id: "compound-plug", port: "items" },
    ]);
    expect(source?.artifact_type_bindings).toContainEqual({
      variable: "Bound",
      artifact_type: { id: "artifact.bound", schema_version: 4 },
    });
    expectNoRuntimeFields(source?.layout as object);
    expectNoRuntimeFields(source?.input_plugs?.[0] as object);
    expectNoRuntimeFields(
      source?.artifact_type_bindings?.find(
        (binding) => binding.variable === "Bound",
      ) as object,
    );

    const replacement = {
      name: "Replacement",
      nodes: [runtimeNode],
      edges: [runtimeEdge],
    };
    result = applyGraphCommand(result, {
      kind: "replace_document",
      document: replacement as never,
    });
    expectNoRuntimeFields(result.nodes[0] as object);
    expectNoRuntimeFields(result.nodes[0]?.layout as object);
    expectNoRuntimeFields(result.nodes[0]?.input_plugs?.[0] as object);
    expectNoRuntimeFields(
      result.nodes[0]?.artifact_type_bindings?.[0] as object,
    );
    expectNoRuntimeFields(
      result.nodes[0]?.artifact_type_bindings?.[0]?.artifact_type as object,
    );
    expectNoRuntimeFields(result.edges[0] as object);
    expectNoRuntimeFields(result.edges[0]?.projection as object);
    expectNoRuntimeFields(result.edges[0]?.conversion_path?.[0] as object);
    expectNoRuntimeFields(result.edges[0]?.route_offset as object);
  });

  it("applies a compound node removal and its incident edges atomically", () => {
    const result = applyGraphCommand(document(), {
      kind: "remove_nodes",
      node_ids: ["source"],
    });

    expect(result.nodes.map((candidate) => candidate.id)).toEqual(["target"]);
    expect(result.edges).toEqual([]);
  });

  it("updates configuration and layout without mutating the input document", () => {
    const original = document();
    const updated = applyGraphCommand(original, {
      kind: "update_node_configuration",
      node_id: "source",
      field: "label",
      value: "new label",
    });
    const laidOut = applyGraphCommand(updated, {
      kind: "update_node_layout",
      node_id: "source",
      layout: { width: 420, body_height: null, appendix_height: null },
    });

    expect(original.nodes[0]?.config).toEqual({ label: "source" });
    expect(laidOut.nodes[0]?.config).toEqual({ label: "new label" });
    expect(laidOut.nodes[0]?.layout).toEqual({
      width: 420,
      body_height: null,
      appendix_height: null,
    });
  });

  it("changes edge transport through a typed semantic command", () => {
    const result = applyGraphCommand(document(), {
      kind: "update_edge",
      edge_id: "edge-1",
      update: { enabled: false, collection_mode: "map" },
    });

    expect(result.edges[0]).toMatchObject({
      id: "edge-1",
      enabled: false,
      collection_mode: "map",
    });
  });

  it("adds, updates, and removes an origin through typed semantic commands", () => {
    const added = applyGraphCommand(document(), {
      kind: "add_origin",
      origin: {
        id: "origin-1",
        to_node: "target",
        to_port: "input",
        to_plug: null,
        value: {
          artifact_id: "00000000-0000-4000-8000-000000000001",
          artifact_type: "scalar.text",
          schema_version: 1,
        },
        conversion_path: [],
      },
    });

    expect(added.origins).toEqual([
      {
        id: "origin-1",
        to_node: "target",
        to_port: "input",
        to_plug: null,
        value: {
          artifact_id: "00000000-0000-4000-8000-000000000001",
          artifact_type: "scalar.text",
          schema_version: 1,
        },
        conversion_path: [],
      },
    ]);

    const updated = applyGraphCommand(added, {
      kind: "update_origin",
      origin_id: "origin-1",
      update: { conversion_path: [{ id: "text.normalize", version: 2 }] },
    });

    expect(updated.origins[0]?.conversion_path).toEqual([
      { id: "text.normalize", version: 2 },
    ]);

    const removed = applyGraphCommand(updated, {
      kind: "remove_origins",
      origin_ids: ["origin-1"],
    });

    expect(removed.origins).toEqual([]);
  });

  it("prunes origins that target a removed node", () => {
    const withOrigin = applyGraphCommand(document(), {
      kind: "add_origin",
      origin: {
        id: "origin-1",
        to_node: "target",
        to_port: "input",
        to_plug: null,
        value: {
          artifact_id: "00000000-0000-4000-8000-000000000001",
          artifact_type: "scalar.text",
          schema_version: 1,
        },
        conversion_path: [],
      },
    });

    const result = applyGraphCommand(withOrigin, {
      kind: "remove_nodes",
      node_ids: ["target"],
    });

    expect(result.origins).toEqual([]);
  });

  it("rejects origin commands that target a missing or duplicate origin", () => {
    expect(() =>
      applyGraphCommand(document(), {
        kind: "update_origin",
        origin_id: "missing-origin",
        update: { to_port: "other" },
      }),
    ).toThrow("missing origin missing-origin");

    const origin = {
      id: "origin-1",
      to_node: "target",
      to_port: "input",
      to_plug: null,
      value: {
        artifact_id: "00000000-0000-4000-8000-000000000001",
        artifact_type: "scalar.text",
        schema_version: 1,
      },
      conversion_path: [],
    };
    const withOrigin = applyGraphCommand(document(), {
      kind: "add_origin",
      origin,
    });

    expect(() =>
      applyGraphCommand(withOrigin, { kind: "add_origin", origin }),
    ).toThrow("duplicate origin origin-1");
  });

  it("moves only the selected exact Plugin release pin", () => {
    const original = authoredGraphDocument(createSavedGraphRequest({
      name: "Pinned Plugins",
      nodes: [
        {
          ...node("source"),
          plugin_release_pin: {
            scope: "system",
            slug: "notes",
            revision: 1,
          },
        },
        {
          ...node("target"),
          plugin_release_pin: {
            scope: "workspace",
            slug: "notes",
            revision: 4,
          },
        },
      ],
      edges: [edge],
      origins: [],
    }));

    const upgraded = applyGraphCommand(original, {
      kind: "update_node_plugin_release",
      node_id: "source",
      plugin_release: { scope: "system", slug: "notes", revision: 3 },
    });

    expect(original.nodes[0]?.plugin_release_pin).toEqual({
      scope: "system",
      slug: "notes",
      revision: 1,
    });
    expect(upgraded.nodes[0]?.plugin_release_pin).toEqual({
      scope: "system",
      slug: "notes",
      revision: 3,
    });
    expect(upgraded.nodes[1]).toEqual(original.nodes[1]);
    expect(
      executionInvalidatedNodeIds(original, {
        kind: "update_node_plugin_release",
        node_id: "source",
        plugin_release: { scope: "system", slug: "notes", revision: 3 },
      }),
    ).toEqual(new Set(["source", "target"]));
  });

  it("rejects an edge update for a missing edge", () => {
    expect(() =>
      applyGraphCommand(document(), {
        kind: "update_edge",
        edge_id: "missing-edge",
        update: { enabled: false },
      }),
    ).toThrow("missing edge missing-edge");
  });

  it("does not invalidate execution for a move, but scopes configuration invalidation", () => {
    const graph = document();
    const move = executionInvalidatedNodeIds(graph, {
      kind: "move_nodes",
      positions: [{ node_id: "source", x: 20, y: 30 }],
    });
    const targetEdit = executionInvalidatedNodeIds(graph, {
      kind: "update_node_configuration",
      node_id: "target",
      field: "label",
      value: "changed",
    });
    const bind = executionInvalidatedNodeIds(graph, {
      kind: "bind_artifact_type",
      node_id: "source",
      variable: "T",
      artifact_type: { id: "artifact.scalar", schema_version: 1 },
    });
    const reset = executionInvalidatedNodeIds(graph, {
      kind: "reset_artifact_type_binding",
      node_id: "source",
      variable: "T",
    });

    expect(move).toEqual(new Set());
    expect(targetEdit).toEqual(new Set(["target"]));
    expect(bind).toEqual(new Set(["source", "target"]));
    expect(reset).toEqual(new Set(["source", "target"]));
  });

  it("preserves edits when stale dispatchers apply sequentially", () => {
    let latest = document();
    const dispatchMove = () => {
      latest = applyGraphCommand(latest, {
        kind: "move_nodes",
        positions: [{ node_id: "source", x: 40, y: 50 }],
      });
    };
    const dispatchConfig = () => {
      latest = applyGraphCommand(latest, {
        kind: "update_node_configuration",
        node_id: "target",
        field: "label",
        value: "edited after move",
      });
    };

    dispatchMove();
    dispatchConfig();

    expect(latest.nodes).toEqual([
      { ...node("source"), position: { x: 40, y: 50 } },
      { ...node("target"), config: { label: "edited after move" } },
    ]);
  });
});
