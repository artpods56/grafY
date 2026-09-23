import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
}));

vi.mock("@xyflow/react", () => ({
  useEdges: () => [],
  useNodesData: () => null,
  useUpdateNodeInternals: () => () => undefined,
}));

vi.mock("@/features/workspaces/WorkspaceLayout", () => ({
  useWorkspaceContext: () => ({ workspace: { id: "workspace-1" } }),
}));

vi.mock("@/hooks/use-api", () => ({
  useNodeRegistry: () => ({ data: null }),
}));

vi.mock("./CanvasNodeShell", () => ({
  useCanvasNodeShell: () => ({ gridWidth: 250, fillMinHeight: false }),
  CanvasNodeShell: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
}));

vi.mock("./CanvasNodeChrome", () => ({
  CanvasNodeHeader: () => <span>Generic viewer</span>,
  CanvasPortRail: () => null,
  CanvasPortTab: () => null,
  canvasNodeInteractionProps: () => ({}),
}));

vi.mock("./ArtifactCardBody", () => ({
  ArtifactCardBody: ({ value }: { value: unknown }) => (
    <span data-artifact-value={value === null ? "null" : "set"} />
  ),
}));

import { ARTIFACT_VIEWER_NODE_TYPE } from "../artifact-viewer";
import ArtifactViewerNodeCard from "./ArtifactViewerNode";

describe("ArtifactViewerNode artifact mode", () => {
  it("renders the raw artifact body for a linked viewer without a saved ref", () => {
    const html = renderToStaticMarkup(
      <ArtifactViewerNodeCard
        id="viewer-1"
        type={ARTIFACT_VIEWER_NODE_TYPE}
        data={{ layout: { width: 250 }, mode: "artifact", artifactRef: null }}
        dragging={false}
        zIndex={0}
        selectable
        deletable
        selected={false}
        draggable
        isConnectable
        positionAbsoluteX={0}
        positionAbsoluteY={0}
      />,
    );

    expect(html).toContain('data-artifact-value="null"');
  });
});
