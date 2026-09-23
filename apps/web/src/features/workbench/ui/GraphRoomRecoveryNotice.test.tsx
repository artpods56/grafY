// @vitest-environment jsdom

import * as React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GraphRoomRecoveryNotice } from "./GraphRoomRecoveryNotice";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
}));

describe("GraphRoomRecoveryNotice", () => {
  const roots: ReturnType<typeof createRoot>[] = [];

  afterEach(() => {
    React.act(() => {
      for (const root of roots.splice(0)) root.unmount();
    });
    document.body.replaceChildren();
  });

  it("explains stale safety and exposes manual retry after exhaustion", () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    roots.push(root);
    const onRetry = vi.fn();

    React.act(() => {
      root.render(
        <GraphRoomRecoveryNotice
          readiness="stale"
          status="stopped"
          failure={{
            workspaceId: "workspace-1",
            graphId: "graph-1",
            graphRoomSessionId: "session-1",
            reason: "reconnect_exhausted",
            retryable: true,
            side: "network",
            phase: "connect",
            messageType: null,
            protocolVersion: 1,
            closeCode: 1006,
            detail: "Automatic reconnection stopped.",
          }}
          terminalReason="reconnect_exhausted"
          onRetry={onRetry}
          onReload={() => undefined}
        />,
      );
    });

    expect(container.textContent).toContain("Stale graph — read only");
    expect(container.textContent).toContain(
      "Server-accepted work is preserved",
    );
    expect(container.textContent).toContain(
      "Editing, saving, running, and Module setup are unavailable",
    );
    const retry = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Retry connection"),
    );
    React.act(() => retry?.click());
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("offers reload for terminal protocol incompatibility", () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    roots.push(root);

    React.act(() => {
      root.render(
        <GraphRoomRecoveryNotice
          readiness="stale"
          status="stopped"
          failure={null}
          terminalReason="protocol_incompatible"
          onRetry={() => undefined}
          onReload={() => undefined}
        />,
      );
    });

    expect(container.textContent).toContain("protocols are incompatible");
    expect(container.textContent).toContain("Reload graph");
  });
});
