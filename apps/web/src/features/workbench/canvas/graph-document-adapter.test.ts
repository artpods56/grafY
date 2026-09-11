import { describe, expect, it } from "vitest";

import {
  addNodeCommand,
  graphCommandsFromNodeChanges,
  reduceWorkbenchAuthoringState,
  type WorkbenchAuthoringState,
} from "./graph-document-adapter";
import {
  authoredGraphDocument,
  createSavedGraphRequest,
} from "../model/graph-document";
import { createWorkflowNodeData } from "./types";

const source = {
  id: "source",
  kind: "builtin" as const,
  operator_id: "test.source",
  operator_version: 1,
  config: { label: "source" },
  input_plugs: [],
  artifact_type_bindings: [],
  position: { x: 0, y: 0 },
  layout: null,
};

const target = {
  id: "target",
  kind: "builtin" as const,
  operator_id: "test.target",
  operator_version: 1,
  config: { label: "target" },
  input_plugs: [],
  artifact_type_bindings: [],
  position: { x: 300, y: 0 },
  layout: null,
};

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

function state(): WorkbenchAuthoringState {
  return {
    document: authoredGraphDocument(createSavedGraphRequest({
      name: "Draft",
      nodes: [source, target],
      edges: [edge],
      origins: [],
    })),
    nodeOverlays: {
      source: {
        run: null,
        execution: { status: "succeeded" },
        progress: null,
      },
      target: {
        run: null,
        execution: { status: "succeeded" },
        progress: null,
      },
    },
    error: null,
  };
}

describe("Workbench authored document adapter", () => {
  it("authors the exact scoped catalog pin at the requested insertion position", () => {
    const data = createWorkflowNodeData({
      operator_id: "reports.render",
      operator_version: 7,
      plugin_slug: "reports",
      origin: "plugin",
      plugin_revision: 11,
      plugin_release: { scope: "system", slug: "reports", revision: 11 },
      title: "Render report",
      description: "Render a report.",
      catalog_visible: true,
      runnable: true,
      config_schema: {},
      input_schema: {},
      output_schema: {},
      inputs: [],
      outputs: [],
    });
    data.config = { nested: { threshold: 3 } };
    data.artifactTypeBindings = {
      T: { id: "table.data", schema_version: 2 },
    };
    data.layout = { width: 420, bodyHeight: 180, appendixHeight: 260 };

    expect(addNodeCommand("plugin-node", data, { x: 80, y: 120 })).toEqual({
      kind: "add_node",
      node: {
        artifact_type_bindings: [
          {
            variable: "T",
            artifact_type: { id: "table.data", schema_version: 2 },
          },
        ],
        config: { nested: { threshold: 3 } },
        id: "plugin-node",
        kind: "plugin",
        input_plugs: [],
        layout: { width: 420, body_height: 180, appendix_height: 260 },
        operator_id: "reports.render",
        operator_version: 7,
        plugin_release_pin: {
          scope: "system",
          slug: "reports",
          revision: 11,
        },
        position: { x: 80, y: 120 },
      },
    });
  });

  it("does not author a move while dragging", () => {
    expect(graphCommandsFromNodeChanges([{
      id: "source",
      type: "position",
      position: { x: 40, y: 50 },
      dragging: true,
    }])).toEqual([]);
  });

  it("authors the final position when dragging stops", () => {
    expect(graphCommandsFromNodeChanges([{
      id: "source",
      type: "position",
      position: { x: 40, y: 50 },
      dragging: false,
    }])).toEqual([{
      kind: "move_nodes",
      positions: [{ node_id: "source", x: 40, y: 50 }],
    }]);
  });

  it("authors one durable command when a multi-node drag stops", () => {
    expect(graphCommandsFromNodeChanges([
      {
        id: "source",
        type: "position",
        position: { x: 40, y: 50 },
        dragging: false,
      },
      {
        id: "target",
        type: "position",
        position: { x: 340, y: 50 },
        dragging: false,
      },
    ])).toEqual([{
      kind: "move_nodes",
      positions: [
        { node_id: "source", x: 40, y: 50 },
        { node_id: "target", x: 340, y: 50 },
      ],
    }]);
  });

  it("keeps move overlays and scopes config invalidation", () => {
    const moved = reduceWorkbenchAuthoringState(state(), {
      kind: "apply_commands",
      commands: [{
        kind: "move_nodes",
        positions: [{ node_id: "source", x: 40, y: 50 }],
      }],
    });
    const edited = reduceWorkbenchAuthoringState(moved, {
      kind: "apply_commands",
      commands: [{
        kind: "update_node_configuration",
        node_id: "target",
        field: "label",
        value: "edited",
      }],
    });

    expect(moved.nodeOverlays.source?.execution.status).toBe("succeeded");
    expect(edited.nodeOverlays.source?.execution.status).toBe("succeeded");
    expect(edited.nodeOverlays.target?.execution.status).toBe("idle");
    expect(edited.document.nodes[0]?.position).toEqual({ x: 40, y: 50 });
  });

  it("applies sequential stale dispatchers to the latest document", () => {
    let current = state();
    const dispatchMove = () => {
      current = reduceWorkbenchAuthoringState(current, {
        kind: "apply_commands",
        commands: [{
          kind: "move_nodes",
          positions: [{ node_id: "source", x: 80, y: 90 }],
        }],
      });
    };
    const dispatchConfig = () => {
      current = reduceWorkbenchAuthoringState(current, {
        kind: "apply_commands",
        commands: [{
          kind: "update_node_configuration",
          node_id: "target",
          field: "label",
          value: "edited after move",
        }],
      });
    };

    dispatchMove();
    dispatchConfig();

    expect(current.document.nodes[0]?.position).toEqual({ x: 80, y: 90 });
    expect(current.document.nodes[1]?.config).toEqual({
      label: "edited after move",
    });
  });

  it("turns stale commands into a bounded error state", () => {
    const initial = state();
    const result = reduceWorkbenchAuthoringState(initial, {
      kind: "apply_commands",
      commands: [{
        kind: "update_node_configuration",
        node_id: "missing",
        field: "label",
        value: "ignored",
      }],
    });

    expect(result.document).toEqual(initial.document);
    expect(result.nodeOverlays).toEqual(initial.nodeOverlays);
    expect(result.error).toContain("missing node missing");
  });

  it("bounds an update for a missing edge as an adapter error", () => {
    const result = reduceWorkbenchAuthoringState(state(), {
      kind: "apply_commands",
      commands: [{
        kind: "update_edge",
        edge_id: "missing-edge",
        update: { enabled: false },
      }],
    });

    expect(result.document).toEqual(state().document);
    expect(result.error).toContain("missing edge missing-edge");
  });

  it("normalizes replacement documents before they enter adapter state", () => {
    const replacement = {
      name: "Replacement",
      nodes: [{
        ...source,
        selected: true,
        dimensions: { width: 480, height: 220 },
        callbackLike: { name: "onNodeChange" },
      }],
      edges: [{
        ...edge,
        selected: true,
        internals: { sourceX: 1 },
        callbackLike: { name: "onEdgeChange" },
      }],
    };
    const result = reduceWorkbenchAuthoringState(state(), {
      kind: "replace_document",
      document: replacement as never,
      nodeOverlays: {},
    });

    expect(result.document.nodes[0]).not.toHaveProperty("selected");
    expect(result.document.nodes[0]).not.toHaveProperty("dimensions");
    expect(result.document.nodes[0]).not.toHaveProperty("callbackLike");
    expect(result.document.edges[0]).not.toHaveProperty("selected");
    expect(result.document.edges[0]).not.toHaveProperty("internals");
    expect(result.document.edges[0]).not.toHaveProperty("callbackLike");
  });

  it("clears an authoring error when the user dismisses it", () => {
    const errored = reduceWorkbenchAuthoringState(state(), {
      kind: "apply_commands",
      commands: [{
        kind: "update_node_configuration",
        node_id: "missing",
        field: "label",
        value: "ignored",
      }],
    });
    const cleared = reduceWorkbenchAuthoringState(errored, {
      kind: "clear_error",
    });

    expect(cleared.error).toBeNull();
  });

  it("clears overlays for downstream descendants while preserving upstream and unrelated nodes", () => {
    // source -> target -> descendant, plus an unrelated node.
    const withDescendant = {
      name: "Draft",
      nodes: [source, target, { ...source, id: "descendant" }],
      edges: [
        edge,
        {
          ...edge,
          id: "edge-2",
          from_node: "target",
          to_node: "descendant",
        },
      ],
      origins: [],
    };
    const initial: WorkbenchAuthoringState = {
      document: authoredGraphDocument(createSavedGraphRequest(withDescendant)),
      nodeOverlays: {
        source: {
          run: null,
          execution: { status: "succeeded" },
          progress: null,
        },
        target: {
          run: null,
          execution: { status: "succeeded" },
          progress: null,
        },
        descendant: {
          run: null,
          execution: { status: "succeeded" },
          progress: null,
        },
      },
      error: null,
    };

    const edited = reduceWorkbenchAuthoringState(initial, {
      kind: "apply_commands",
      commands: [{
        kind: "update_node_configuration",
        node_id: "target",
        field: "label",
        value: "changed",
      }],
    });

    // target and its descendant are cleared; the upstream source keeps its run.
    expect(edited.nodeOverlays.target?.execution.status).toBe("idle");
    expect(edited.nodeOverlays.descendant?.execution.status).toBe("idle");
    expect(edited.nodeOverlays.source?.execution.status).toBe("succeeded");
  });

  it("does not clear overlays through a disabled edge", () => {
    const withDisabledEdge = {
      name: "Draft",
      nodes: [source, target, { ...source, id: "descendant" }],
      edges: [
        edge,
        {
          ...edge,
          id: "edge-2",
          from_node: "target",
          to_node: "descendant",
          enabled: false,
        },
      ],
      origins: [],
    };
    const initial: WorkbenchAuthoringState = {
      document: authoredGraphDocument(createSavedGraphRequest(withDisabledEdge)),
      nodeOverlays: {
        source: {
          run: null,
          execution: { status: "succeeded" },
          progress: null,
        },
        target: {
          run: null,
          execution: { status: "succeeded" },
          progress: null,
        },
        descendant: {
          run: null,
          execution: { status: "succeeded" },
          progress: null,
        },
      },
      error: null,
    };

    const edited = reduceWorkbenchAuthoringState(initial, {
      kind: "apply_commands",
      commands: [{
        kind: "update_node_configuration",
        node_id: "target",
        field: "label",
        value: "changed",
      }],
    });

    expect(edited.nodeOverlays.target?.execution.status).toBe("idle");
    expect(edited.nodeOverlays.descendant?.execution.status).toBe("succeeded");
  });

  it("applies a batch equivalently to sequential dispatches", () => {
    const batched = reduceWorkbenchAuthoringState(state(), {
      kind: "apply_commands",
      commands: [
        { kind: "move_nodes", positions: [{ node_id: "source", x: 40, y: 50 }] },
        {
          kind: "update_node_configuration",
          node_id: "target",
          field: "label",
          value: "edited",
        },
      ],
    });
    const sequential = reduceWorkbenchAuthoringState(
      reduceWorkbenchAuthoringState(state(), {
        kind: "apply_commands",
        commands: [
          { kind: "move_nodes", positions: [{ node_id: "source", x: 40, y: 50 }] },
        ],
      }),
      {
        kind: "apply_commands",
        commands: [{
          kind: "update_node_configuration",
          node_id: "target",
          field: "label",
          value: "edited",
        }],
      },
    );

    expect(batched.document).toEqual(sequential.document);
    expect(batched.nodeOverlays).toEqual(sequential.nodeOverlays);
  });
});
