// @vitest-environment jsdom

import { act } from "react";
import * as React from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
}));

import type { WorkflowInputPlug } from "../canvas/input-plugs";
import type { ArtifactQueryRelation } from "../canvas/query-artifact-tables";
import type { SchemaBuilderField } from "../canvas/schema-builder";
import type { GraphCommand } from "../model/graph-document";
import { useNodeCommands } from "./workbench-node-commands";

type NodeFixture = {
  readonly id: string;
  readonly data: {
    readonly config: Record<string, unknown>;
    readonly inputPlugs: readonly WorkflowInputPlug[];
  };
};

type Harness = {
  api: ReturnType<typeof useNodeCommands>;
  runError: string | null;
};

function plug(id: string, portName = "input"): WorkflowInputPlug {
  return { id, portName };
}

function node(
  id: string,
  data: Partial<NodeFixture["data"]> = {},
): NodeFixture {
  return {
    id,
    data: {
      config: data.config ?? {},
      inputPlugs: data.inputPlugs ?? [],
    },
  };
}

async function mount(options: {
  nodes?: readonly NodeFixture[];
  edges?: readonly { source: string; target: string }[];
}) {
  const commands: GraphCommand[][] = [];
  const forgotten: string[] = [];
  const clearedRoutes: unknown[] = [];
  let harness: Harness | null = null;

  function HarnessComponent() {
    const [runError, setRunError] = React.useState<string | null>(
      "a stale run error",
    );
    const api = useNodeCommands({
      applyAuthoringCommands: (batch) => {
        commands.push([...batch]);
      },
      edges: options.edges ?? [],
      forgetNodeSecretStatuses: (nodeId) => {
        forgotten.push(nodeId);
      },
      nodes: options.nodes ?? [],
      setPendingConnectionRoute: (value) => {
        clearedRoutes.push(typeof value === "function" ? value(null) : value);
      },
      setRunError: (value) => {
        setRunError(
          typeof value === "function" ? value("a stale run error") : value,
        );
      },
    });
    harness = { api, runError };
    return null;
  }

  const root = createRoot(document.createElement("div"));
  await act(async () => {
    root.render(React.createElement(HarnessComponent));
  });

  const read = (): Harness => {
    if (!harness) {
      throw new Error("harness did not render");
    }
    return harness;
  };

  return {
    clearedRoutes,
    commands,
    forgotten,
    read,
    unmount: () => root.unmount(),
  };
}

function lastCommand(view: Awaited<ReturnType<typeof mount>>): GraphCommand {
  const batch = view.commands.at(-1);
  if (!batch || batch.length !== 1) {
    throw new Error(`expected one command batch, saw ${batch?.length ?? 0}`);
  }
  const command = batch[0];
  if (!command) {
    throw new Error("expected one command, saw none");
  }
  return command;
}

const FIELD: SchemaBuilderField = {
  id: "field-1",
  name: "city",
  kind: "string",
  required: false,
  description: "",
};

const RELATION: ArtifactQueryRelation = { id: "relation-1", alias: "parcels" };

describe("useNodeCommands", () => {
  it("refuses to rebind an artifact type on a node that is already wired", async () => {
    const view = await mount({
      nodes: [node("node-1")],
      edges: [{ source: "node-1", target: "node-2" }],
    });

    await act(async () => {
      view.read().api.bindNodeArtifactTypeBinding("node-1", "input", {
        id: "geo.table",
        schema_version: 1,
      });
    });
    await act(async () => {
      view.read().api.resetNodeArtifactTypeBinding("node-1", "input");
    });

    expect(view.commands).toEqual([]);
    expect(view.read().runError).toBe("a stale run error");
    view.unmount();
  });

  it("binds an artifact type on an unwired node and clears the stale run error", async () => {
    const view = await mount({ nodes: [node("node-1")] });
    expect(view.read().runError).toBe("a stale run error");

    await act(async () => {
      view.read().api.bindNodeArtifactTypeBinding("node-1", "input", {
        id: "geo.table",
        schema_version: 1,
      });
    });

    expect(lastCommand(view)).toEqual({
      kind: "bind_artifact_type",
      node_id: "node-1",
      variable: "input",
      artifact_type: { id: "geo.table", schema_version: 1 },
    });
    expect(view.read().runError).toBeNull();
    expect(view.clearedRoutes).toEqual([null]);
    view.unmount();
  });

  it("deleting a node forgets its secret as well as removing it", async () => {
    const view = await mount({ nodes: [node("node-1")] });

    await act(async () => {
      view.read().api.removeNode("node-1");
    });

    expect(lastCommand(view)).toEqual({
      kind: "remove_nodes",
      node_ids: ["node-1"],
    });
    expect(view.forgotten).toEqual(["node-1"]);
    view.unmount();
  });

  it("keeps the rest of the configuration when a schema builder rewrites fields", async () => {
    const view = await mount({
      nodes: [node("node-1", { config: { timeout: 30 } })],
    });

    await act(async () => {
      view
        .read()
        .api.updateSchemaBuilderFields("node-1", [FIELD], [plug("plug-1")]);
    });

    const command = lastCommand(view);
    if (command.kind !== "update_node_configuration_and_input_plugs") {
      throw new Error(`unexpected command kind: ${command.kind}`);
    }
    expect(command.config).toMatchObject({ timeout: 30, fields: [FIELD] });
    expect(command.input_plugs).toEqual([{ id: "plug-1", port: "input" }]);
    view.unmount();
  });

  it("replaces relations and leaves the fields alone for an artifact query", async () => {
    const view = await mount({
      nodes: [
        node("node-1", {
          config: { fields: [FIELD], relations: [{ id: "old", alias: "old" }] },
        }),
      ],
    });

    await act(async () => {
      view
        .read()
        .api.updateArtifactQueryRelations(
          "node-1",
          [RELATION],
          [plug("plug-2", "relations")],
        );
    });

    const command = lastCommand(view);
    if (command.kind !== "update_node_configuration_and_input_plugs") {
      throw new Error(`unexpected command kind: ${command.kind}`);
    }
    expect(command.config["relations"]).toEqual([RELATION]);
    expect(command.config["fields"]).toEqual([FIELD]);
    expect(command.input_plugs).toEqual([{ id: "plug-2", port: "relations" }]);
    view.unmount();
  });

  it("emits nothing when the node a plug belongs to is gone", async () => {
    const view = await mount({ nodes: [] });

    await act(async () => {
      view.read().api.addNodeInputPlug("deleted-node", "input");
    });

    expect(view.commands).toEqual([]);
    view.unmount();
  });
});
