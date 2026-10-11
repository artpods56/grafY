import { describe, expect, it } from "vitest";

import { applyGraphDiffToHead, sameCanonicalJson } from "./graph-diff";
import type { GraphDiff } from "./protocol";
import type { CollaborativeHead } from "@/lib/api";

type NodeEntity = NonNullable<GraphDiff["nodes"][string]["after"]>;
type EdgeEntity = NonNullable<GraphDiff["edges"][string]["after"]>;
type OriginEntity = NonNullable<GraphDiff["origins"][string]["after"]>;
type ViewerEntity = NonNullable<GraphDiff["viewers"][string]["after"]>;
type LinkEntity = NonNullable<GraphDiff["links"][string]["after"]>;

const GRAPH_ID = "11111111-1111-4111-8111-111111111111";
const ROOM_EPOCH = "33333333-3333-4333-8333-333333333333";

function node(id: string, x = 0): NodeEntity {
  return {
    id,
    kind: "builtin",
    operator_id: "demo.op",
    operator_version: 1,
    position: { x, y: 0 },
    input_plugs: [],
    artifact_type_bindings: [],
  };
}

function edge(id: string, fromNode: string, toNode: string): EdgeEntity {
  return {
    id,
    collection_mode: "direct",
    conversion_path: [],
    enabled: true,
    from_node: fromNode,
    from_port: "out",
    to_node: toNode,
    to_port: "in",
  };
}

function origin(id: string, toNode: string): OriginEntity {
  return {
    id,
    collection_mode: "direct",
    conversion_path: [],
    to_node: toNode,
    to_port: "in",
    value: {
      artifact_id: "55555555-5555-4555-8555-555555555555",
      artifact_type: "table.data",
      schema_version: 1,
    },
  };
}

function viewer(id: string, x = 0): ViewerEntity {
  return { id, position: { x, y: 0 } };
}

function link(
  id: string,
  sourceNodeId: string,
  targetViewerId: string,
): LinkEntity {
  return {
    id,
    source_node_id: sourceNodeId,
    source_port_name: "out",
    target_viewer_id: targetViewerId,
  };
}

function headWith(
  document: Partial<CollaborativeHead["document"]> = {},
  name = "Room graph",
): CollaborativeHead {
  return {
    graph_id: GRAPH_ID,
    room_epoch: ROOM_EPOCH,
    collaboration_sequence: 4,
    checkpoint_sequence: 1,
    checkpoint_revision: 1,
    name,
    updated_at: "2026-08-07T10:00:00Z",
    document: {
      schema_version: 7,
      nodes: [],
      edges: [],
      origins: [],
      presentation: { viewers: [], links: [], bindings: [], annotations: [] },
      ...document,
    },
  };
}

function diffWith(overrides: Partial<GraphDiff> = {}): GraphDiff {
  return {
    name: null,
    nodes: {},
    edges: {},
    origins: {},
    viewers: {},
    links: {},
    bindings: {},
    annotations: {},
    ...overrides,
  };
}

function changed<T>(before: T | null, after: T | null) {
  return { before, after };
}

describe("applyGraphDiffToHead", () => {
  it("appends inserted entities in the diff's key order", () => {
    const head = headWith({ nodes: [node("a")] });

    const next = applyGraphDiffToHead(
      head,
      diffWith({
        nodes: {
          b: changed(null, node("b")),
          c: changed(null, node("c")),
        },
      }),
      5,
    );

    expect(next.document.nodes.map((item) => item.id)).toEqual(["a", "b", "c"]);
  });

  it("replaces a changed entity where it already sits", () => {
    const head = headWith({ nodes: [node("a"), node("b"), node("c")] });

    const next = applyGraphDiffToHead(
      head,
      diffWith({ nodes: { b: changed(node("b"), node("b", 90)) } }),
      5,
    );

    expect(next.document.nodes.map((item) => item.id)).toEqual(["a", "b", "c"]);
    expect(next.document.nodes[1]?.position).toEqual({ x: 90, y: 0 });
    expect(next.document.nodes[0]).toBe(head.document.nodes[0]);
  });

  it("drops an entity whose after is null", () => {
    const head = headWith({ nodes: [node("a"), node("b")] });

    const next = applyGraphDiffToHead(
      head,
      diffWith({ nodes: { a: changed(node("a"), null) } }),
      5,
    );

    expect(next.document.nodes.map((item) => item.id)).toEqual(["b"]);
  });

  it("applies a cascade diff that removes a node with its edge, origin, and link", () => {
    const head = headWith({
      nodes: [node("gone"), node("stays")],
      edges: [edge("e1", "gone", "stays")],
      origins: [origin("o1", "stays")],
      presentation: {
        viewers: [viewer("v1")],
        links: [link("l1", "gone", "v1")],
        bindings: [],
        annotations: [],
      },
    });

    const next = applyGraphDiffToHead(
      head,
      diffWith({
        nodes: { gone: changed(node("gone"), null) },
        edges: { e1: changed(edge("e1", "gone", "stays"), null) },
        origins: { o1: changed(origin("o1", "stays"), null) },
        links: { l1: changed(link("l1", "gone", "v1"), null) },
      }),
      5,
    );

    expect(next.document.nodes.map((item) => item.id)).toEqual(["stays"]);
    expect(next.document.edges).toEqual([]);
    expect(next.document.origins).toEqual([]);
    expect(next.document.presentation?.links).toEqual([]);
    expect(next.document.presentation?.viewers.map((item) => item.id)).toEqual([
      "v1",
    ]);
  });

  it("changes the name only when the diff carries one", () => {
    const head = headWith({}, "Room graph");

    expect(applyGraphDiffToHead(head, diffWith(), 5).name).toBe("Room graph");
    expect(
      applyGraphDiffToHead(
        head,
        diffWith({ name: { before: "Room graph", after: "Renamed" } }),
        5,
      ).name,
    ).toBe("Renamed");
  });

  it("sets the collaboration sequence and leaves other head fields alone", () => {
    const head = headWith({}, "Room graph");

    const next = applyGraphDiffToHead(head, diffWith(), 12);

    expect(next).toMatchObject({
      graph_id: GRAPH_ID,
      room_epoch: ROOM_EPOCH,
      collaboration_sequence: 12,
      checkpoint_sequence: 1,
      checkpoint_revision: 1,
      updated_at: "2026-08-07T10:00:00Z",
    });
    expect(head.collaboration_sequence).toBe(4);
  });

  it("treats entity ids that name Object members as ordinary keys", () => {
    const head = headWith({ nodes: [node("toString")] });

    const next = applyGraphDiffToHead(
      head,
      diffWith({ nodes: { constructor: changed(null, node("constructor")) } }),
      5,
    );

    // The head item whose id names an inherited member is untouched because it
    // is not in the diff, and "constructor" still inserts.
    expect(next.document.nodes.map((item) => item.id)).toEqual([
      "toString",
      "constructor",
    ]);
  });

  it("leaves an entity alone when the diff only mentions other ids", () => {
    const head = headWith({ nodes: [node("toString"), node("a")] });

    const next = applyGraphDiffToHead(
      head,
      diffWith({ nodes: { a: changed(node("a"), node("a", 7)) } }),
      5,
    );

    expect(next.document.nodes[0]).toBe(head.document.nodes[0]);
    expect(next.document.nodes[1]?.position).toEqual({ x: 7, y: 0 });
  });

  it("fills an empty presentation the diff does not mention", () => {
    const head = headWith({
      presentation: {
        viewers: [viewer("v1")],
        links: [],
        bindings: [],
        annotations: [],
      },
    });

    const next = applyGraphDiffToHead(head, diffWith({ edges: {} }), 5);

    expect(next.document.presentation?.viewers.map((item) => item.id)).toEqual([
      "v1",
    ]);
  });
});

describe("sameCanonicalJson", () => {
  it("ignores object key order", () => {
    expect(
      sameCanonicalJson(
        { id: "a", position: { x: 1, y: 2 }, config: { a: 1, b: [2, 3] } },
        { config: { b: [2, 3], a: 1 }, position: { y: 2, x: 1 }, id: "a" },
      ),
    ).toBe(true);
  });

  it("drops undefined members the way JSON does", () => {
    expect(sameCanonicalJson({ id: "a", extra: undefined }, { id: "a" })).toBe(
      true,
    );
  });

  it("keeps number and string apart", () => {
    expect(sameCanonicalJson({ v: 1 }, { v: "1" })).toBe(false);
  });

  it("keeps array order meaningful", () => {
    expect(sameCanonicalJson({ v: [1, 2] }, { v: [2, 1] })).toBe(false);
  });
});
