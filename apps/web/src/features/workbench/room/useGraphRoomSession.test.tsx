import { collaborativeHeadFromLegacy } from "@/lib/api/graph-head";
import type { LegacyCollaborativeHead } from "@/lib/api";
// @vitest-environment jsdom

import * as React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { RoomReadyMessage } from "./protocol";
import {
  useGraphRoomSession,
  type UseGraphRoomSessionResult,
} from "./useGraphRoomSession";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  static instances: FakeWebSocket[] = [];

  readyState = FakeWebSocket.CONNECTING;
  private readonly listeners = new Map<
    string,
    Set<(event: unknown) => void>
  >();

  constructor(readonly url: string) {
    FakeWebSocket.instances.push(this);
  }

  addEventListener(type: string, listener: (event: unknown) => void): void {
    const listeners = this.listeners.get(type) ?? new Set();
    listeners.add(listener);
    this.listeners.set(type, listeners);
  }

  send(): void {}

  close(): void {
    this.readyState = FakeWebSocket.CLOSED;
  }

  emitMessage(payload: unknown): void {
    for (const listener of this.listeners.get("message") ?? []) {
      listener({ data: JSON.stringify(payload) });
    }
  }
}

function readyMessage(graphId: string): Omit<RoomReadyMessage, "head"> & { head: LegacyCollaborativeHead } {
  return {
    protocol_version: 1,
    type: "room.ready",
    workspace_id: "workspace-1",
    graph_id: graphId,
    graph_room_session_id: `session-${graphId}`,
    actor: {
      actor_id: "actor-1",
      display_name: "Owner",
      color: "emerald",
    },
    capabilities: {
      capabilities: ["edit_graph", "publish_presence"],
      authorization_version: 2,
    },
    head: {
      graph_id: graphId,
      room_epoch: "00000000-0000-0000-0000-000000000001",
      collaboration_sequence: 4,
      checkpoint_sequence: 1,
      checkpoint_revision: 1,
      name: "Room graph",
      updated_at: "2026-08-13T00:00:00Z",
      nodes: [],
      edges: [],
    },
    participants: [
      {
        graph_room_session_id: `session-${graphId}`,
        actor: {
          actor_id: "actor-1",
          display_name: "Owner",
          color: "emerald",
        },
        presence_sequence: 0,
        cursor: null,
        selected_node_ids: [],
        selected_edge_ids: [],
        activity: null,
        activity_target_ids: [],
        transient_node_positions: [],
      },
    ],
    active_execution: {
      execution_id: "execution-1",
      graph_revision: 1,
      status: "running",
      scope: "all",
      requested_node_ids: [],
      starter: {
        actor_id: "actor-1",
        display_name: "Owner",
        color: "emerald",
      },
      active_node_id: null,
      overlays_compatible: true,
      cancellable: true,
    },
    registry_marker: "builtin",
  };
}

let latest: UseGraphRoomSessionResult | undefined;

function captureLatest(result: UseGraphRoomSessionResult): void {
  latest = result;
}

function SessionProbe({ graphId }: { graphId: string | null }) {
  const result = useGraphRoomSession({ workspaceId: "workspace-1", graphId });
  React.useEffect(() => captureLatest(result), [result]);
  return <span>{result.status}</span>;
}

describe("useGraphRoomSession", () => {
  const roots: ReturnType<typeof createRoot>[] = [];

  beforeEach(() => {
    latest = undefined;
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket);
  });

  afterEach(() => {
    React.act(() => {
      for (const root of roots.splice(0)) root.unmount();
    });
    vi.unstubAllGlobals();
    document.body.replaceChildren();
  });

  it("exposes an empty idle snapshot when a graph is removed or switched", () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    roots.push(root);

    React.act(() => root.render(<SessionProbe graphId="graph-1" />));
    expect(latest?.status).toBe("connecting");
    React.act(() => {
      FakeWebSocket.instances[0]?.emitMessage(readyMessage("graph-1"));
    });
    expect(latest).toMatchObject({
      status: "ready",
      authorizationVersion: 2,
      localSessionId: "session-graph-1",
      canSubmitCommands: true,
      canPublishPresence: true,
    });
    expect(latest?.head?.graph_id).toBe("graph-1");
    expect(latest?.participants).toHaveLength(1);
    expect(latest?.activeExecution?.execution_id).toBe("execution-1");

    React.act(() => root.render(<SessionProbe graphId={null} />));
    expect(latest).toMatchObject({
      status: "idle",
      terminalReason: null,
      head: null,
      capabilities: [],
      authorizationVersion: null,
      localSessionId: null,
      participants: [],
      activeExecution: null,
      canSubmitCommands: false,
      canPublishPresence: false,
    });

    React.act(() => root.render(<SessionProbe graphId="graph-2" />));
    expect(latest).toMatchObject({
      status: "connecting",
      head: null,
      capabilities: [],
      authorizationVersion: null,
      localSessionId: null,
      participants: [],
      activeExecution: null,
      canSubmitCommands: false,
      canPublishPresence: false,
    });
  });

  it("reconciles checkpoint metadata without replacing a newer peer head", () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    roots.push(root);

    React.act(() => root.render(<SessionProbe graphId="graph-1" />));
    React.act(() => {
      FakeWebSocket.instances[0]?.emitMessage(readyMessage("graph-1"));
      FakeWebSocket.instances[0]?.emitMessage({
        protocol_version: 1,
        type: "graph.command.accepted",
        command_id: "peer-presentation",
        room_epoch: "00000000-0000-0000-0000-000000000001",
        sequence: 5,
        actor: {
          actor_id: "actor-2",
          display_name: "Peer",
          color: "blue",
        },
        graph_room_session_id: "session-peer",
        command: {
          kind: "replace_presentation",
          presentation: {
            viewers: [{
              id: "peer-viewer",
              position: { x: 80, y: 120 },
              layout: null,
              mode: null,
            }],
            links: [],
            bindings: [],
            annotations: [],
          },
        },
      });
    });

    let effectiveHead = latest?.head;
    React.act(() => {
      effectiveHead = latest?.reconcileCheckpointHead(
        {
          ...collaborativeHeadFromLegacy(readyMessage("graph-1").head),
          checkpoint_sequence: 4,
          checkpoint_revision: 2,
        },
        "00000000-0000-0000-0000-000000000001",
      );
    });

    expect(effectiveHead).toMatchObject({
      collaboration_sequence: 5,
      checkpoint_sequence: 4,
      checkpoint_revision: 2,
      document: {
        presentation: { viewers: [expect.objectContaining({ id: "peer-viewer" })] },
      },
    });
    expect(latest?.head).toEqual(effectiveHead);
  });
});
