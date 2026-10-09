// @vitest-environment jsdom

import { act } from "react";
import * as React from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

import type { NodeSpec, Port } from "@/lib/api";
import { encodeHandleId } from "../canvas/handles";
import { reduceWorkbenchAuthoringState } from "../canvas/graph-document-adapter";
import {
  ARTIFACT_VIEWER_EDGE_TYPE,
  ARTIFACT_VIEWER_NODE_TYPE,
  presentationFromArtifactViewers,
  type ArtifactViewerCanvasState,
  type ArtifactViewerEdge,
  type ArtifactViewerNode,
  type GraphPresentation,
} from "../canvas/artifact-viewer";
import {
  WORKFLOW_NODE_TYPE,
  createWorkflowNodeData,
  portMetaForPort,
  type WorkflowEdge,
} from "../canvas/types";
import {
  authoredGraphDocument,
  createSavedGraphRequest,
  type AuthoredGraphDocument,
  type GraphCommand,
} from "../model/graph-document";
import { COLLECTION_OPERATOR_ID, COLLECTION_PORT } from "../model/collection";
import type { WorkflowNode } from "../model/execution-plan";
import { useArtifactCardCommands } from "./workbench-artifact-cards";
import { useCanvasSelection } from "./workbench-canvas-selection";
import {
  useArtifactViewerCommands,
  type ArtifactViewerRoomSync,
} from "./workbench-artifact-viewers";
import {
  useWorkbenchAuthoringCommands,
  type WorkbenchRoomCommandSync,
} from "./workbench-authoring-commands";

const IMAGE = { id: "file.png", schema_version: 1 };

function spec(
  operator_id: string,
  inputs: Port[],
  outputs: Port[],
  title = operator_id,
): NodeSpec {
  return {
    operator_id,
    operator_version: 1,
    plugin_slug: "test",
    origin: "builtin",
    title,
    description: title,
    catalog_visible: true,
    runnable: true,
    config_schema: {},
    input_schema: {},
    output_schema: {},
    inputs,
    outputs,
  };
}

const collectSpec = spec(
  COLLECTION_OPERATOR_ID,
  [
    {
      name: COLLECTION_PORT,
      title: "items",
      description: null,
      direction: "input",
      artifact_type: null,
      artifact_type_variable: "T",
      shape: "one",
      accepted_shapes: ["one", "many"],
      instance_plugs: true,
      variadic: true,
      required: true,
    },
  ],
  [
    {
      name: COLLECTION_PORT,
      title: "items",
      description: null,
      direction: "output",
      artifact_type: null,
      artifact_type_variable: "T",
      shape: "many",
      accepted_shapes: ["many"],
      instance_plugs: false,
      variadic: false,
      required: true,
    },
  ],
  "Collect",
);

const resizeSpec = spec(
  "image.resize",
  [],
  [
    {
      name: "image",
      title: "Resized",
      description: null,
      direction: "output",
      artifact_type: IMAGE,
      shape: "one",
      accepted_shapes: ["one"],
      instance_plugs: false,
      variadic: false,
      required: true,
    },
  ],
  "Resize image",
);

function collectionNode(): WorkflowNode {
  const data = createWorkflowNodeData(collectSpec, [
    { id: "member-1", port: COLLECTION_PORT },
    { id: "member-2", port: COLLECTION_PORT },
  ]);
  data.artifactTypeBindings = { T: IMAGE };
  return {
    id: "collection",
    type: WORKFLOW_NODE_TYPE,
    position: { x: 0, y: 0 },
    data,
  };
}

function producerNode(): WorkflowNode {
  return {
    id: "resize",
    type: WORKFLOW_NODE_TYPE,
    position: { x: 0, y: 300 },
    data: createWorkflowNodeData(resizeSpec, []),
  };
}

/** A member of the collection, fed by `resize`'s output into one of its plugs. */
function memberEdge(plugId: string): WorkflowEdge {
  const itemsPort = collectSpec.inputs[0]!;
  return {
    id: `resize->${plugId}`,
    source: "resize",
    sourceHandle: encodeHandleId(portMetaForPort(resizeSpec.outputs[0]!)),
    target: "collection",
    targetHandle: encodeHandleId(
      portMetaForPort(itemsPort, itemsPort.shape, plugId, { T: IMAGE }),
    ),
    data: { enabled: true, collectionMode: "direct", conversionPath: [] },
  };
}

function card(id: string): ArtifactViewerNode {
  return {
    id,
    type: ARTIFACT_VIEWER_NODE_TYPE,
    position: { x: 600, y: 0 },
    data: { layout: null, mode: null, artifactRef: null },
  };
}

/** A card showing the collection's own output: its link is sourced from that node. */
function viewers(): ArtifactViewerCanvasState {
  const edge: ArtifactViewerEdge = {
    id: "edge-collection-card",
    type: ARTIFACT_VIEWER_EDGE_TYPE,
    source: "collection",
    target: "card-fed-by-collection",
    targetHandle: "artifact-viewer-input",
    data: { sourcePortName: COLLECTION_PORT },
  };
  return {
    nodes: [card("card-fed-by-collection")],
    edges: [edge],
    bindings: [],
    annotations: [],
  };
}

function initialDocument(): AuthoredGraphDocument {
  return authoredGraphDocument(
    createSavedGraphRequest({
      name: "Collection feeding a card",
      nodes: [
        {
          id: "collection",
          kind: "builtin",
          operator_id: COLLECTION_OPERATOR_ID,
          operator_version: 1,
          config: {},
          input_plugs: [
            { id: "member-1", port: COLLECTION_PORT },
            { id: "member-2", port: COLLECTION_PORT },
          ],
          artifact_type_bindings: [{ variable: "T", artifact_type: IMAGE }],
          plugin_release_pin: null,
          position: { x: 0, y: 0 },
          layout: null,
        },
        {
          id: "resize",
          kind: "builtin",
          operator_id: "image.resize",
          operator_version: 1,
          config: {},
          input_plugs: [],
          artifact_type_bindings: [],
          plugin_release_pin: null,
          position: { x: 0, y: 300 },
          layout: null,
        },
      ],
      edges: [],
      origins: [],
    }),
  );
}

type Harness = {
  /** Links the room refused because their source node was gone from its head. */
  refused: string[];
  document: AuthoredGraphDocument;
  published: GraphPresentation[];
  /** The nodes the canvas still holds, so a selection hand-off is visible. */
  selectedNodeIds: string[];
  ungroupCollection: (nodeId: string) => void;
  viewers: ArtifactViewerCanvasState;
};

/**
 * Ungrouping touches three hooks at once: the card command, the committed card layer,
 * and the command path that prunes it. Only their combination shows what the room is
 * asked to accept, so this mounts all three and stops at a fake room that applies the
 * server's rule — a card link must name a node the head still holds.
 */
async function mount() {
  const refused: string[] = [];
  const published: GraphPresentation[] = [];
  const baseDocument = initialDocument();
  let latest: Harness | null = null;

  function HarnessComponent() {
    const [authoring, dispatchAuthoringState] = React.useReducer(
      reduceWorkbenchAuthoringState,
      { document: baseDocument, nodeOverlays: {}, error: null },
    );
    const authoredDocumentRef = React.useRef(authoring.document);
    React.useLayoutEffect(() => {
      authoredDocumentRef.current = authoring.document;
    }, [authoring.document]);
    const [viewersState, setArtifactViewers] = React.useState(viewers);

    const roomNodeIds = React.useRef(
      new Set(baseDocument.nodes.map((node) => node.id)),
    );
    const localAuthoringEnabledRef = React.useRef(true);
    const localAuthoringBlockedMessageRef = React.useRef(
      "Wait for the running operation to finish.",
    );
    const artifactViewerActivityRevisionRef = React.useRef(0);
    const [, setRunErrorState] = React.useState<string | null>(null);
    // The collection's own node starts out the thing a person holds.
    const [selectedNodeIdSet, setSelectedNodeIdSet] = React.useState<
      ReadonlySet<string>
    >(new Set(["collection"]));
    const [, setSelectedEdgeIdSet] = React.useState<ReadonlySet<string>>(
      new Set(),
    );
    const [, setPositionOverrides] = React.useState<
      Record<string, { x: number; y: number }>
    >({});
    const [, setArtifactViewerSelections] = React.useState({});
    const [, setArtifactViewerFields] = React.useState({});
    const [, setArtifactViewerActivities] = React.useState({});

    const roomCommandSyncRef = React.useRef<WorkbenchRoomCommandSync>({
      submitLocal: (commands: readonly GraphCommand[]) => {
        // The room has accepted the removal by the time it reads the next
        // presentation, so its head no longer holds those nodes.
        for (const command of commands) {
          if (command.kind !== "remove_nodes") continue;
          for (const nodeId of command.node_ids)
            roomNodeIds.current.delete(nodeId);
        }
      },
    });
    const presentationRoomSyncRef = React.useRef<ArtifactViewerRoomSync>({
      submitReplace: (state) => {
        const presentation = presentationFromArtifactViewers(state);
        published.push(presentation);
        for (const link of presentation.links) {
          if (!roomNodeIds.current.has(link.source_node_id)) {
            refused.push(link.source_node_id);
          }
        }
      },
    });

    const { applyAuthoringCommands } = useWorkbenchAuthoringCommands({
      authoredDocument: authoring.document,
      authoredDocumentRef,
      dispatchAuthoringState,
      localAuthoringBlockedMessageRef,
      localAuthoringEnabledRef,
      roomCommandSyncRef,
      setArtifactViewers,
      setPendingConnectionRoute: () => undefined,
      setPositionOverrides,
      setRunError: setRunErrorState,
      setSelectedEdgeIdSet,
      setSelectedNodeIdSet,
    });

    const { commitArtifactViewers } = useArtifactViewerCommands({
      artifactViewers: viewersState,
      artifactViewerActivityRevisionRef,
      applyAuthoringCommands,
      authoredDocumentRef,
      localAuthoringBlockedMessageRef,
      localAuthoringEnabledRef,
      presentationRoomSyncRef,
      setArtifactViewerActivities,
      setArtifactViewerFields,
      setArtifactViewerSelections,
      setArtifactViewers,
      setRunError: setRunErrorState,
    });

    const { ungroupCollection } = useArtifactCardCommands({
      applyAuthoringCommands,
      artifactViewers: viewersState,
      authoredDocumentRef,
      commitArtifactViewers,
      groupingDisabledReason: null,
      localAuthoringEnabled: true,
      selection: useCanvasSelection({
        setArtifactViewers,
        setSelectedEdgeIdSet,
        setSelectedNodeIdSet,
      }),
      collection: {
        spec: collectSpec,
        disabledReason: null,
        sources: [],
        nodes: [collectionNode(), producerNode()],
        edges: [memberEdge("member-1"), memberEdge("member-2")],
        onCollected: () => {},
      },
    });

    latest = {
      refused,
      document: authoring.document,
      published,
      selectedNodeIds: [...selectedNodeIdSet],
      ungroupCollection,
      viewers: viewersState,
    };
    return null;
  }

  const root = createRoot(document.createElement("div"));
  await act(async () => {
    root.render(React.createElement(HarnessComponent));
  });

  return {
    read(): Harness {
      if (!latest) throw new Error("harness did not render");
      return latest;
    },
    ungroup: () =>
      act(async () => {
        latest?.ungroupCollection("collection");
      }),
    unmount: () => root.unmount(),
  };
}

describe("ungrouping a collection that feeds a card", () => {
  it("retires the card link before the room is asked to accept it", async () => {
    const view = await mount();

    await view.ungroup();

    const harness = view.read();
    expect(harness.document.nodes.map((node) => node.id)).toEqual(["resize"]);
    expect(harness.viewers.edges.map((edge) => edge.source)).not.toContain(
      "collection",
    );
    // Every presentation the room was handed named only nodes its head still held.
    expect(harness.refused).toEqual([]);
    expect(harness.published.length).toBeGreaterThan(0);
    view.unmount();
  });

  it("wires the cards the collection ungroups into to the node that fed it", async () => {
    const view = await mount();

    await view.ungroup();

    const harness = view.read();
    expect(harness.viewers.nodes).toHaveLength(3); // the card that was there, plus two members
    expect(harness.viewers.edges.map((edge) => edge.source)).toEqual([
      "resize",
      "resize",
    ]);
    expect(harness.viewers.edges.map((edge) => edge.target)).toEqual(
      harness.viewers.nodes.slice(1).map((node) => node.id),
    );
    view.unmount();
  });

  it("hands the selection to the cards and lets go of the collection it removed", async () => {
    const view = await mount();
    expect(view.read().selectedNodeIds).toEqual(["collection"]);

    await view.ungroup();

    const harness = view.read();
    // Only the cards are held: the node that was collected is gone, and a person
    // who drags one card does not drag the old selection along with it.
    expect(harness.selectedNodeIds).toEqual([]);
    expect(harness.viewers.nodes.map((node) => node.selected)).toEqual([
      false,
      true,
      true,
    ]);
    view.unmount();
  });
});
