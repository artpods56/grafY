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
  useNodeId: () => null,
  ViewportPortal: ({ children }: { children: React.ReactNode }) => children,
}));

import { PresenceOverlay } from "./PresenceOverlay";

const PROJECT_ID = "00000000-0000-4000-8000-000000000009";
const GRAPH_ID = "11111111-1111-4111-8111-111111111111";
const OTHER_GRAPH_ID = "66666666-6666-4666-8666-666666666666";
const LOCAL_SESSION_ID = "local-session";

function participant(
  displayName: string,
  cursor: { x: number; y: number },
  overrides: Partial<PresenceParticipant> = {},
): PresenceParticipant {
  return {
    project_room_session_id: "remote-session",
    actor: {
      actor_id: "remote-actor",
      display_name: displayName,
      color: "indigo",
    },
    // A participant names the Graph of the Project they are looking at.
    graph_id: GRAPH_ID,
    presence_sequence: 1,
    cursor,
    selected_node_ids: [],
    selected_edge_ids: [],
    activity: null,
    activity_target_ids: [],
    transient_node_positions: [],
    ...overrides,
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

  function render(participants: readonly PresenceParticipant[]) {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    roots.push(root);
    React.act(() => {
      root.render(
        <PresenceOverlay
          participants={participants}
          localSessionId={LOCAL_SESSION_ID}
          now={() => 0}
        />,
      );
    });
    return container;
  }

  it("renders cursor snapshots without reading the mutable track ref", () => {
    vi.stubGlobal(
      "requestAnimationFrame",
      vi.fn(() => 1),
    );
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    const container = render([participant("Ada", { x: 12, y: 34 })]);

    expect(container.textContent).toContain("Ada");
    expect(container.querySelector("svg")?.parentElement?.style.transform).toBe(
      "translate3d(12px, 34px, 0)",
    );
  });

  it("shows every remote session in the Project, whichever Graph it is on", () => {
    const container = render([
      participant("Ada", { x: 12, y: 34 }, { graph_id: GRAPH_ID }),
      participant("Grace", { x: 5, y: 6 }, { graph_id: OTHER_GRAPH_ID }),
      // The room carries this client's own participant too; it never chairs
      // itself alongside the others.
      participant("Me", { x: 0, y: 0 }, {
        project_room_session_id: LOCAL_SESSION_ID,
        graph_id: PROJECT_ID,
      }),
    ]);

    const strip = container.querySelector('[aria-label="Collaborators"]');
    expect(strip?.textContent).toContain("Ada");
    expect(strip?.textContent).toContain("Grace");
    expect(strip?.textContent).not.toContain("Me");
    expect(strip?.querySelectorAll("span[title]")).toHaveLength(2);
  });

  it("renders nothing when the Project room holds only this session", () => {
    const container = render([
      participant("Me", { x: 0, y: 0 }, {
        project_room_session_id: LOCAL_SESSION_ID,
      }),
    ]);

    expect(container.textContent).toBe("");
  });
});
