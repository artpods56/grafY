import { describe, expect, it } from "vitest";

import {
  mergeArtifactViewerState,
  reconcileWithConfirmedHead,
} from "./workbench-room-reconcile";
import {
  artifactViewersFromPresentation,
  presentationFromArtifactViewers,
  type ArtifactViewerCanvasState,
  type GraphPresentation,
} from "../canvas/artifact-viewer";
import {
  authoredGraphDocument,
  type AuthoredGraphDocument,
} from "../model/graph-document";
import type { RoomGraphCommand } from "../room/protocol";
import type { CollaborativeHead } from "@/lib/api";

const GRAPH_ID = "11111111-1111-4111-8111-111111111111";
const ROOM_EPOCH = "33333333-3333-4333-8333-333333333333";

const EMPTY_PRESENTATION: GraphPresentation = {
  viewers: [],
  links: [],
  bindings: [],
  annotations: [],
};

function node(
  id: string,
  overrides: Partial<AuthoredGraphDocument["nodes"][number]> = {},
): AuthoredGraphDocument["nodes"][number] {
  return {
    id,
    kind: "builtin",
    operator_id: "demo.op",
    operator_version: 1,
    position: { x: 10, y: 20 },
    config: { threshold: 1 },
    input_plugs: [],
    artifact_type_bindings: [],
    ...overrides,
  };
}

function document(
  nodes: readonly AuthoredGraphDocument["nodes"][number][],
  name = "Room graph",
): AuthoredGraphDocument {
  return { name, nodes, edges: [], origins: [] };
}

/** The presentation the canvas hands over: what its cards round-trip into. */
function canvasPresentation(
  presentation: GraphPresentation = EMPTY_PRESENTATION,
): GraphPresentation {
  return presentationFromArtifactViewers(
    artifactViewersFromPresentation(presentation),
  );
}

function headWith(
  documentOverrides: Partial<CollaborativeHead["document"]> = {},
  headOverrides: Partial<CollaborativeHead> = {},
): CollaborativeHead {
  const authored = document([node("a")]);
  return {
    graph_id: GRAPH_ID,
    room_epoch: ROOM_EPOCH,
    collaboration_sequence: 4,
    checkpoint_sequence: 1,
    checkpoint_revision: 1,
    name: authored.name,
    updated_at: "2026-08-07T10:00:00Z",
    document: {
      schema_version: 7,
      nodes: authored.nodes,
      edges: [],
      origins: [],
      presentation: EMPTY_PRESENTATION,
      ...documentOverrides,
    },
    ...headOverrides,
  };
}

describe("reconcileWithConfirmedHead", () => {
  it("changes nothing when the head already shows the author's own edit", () => {
    const moved = node("a", { position: { x: 80, y: 90 } });
    const head = headWith({ nodes: [moved] });

    const reconciliation = reconcileWithConfirmedHead({
      head,
      pendingCommands: [],
      document: authoredGraphDocument(head),
      presentation: canvasPresentation(),
    });

    expect(reconciliation.document).toBeNull();
    expect(reconciliation.presentation).toBeNull();
  });

  it("adopts a peer's node move the local document does not hold yet", () => {
    const head = headWith({
      nodes: [node("a", { position: { x: 40, y: 50 } })],
    });

    const reconciliation = reconcileWithConfirmedHead({
      head,
      pendingCommands: [],
      document: document([node("a", { position: { x: 10, y: 20 } })]),
      presentation: canvasPresentation(),
    });

    expect(reconciliation.document?.nodes[0]?.position).toEqual({
      x: 40,
      y: 50,
    });
    expect(reconciliation.presentation).toBeNull();
  });

  it("keeps a pending local move while adopting a peer's rename", () => {
    const head = headWith({ nodes: [node("a")] }, { name: "Peer title" });
    const pending: readonly RoomGraphCommand[] = [
      { kind: "move_nodes", positions: [{ node_id: "a", x: 70, y: 80 }] },
    ];

    const reconciliation = reconcileWithConfirmedHead({
      head,
      pendingCommands: pending,
      // The author sees their own move under the name the peer already changed.
      document: document(
        [node("a", { position: { x: 70, y: 80 } })],
        "Old title",
      ),
      presentation: canvasPresentation(),
    });

    expect(reconciliation.document?.name).toBe("Peer title");
    expect(reconciliation.document?.nodes[0]?.position).toEqual({
      x: 70,
      y: 80,
    });
    expect(reconciliation.presentation).toBeNull();
  });

  it("corrects the optimistic document when the head applied a peer's config", () => {
    const head = headWith({ nodes: [node("a", { config: { threshold: 9 } })] });

    const reconciliation = reconcileWithConfirmedHead({
      head,
      // The author's own config command was rejected, so nothing is pending.
      pendingCommands: [],
      document: document([node("a", { config: { threshold: 1 } })]),
      presentation: canvasPresentation(),
    });

    expect(reconciliation.document?.nodes[0]?.config).toEqual({ threshold: 9 });
  });

  it("drops a card link whose node the head removed", () => {
    const head = headWith(
      {
        nodes: [],
        presentation: {
          viewers: [{ id: "card-1", position: { x: 5, y: 5 } }],
          links: [],
          bindings: [],
          annotations: [],
        },
      },
      { name: "Room graph" },
    );
    const heldPresentation: GraphPresentation = {
      viewers: [{ id: "card-1", position: { x: 5, y: 5 } }],
      links: [
        {
          id: "link-1",
          source_node_id: "a",
          source_port_name: "out",
          target_viewer_id: "card-1",
        },
      ],
      bindings: [],
      annotations: [],
    };

    const reconciliation = reconcileWithConfirmedHead({
      head,
      pendingCommands: [],
      // The canvas already dropped the node but still holds the card's link.
      document: document([]),
      presentation: canvasPresentation(heldPresentation),
    });

    expect(reconciliation.document).toBeNull();
    expect(reconciliation.presentation?.links).toEqual([]);
  });
});

describe("mergeArtifactViewerState", () => {
  function cardState(): ArtifactViewerCanvasState {
    return {
      nodes: [
        {
          id: "card-1",
          type: "grafyArtifactViewerNode",
          position: { x: 0, y: 0 },
          selected: true,
          width: 320,
          height: 240,
          data: { layout: null, mode: null },
        },
      ],
      edges: [],
      bindings: [],
      annotations: [],
    };
  }

  it("keeps React Flow fields on a card the new presentation also holds", () => {
    const current = cardState();
    const next: ArtifactViewerCanvasState = {
      nodes: [
        {
          id: "card-1",
          type: "grafyArtifactViewerNode",
          position: { x: 40, y: 60 },
          data: { layout: null, mode: "table" },
        },
      ],
      edges: [],
      bindings: [],
      annotations: [],
    };

    const merged = mergeArtifactViewerState(current, next);

    expect(merged.nodes[0]).toMatchObject({
      id: "card-1",
      position: { x: 40, y: 60 },
      selected: true,
      width: 320,
      height: 240,
    });
    expect(merged.nodes[0]?.data.mode).toBe("table");
  });

  it("adds new items, drops the ones the presentation let go, and takes bindings whole", () => {
    const current: ArtifactViewerCanvasState = {
      nodes: cardState().nodes,
      edges: [
        {
          id: "edge-1",
          type: "grafyArtifactViewerEdge",
          source: "a",
          target: "card-1",
          data: { sourcePortName: "out" },
        },
      ],
      bindings: [
        {
          id: "binding-1",
          sourceViewerId: "card-1",
          targetViewerId: "card-2",
          mappings: [],
          effects: ["filter"],
          emptySelection: "show_all",
        },
      ],
      annotations: [
        {
          id: "note-1",
          type: "grafyAnnotationNode",
          position: { x: 1, y: 1 },
          data: {
            kind: "text",
            layout: { width: 100, height: 40 },
            text: "held",
            color: "#475569",
          },
        },
      ],
    };
    const next: ArtifactViewerCanvasState = {
      nodes: [
        {
          id: "card-1",
          type: "grafyArtifactViewerNode",
          position: { x: 0, y: 0 },
          data: { layout: null, mode: null },
        },
        {
          id: "card-2",
          type: "grafyArtifactViewerNode",
          position: { x: 400, y: 0 },
          data: { layout: null, mode: null },
        },
      ],
      edges: [],
      bindings: [],
      annotations: [
        {
          id: "note-2",
          type: "grafyAnnotationNode",
          position: { x: 9, y: 9 },
          data: {
            kind: "text",
            layout: { width: 100, height: 40 },
            text: "new",
            color: "#475569",
          },
        },
      ],
    };

    const merged = mergeArtifactViewerState(current, next);

    expect(merged.nodes.map((item) => item.id)).toEqual(["card-1", "card-2"]);
    expect(merged.nodes[0]?.selected).toBe(true);
    expect(merged.nodes[1]?.selected).toBeUndefined();
    expect(merged.edges).toEqual([]);
    expect(merged.bindings).toEqual([]);
    expect(merged.annotations.map((item) => item.id)).toEqual(["note-2"]);
  });

  it("takes bindings from the incoming presentation", () => {
    const bindings = [
      {
        id: "binding-2",
        sourceViewerId: "card-1",
        targetViewerId: "card-2",
        mappings: [],
        effects: ["focus"],
        emptySelection: "show_all",
      },
    ] as ArtifactViewerCanvasState["bindings"];

    const merged = mergeArtifactViewerState(
      { ...cardState(), bindings: [] },
      { ...cardState(), bindings },
    );

    expect(merged.bindings).toEqual(bindings);
  });
});
