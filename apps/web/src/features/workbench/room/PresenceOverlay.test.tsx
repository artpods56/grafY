// @vitest-environment jsdom

import * as React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { PresenceParticipant } from "./protocol";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
}));

vi.mock("@xyflow/react", () => ({
  ViewportPortal: ({ children }: { children: React.ReactNode }) => children,
}));

import { PresenceOverlay } from "./PresenceOverlay";

function participant(
  displayName: string,
  cursor: { x: number; y: number },
): PresenceParticipant {
  return {
    graph_room_session_id: "remote-session",
    actor: {
      actor_id: "remote-actor",
      display_name: displayName,
      color: "indigo",
    },
    presence_sequence: 1,
    cursor,
    selected_node_ids: [],
    selected_edge_ids: [],
    activity: null,
    activity_target_ids: [],
    transient_node_positions: [],
  };
}

describe("PresenceOverlay", () => {
  const roots: ReturnType<typeof createRoot>[] = [];

  afterEach(() => {
    React.act(() => {
      for (const root of roots.splice(0)) root.unmount();
    });
    vi.unstubAllGlobals();
    document.body.replaceChildren();
  });

  it("renders cursor snapshots without reading the mutable track ref", () => {
    vi.stubGlobal(
      "requestAnimationFrame",
      vi.fn(() => 1),
    );
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    roots.push(root);

    React.act(() => {
      root.render(
        <PresenceOverlay
          participants={[participant("Ada", { x: 12, y: 34 })]}
          localSessionId="local-session"
          now={() => 0}
        />,
      );
    });

    expect(container.textContent).toContain("Ada");
    expect(container.querySelector("svg")?.parentElement?.style.transform).toBe(
      "translate3d(12px, 34px, 0)",
    );
  });
});
