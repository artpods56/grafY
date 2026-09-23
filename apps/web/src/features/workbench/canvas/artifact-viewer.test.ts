import { describe, expect, it } from "vitest";

import {
  ARTIFACT_VIEWER_EDGE_TYPE,
  ARTIFACT_VIEWER_INPUT_HANDLE,
  ARTIFACT_VIEWER_NODE_TYPE,
  artifactViewersFromPresentation,
  presentationFromArtifactViewers,
  type ArtifactViewerEdge,
  type ArtifactViewerNode,
} from "./artifact-viewer";
import type { ArtifactViewerBinding } from "./artifact-interactions";

describe("shared presentation", () => {
  it("keeps a node-less artifact card reference through canvas load and save", () => {
    const reference = {
      artifact_id: "00000000-0000-0000-0000-0000000000bb",
      artifact_type: "table.data",
      schema_version: 1,
      content_hash: "c".repeat(64),
    };
    const loaded = artifactViewersFromPresentation("graph-1", {
      viewers: [
        {
          id: "artifact-card",
          position: { x: 40, y: 80 },
          artifact_ref: reference,
        },
      ],
      links: [],
      bindings: [],
      annotations: [],
    });
    const saved = presentationFromArtifactViewers(loaded);

    expect(saved.viewers).toHaveLength(1);
    expect(saved.viewers?.[0]?.artifact_ref).toEqual(reference);
    expect(saved.links).toEqual([]);
  });

  it("round-trips geometry and semantic source identity without runtime payload", () => {
    const nodes: ArtifactViewerNode[] = [
      {
        id: "artifact-viewer-1",
        type: ARTIFACT_VIEWER_NODE_TYPE,
        position: { x: 412, y: -88 },
        data: {
          layout: {
            width: 560,
            bodyHeight: 240,
            appendixHeight: 420,
          },
          mode: "raw",
          run: "do-not-persist-run",
          artifact: "do-not-persist-artifact",
          payload: "do-not-persist-payload",
          content_url: "https://private.example/artifact",
          onRemoveNode: () => undefined,
        },
      },
      {
        id: "artifact-viewer-2",
        type: ARTIFACT_VIEWER_NODE_TYPE,
        position: { x: 940, y: -88 },
        data: { layout: null, mode: "map" },
      },
    ];
    const edges: ArtifactViewerEdge[] = [
      {
        id: "artifact-viewer-edge-1",
        type: ARTIFACT_VIEWER_EDGE_TYPE,
        source: "source-node",
        sourceHandle: "output-handle-with-runtime-contract",
        target: "artifact-viewer-1",
        targetHandle: ARTIFACT_VIEWER_INPUT_HANDLE,
        data: {
          sourcePortName: "features",
          run: "do-not-persist-edge-run",
          artifacts: "do-not-persist-edge-artifacts",
          payload: "do-not-persist-edge-payload",
          content_url: "https://private.example/edge-artifact",
        },
      },
    ];
    const bindings: ArtifactViewerBinding[] = [
      {
        id: "artifact-viewer-binding-1",
        sourceViewerId: "artifact-viewer-1",
        targetViewerId: "artifact-viewer-2",
        mappings: [
          { sourceField: "historical_name", targetField: "transliteration" },
          { sourceField: "district", targetField: "district" },
        ],
        effects: ["highlight", "focus"],
        emptySelection: "show_all",
      },
    ];

    const presentation = presentationFromArtifactViewers({
      nodes,
      edges,
      bindings,
      annotations: [],
    });

    expect(presentation).toEqual({
      viewers: [
        {
          id: "artifact-viewer-1",
          position: { x: 412, y: -88 },
          layout: {
            width: 560,
            body_height: 240,
            appendix_height: 420,
          },
          mode: "raw",
        },
        {
          id: "artifact-viewer-2",
          position: { x: 940, y: -88 },
          layout: null,
          mode: "map",
        },
      ],
      links: [
        {
          id: "artifact-viewer-edge-1",
          source_node_id: "source-node",
          source_port_name: "features",
          target_viewer_id: "artifact-viewer-1",
          projection: null,
          route_offset: null,
        },
      ],
      bindings: [
        {
          id: "artifact-viewer-binding-1",
          source_viewer_id: "artifact-viewer-1",
          target_viewer_id: "artifact-viewer-2",
          mappings: [
            {
              source_field: "historical_name",
              target_field: "transliteration",
            },
            { source_field: "district", target_field: "district" },
          ],
          effects: ["highlight", "focus"],
          empty_selection: "show_all",
        },
      ],
      annotations: [],
    });
    expect(JSON.stringify(presentation)).not.toContain("do-not-persist");
    expect(JSON.stringify(presentation)).not.toContain("private.example");

    expect(artifactViewersFromPresentation("graph-1", presentation)).toEqual({
      graphId: "graph-1",
      nodes: [
        {
          id: "artifact-viewer-1",
          type: ARTIFACT_VIEWER_NODE_TYPE,
          position: { x: 412, y: -88 },
          data: {
            layout: {
              width: 560,
              bodyHeight: 240,
              appendixHeight: 420,
            },
            mode: "raw",
          },
        },
        {
          id: "artifact-viewer-2",
          type: ARTIFACT_VIEWER_NODE_TYPE,
          position: { x: 940, y: -88 },
          data: { layout: null, mode: "map" },
        },
      ],
      edges: [
        {
          id: "artifact-viewer-edge-1",
          type: ARTIFACT_VIEWER_EDGE_TYPE,
          source: "source-node",
          target: "artifact-viewer-1",
          targetHandle: ARTIFACT_VIEWER_INPUT_HANDLE,
          data: { sourcePortName: "features" },
        },
      ],
      bindings,
      annotations: [],
    });
  });

  it("round-trips presentation link projection and route offset", () => {
    const edges: ArtifactViewerEdge[] = [
      {
        id: "artifact-viewer-edge-1",
        type: ARTIFACT_VIEWER_EDGE_TYPE,
        source: "source-node",
        target: "artifact-viewer-1",
        targetHandle: ARTIFACT_VIEWER_INPUT_HANDLE,
        data: {
          sourcePortName: "items",
          projection: { path: ["role"] },
          routeOffset: { x: 12, y: -8 },
        },
      },
    ];
    const presentation = presentationFromArtifactViewers({
      nodes: [
        {
          id: "artifact-viewer-1",
          type: ARTIFACT_VIEWER_NODE_TYPE,
          position: { x: 0, y: 0 },
          data: { layout: null, mode: null },
        },
      ],
      edges,
      bindings: [],
      annotations: [],
    });

    expect(presentation.links?.[0]).toEqual({
      id: "artifact-viewer-edge-1",
      source_node_id: "source-node",
      source_port_name: "items",
      target_viewer_id: "artifact-viewer-1",
      projection: { path: ["role"] },
      route_offset: { x: 12, y: -8 },
    });

    expect(
      artifactViewersFromPresentation("graph-1", presentation).edges[0]?.data,
    ).toEqual({
      sourcePortName: "items",
      projection: { path: ["role"] },
      routeOffset: { x: 12, y: -8 },
    });
  });

  it("omits incomplete draft mappings and trims complete mappings", () => {
    const presentation = presentationFromArtifactViewers({
      nodes: [],
      edges: [],
      bindings: [
        {
          id: "artifact-viewer-binding-empty",
          sourceViewerId: "artifact-viewer-source",
          targetViewerId: "artifact-viewer-target",
          mappings: [
            { sourceField: "", targetField: "" },
            { sourceField: "source_only", targetField: "" },
            { sourceField: "   ", targetField: "target_only" },
          ],
          effects: ["highlight"],
          emptySelection: "show_all",
        },
        {
          id: "artifact-viewer-binding-complete",
          sourceViewerId: "artifact-viewer-source",
          targetViewerId: "artifact-viewer-target",
          mappings: [
            {
              sourceField: "  historical_name  ",
              targetField: "  transliteration  ",
            },
            { sourceField: "district", targetField: "district" },
          ],
          effects: ["focus"],
          emptySelection: "show_all",
        },
      ],
      annotations: [],
    });

    expect(presentation.bindings?.map((binding) => binding.mappings)).toEqual([
      [],
      [
        {
          source_field: "historical_name",
          target_field: "transliteration",
        },
        { source_field: "district", target_field: "district" },
      ],
    ]);
  });

  it("serializes viewer layout with API snake_case fields", () => {
    const presentation = presentationFromArtifactViewers({
      nodes: [
        {
          id: "artifact-viewer-1",
          type: ARTIFACT_VIEWER_NODE_TYPE,
          position: { x: 10, y: 20 },
          data: {
            layout: { width: 520, appendixHeight: 300 },
            mode: "map",
          },
        },
      ],
      edges: [],
      bindings: [],
      annotations: [],
    });

    expect(presentation.viewers?.[0]?.layout).toEqual({
      width: 520,
      body_height: null,
      appendix_height: 300,
    });
  });

  it("hydrates API snake_case layout and drops invalid links", () => {
    const state = artifactViewersFromPresentation("graph-1", {
      viewers: [
        {
          id: "artifact-viewer-1",
          position: { x: 10, y: 20 },
          layout: {
            width: 520,
            body_height: null,
            appendix_height: 300,
          },
          mode: "map",
        },
        {
          id: "artifact-viewer-2",
          position: { x: -30, y: 44 },
          layout: null,
          mode: null,
        },
      ],
      links: [
        {
          id: "artifact-viewer-edge-1",
          source_node_id: "source-a",
          source_port_name: "image",
          target_viewer_id: "artifact-viewer-1",
        },
        {
          id: "artifact-viewer-edge-replacement",
          source_node_id: "source-b",
          source_port_name: "features",
          target_viewer_id: "artifact-viewer-1",
        },
        {
          id: "artifact-viewer-edge-2",
          source_node_id: "source-d",
          source_port_name: "document",
          target_viewer_id: "artifact-viewer-2",
        },
        {
          id: "artifact-viewer-edge-empty-port",
          source_node_id: "source-f",
          source_port_name: "",
          target_viewer_id: "artifact-viewer-2",
        },
        {
          id: "artifact-viewer-edge-unknown-target",
          source_node_id: "source-e",
          source_port_name: "table",
          target_viewer_id: "artifact-viewer-missing",
        },
      ],
      bindings: [],
      annotations: [],
    });

    expect(state.nodes[0]?.data.layout).toEqual({
      width: 520,
      appendixHeight: 300,
    });
    expect(state.edges).toEqual([
      {
        id: "artifact-viewer-edge-1",
        type: ARTIFACT_VIEWER_EDGE_TYPE,
        source: "source-a",
        target: "artifact-viewer-1",
        targetHandle: ARTIFACT_VIEWER_INPUT_HANDLE,
        data: { sourcePortName: "image" },
      },
      {
        id: "artifact-viewer-edge-2",
        type: ARTIFACT_VIEWER_EDGE_TYPE,
        source: "source-d",
        target: "artifact-viewer-2",
        targetHandle: ARTIFACT_VIEWER_INPUT_HANDLE,
        data: { sourcePortName: "document" },
      },
    ]);
  });
});
