// @vitest-environment jsdom

import * as React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ArtifactRef, PlacedLibraryItem } from "@/lib/api";
import type { ArtifactCardValue } from "../artifact-card";
import type { ArtifactViewerNodeData } from "../artifact-viewer";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const libraryMocks = vi.hoisted(() => ({ items: [] as PlacedLibraryItem[] }));

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
}));

vi.mock("@xyflow/react", () => ({
  useUpdateNodeInternals: () => vi.fn(),
  useViewport: () => ({ zoom: 1 }),
}));

vi.mock("swr", () => ({
  default: () => ({ data: { folders: [], items: libraryMocks.items } }),
}));

vi.mock("@/features/workspaces/WorkspaceLayout", () => ({
  useWorkspaceContext: () => ({
    workspace: {
      id: "workspace-1",
      slug: "team",
      name: "Local",
      kind: "personal",
      role: "owner",
      capabilities: [],
    },
    workspaces: [],
    refreshWorkspaces: async () => undefined,
  }),
}));

vi.mock("@base-ui/react/menu", () => ({
  Menu: {
    Root: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    Trigger: ({
      children,
      ...props
    }: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
      <button type="button" {...props}>
        {children}
      </button>
    ),
    Portal: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    Positioner: ({ children }: { children: React.ReactNode }) => (
      <>{children}</>
    ),
    Popup: ({ children }: { children: React.ReactNode }) => (
      <div role="dialog">{children}</div>
    ),
    Item: ({
      children,
      ...props
    }: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
      <button type="button" {...props}>
        {children}
      </button>
    ),
  },
}));

import { ArtifactCardBody } from "./ArtifactCardBody";

function libraryItem(artifactId: string, name: string): PlacedLibraryItem {
  return {
    name,
    folder_id: null,
    provenance: {
      source: "upload",
      saved_at: "2026-01-01T00:00:00Z",
      original_filename: name,
    },
    artifact: {
      artifact_id: artifactId,
      artifact_type: "file.jpeg",
      schema_version: 1,
      content_type: "image/jpeg",
      byte_size: 2_516_586,
    },
  };
}

function single(artifactId: string): ArtifactRef {
  return {
    artifact_id: artifactId,
    artifact_type: "file.jpeg",
    schema_version: 1,
  };
}

function sequence(artifactIds: readonly string[]): ArtifactCardValue {
  return {
    artifact_type: "file.jpeg",
    schema_version: 1,
    item_refs: artifactIds.map(single),
    ordered: true,
    index_key: "order_index",
    sequence_id: "22222222-2222-4222-8222-222222222222",
  };
}

function mount(
  value: ArtifactCardValue,
  data: Partial<ArtifactViewerNodeData> = {},
) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  const nodeData: ArtifactViewerNodeData = {
    layout: { width: 264 },
    mode: null,
    ...data,
  };
  React.act(() => {
    root.render(
      <ArtifactCardBody id="artifact-viewer-1" data={nodeData} value={value} />,
    );
  });
  return { container, root };
}

afterEach(() => {
  document.body.replaceChildren();
  libraryMocks.items = [];
});

describe("artifact on the canvas", () => {
  beforeEach(() => {
    libraryMocks.items = [libraryItem("a1", "boat.jpg")];
  });

  it("paints a single image with its name floating above it", () => {
    const { container } = mount(single("a1"));
    const image = container.querySelector("img");

    expect(image?.getAttribute("src")).toContain("/artifacts/a1/content");
    expect(container.textContent).toContain("boat.jpg");
    expect(container.textContent).toContain("file.jpeg@1");
    expect(container.querySelector("ol")).toBeNull();
    expect(
      container.querySelector('[data-node-pickup-shadow="true"]'),
    ).not.toBeNull();
    // The container sets the size and the artifact fits inside it, so a portrait
    // photo takes the same room on the canvas as a wide map.
    const media = container.querySelector<HTMLElement>("[data-artifact-media]");
    expect(media?.style.height).toBe("198px");
  });

  it("passes its artifact out when the ball is dragged", () => {
    const { container } = mount(single("a1"));
    const ball = container.querySelector<HTMLButtonElement>(
      '[aria-label="Pass file.jpeg@1 to a node input"]',
    );
    const stored = new Map<string, string>();
    const dataTransfer = {
      effectAllowed: "",
      setData: (mime: string, value: string) => stored.set(mime, value),
    };
    const event = new Event("dragstart", { bubbles: true, cancelable: true });
    Object.defineProperty(event, "dataTransfer", { value: dataTransfer });

    React.act(() => {
      ball?.dispatchEvent(event);
    });

    expect(
      JSON.parse(stored.get("application/x-grafy-artifact") ?? "{}"),
    ).toEqual({
      value: single("a1"),
      shape: "one",
    });
  });

  it("shows a run of artifacts as a stack counted by item", () => {
    const { container } = mount(sequence(["a1", "a2", "a3"]));

    expect(container.textContent).toContain("3 artifacts");
    expect(container.textContent).toContain("3 items");
    expect(container.textContent).toContain("file.jpeg@1 · 3 items");
  });

  it("reorders the run it passes on", () => {
    libraryMocks.items = [
      libraryItem("a1", "boat.jpg"),
      libraryItem("a2", "coast.jpg"),
    ];
    const onRefsChange = vi.fn();
    const { container } = mount(sequence(["a1", "a2"]), { onRefsChange });
    const reorder = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Reorder items"),
    );

    React.act(() => {
      reorder?.click();
    });
    const moveLater = container.querySelector<HTMLButtonElement>(
      '[aria-label="Move later in the order"]',
    );

    React.act(() => {
      moveLater?.click();
    });

    expect(onRefsChange).toHaveBeenCalledTimes(1);
    const committed = onRefsChange.mock.calls[0][1];
    expect(
      "item_refs" in committed
        ? committed.item_refs.map(
            (ref: { artifact_id: string }) => ref.artifact_id,
          )
        : null,
    ).toEqual(["a2", "a1"]);
    expect("sequence_id" in committed ? committed.sequence_id : null).toBe(
      "22222222-2222-4222-8222-222222222222",
    );
  });

  it("paints a produced artifact the library never listed", () => {
    const { container } = mount(single("zz"));

    expect(container.querySelector("img")?.getAttribute("src")).toContain(
      "/artifacts/zz/content",
    );
    expect(container.textContent).toContain("file.jpeg@1");
  });

  it("shows a file tile for a type it cannot paint", () => {
    const { container } = mount({
      artifact_id: "csv1",
      artifact_type: "file.csv",
      schema_version: 1,
    });

    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("not in this library");
    expect(container.textContent).toContain("file.csv@1");
  });
});
