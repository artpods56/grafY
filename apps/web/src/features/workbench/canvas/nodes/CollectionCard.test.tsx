// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { NodeSpec, PlacedLibraryItem, Port } from "@/lib/api";

import { createWorkflowNodeData, type WorkflowNodeData } from "../types";
import { COLLECTION_PORT, type CollectionMember } from "../../model/collection";
import { CollectionCard } from "./CollectionCard";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const mocks = vi.hoisted(() => ({
  items: [] as PlacedLibraryItem[],
  /** The bytes each artifact serves, as the card's read of them. */
  text: {} as Record<string, { text: string; truncated: boolean } | null>,
  read: [] as string[],
  artifactTypes: [] as {
    key: { id: string; schema_version: number };
    title: string;
    export_formats?: { content_type: string }[];
    bundle?: { format: string };
  }[],
}));

vi.mock("@xyflow/react", () => ({
  useNodeId: () => null,
  useUpdateNodeInternals: () => vi.fn(),
  useViewport: () => ({ zoom: 1 }),
  useEdges: () => [],
  useNodesData: () => null,
  useConnection: (selector: (state: { inProgress: boolean }) => unknown) =>
    selector({ inProgress: false }),
  useNodeConnections: () => [],
  useStore: (selector: (state: unknown) => unknown) =>
    selector({ edges: [], nodeLookup: new Map() }),
  Handle: (props: { id?: string; "aria-label"?: string }) => (
    <span data-testid="card-port" aria-label={props["aria-label"]} />
  ),
  Position: { Left: "left", Right: "right" },
}));

vi.mock("swr", () => ({
  default: (key: readonly unknown[] | string | null) => {
    if (key === null) return { data: undefined };
    if (typeof key === "string")
      return { data: { artifact_types: mocks.artifactTypes } };
    if (key[0] === "artifact-card-text") {
      const artifactId = String(key[2]);
      mocks.read.push(artifactId);
      return { data: mocks.text[artifactId] ?? undefined };
    }
    return { data: { folders: [], items: mocks.items } };
  },
}));

const workspace = {
  id: "workspace-1",
  slug: "team",
  name: "Local",
  kind: "personal" as const,
  role: "owner" as const,
  capabilities: [],
};

vi.mock("@/features/workspaces/WorkspaceLayout", () => ({
  useWorkspaceContext: () => ({
    workspace,
    workspaces: [],
    refreshWorkspaces: async () => undefined,
  }),
  useOptionalWorkspaceContext: () => ({
    workspace,
    workspaces: [],
    refreshWorkspaces: async () => undefined,
  }),
}));

vi.mock("@base-ui/react/menu", () => ({
  Menu: {
    Root: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    Trigger: ({ children }: { children: React.ReactNode }) => (
      <button type="button">{children}</button>
    ),
    Portal: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    Positioner: ({ children }: { children: React.ReactNode }) => (
      <>{children}</>
    ),
    Popup: ({ children }: { children: React.ReactNode }) => (
      <div role="dialog">{children}</div>
    ),
    Item: ({ children }: { children: React.ReactNode }) => (
      <button type="button">{children}</button>
    ),
    Group: ({ children }: { children: React.ReactNode }) => (
      <div role="group">{children}</div>
    ),
    GroupLabel: ({ children }: { children: React.ReactNode }) => (
      <div>{children}</div>
    ),
    Separator: () => <hr />,
    RadioGroup: ({ children }: { children: React.ReactNode }) => (
      <div role="radiogroup">{children}</div>
    ),
    RadioItem: ({ children }: { children: React.ReactNode }) => (
      <button type="button">{children}</button>
    ),
    RadioItemIndicator: ({ children }: { children?: React.ReactNode }) => (
      <>{children}</>
    ),
  },
}));

const MESSAGE = { id: "prompt.message", schema_version: 1 };

const itemsPort: Port = {
  kind: "artifact",
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
};

const outPort: Port = {
  ...itemsPort,
  direction: "output",
  shape: "many",
  accepted_shapes: ["many"],
  instance_plugs: false,
  variadic: false,
};

const collectSpec: NodeSpec = {
  operator_id: "sequence.collect",
  operator_version: 1,
  plugin_slug: "builtin",
  origin: "builtin",
  title: "Collect",
  description: "Collect",
  catalog_visible: true,
  runnable: true,
  config_schema: {},
  input_schema: {},
  output_schema: {},
  inputs: [itemsPort],
  outputs: [outPort],
};

function member(plugId: string, artifactId: string): CollectionMember {
  return {
    plugId,
    kind: "library",
    originId: `origin-${plugId}`,
    refs: [
      {
        artifact_id: artifactId,
        artifact_type: MESSAGE.id,
        schema_version: MESSAGE.schema_version,
      },
    ],
  };
}

function libraryItem(artifactId: string, name: string): PlacedLibraryItem {
  return {
    name,
    folder_id: null,
    provenance: {
      source: "upload",
      call_path: [],
      saved_at: "2026-01-01T00:00:00Z",
      original_filename: name,
    },
    artifact: {
      artifact_id: artifactId,
      artifact_type: MESSAGE.id,
      schema_version: MESSAGE.schema_version,
      content_type: "application/json",
      byte_size: 96,
    },
  };
}

const mountedRoots: ReturnType<typeof createRoot>[] = [];

function mount(
  members: readonly CollectionMember[],
  { selected = false }: { selected?: boolean } = {},
) {
  const data: WorkflowNodeData = {
    ...createWorkflowNodeData(
      collectSpec,
      members.map((m) => ({
        id: m.plugId,
        port: COLLECTION_PORT,
      })),
    ),
    collectionMembers: members,
    artifactTypeBindings: { T: MESSAGE },
  };
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  mountedRoots.push(root);
  act(() => {
    root.render(
      <CollectionCard
        id="collection"
        data={data}
        selected={selected}
        dragging={false}
      />,
    );
  });
  return container;
}

afterEach(() => {
  act(() => {
    for (const root of mountedRoots) root.unmount();
  });
  mountedRoots.length = 0;
  document.body.replaceChildren();
  mocks.items = [];
  mocks.text = {};
  mocks.read = [];
  mocks.artifactTypes = [];
});

describe("collection members on the canvas", () => {
  it("shows the front member's JSON instead of a file tile", () => {
    mocks.items = [libraryItem("m1", "prompt.message")];
    mocks.text.m1 = {
      text: '{"role":"user","content":"Where is the boat?"}',
      truncated: false,
    };

    const container = mount([member("plug-1", "m1")]);

    expect(mocks.read).toContain("m1");
    const body = container.querySelector('[data-artifact-value="true"]');
    expect(body?.textContent).toContain('"role": "user"');
    expect(body?.textContent).toContain('"content": "Where is the boat?"');
    // The tile it replaces is gone, not hidden behind the words.
    expect(container.querySelector("svg.lucide-file")).toBeNull();
  });

  it("keeps the file tile for bytes it cannot read", () => {
    mocks.items = [libraryItem("m1", "blob.bin")];
    // Binary bytes: the card's read comes back with nothing to print.
    mocks.text.m1 = null;

    const container = mount([member("plug-1", "m1")]);

    expect(mocks.read).toContain("m1");
    expect(container.querySelector('[data-artifact-value="true"]')).toBeNull();
    expect(container.textContent).toContain("prompt.message");
  });

  it("keeps the file tile for a PDF, which has no text to read", () => {
    mocks.items = [
      {
        ...libraryItem("m1", "report.pdf"),
        artifact: {
          artifact_id: "m1",
          artifact_type: "file.pdf",
          schema_version: 1,
          content_type: "application/pdf",
          byte_size: 40_000,
        },
      },
    ];

    const container = mount([
      {
        plugId: "plug-1",
        kind: "library",
        originId: "origin-1",
        refs: [
          { artifact_id: "m1", artifact_type: "file.pdf", schema_version: 1 },
        ],
      },
    ]);

    expect(mocks.read).toEqual([]);
    expect(container.querySelector('[data-artifact-value="true"]')).toBeNull();
  });

  it("puts the members behind the front one down as plain plates", () => {
    mocks.items = [libraryItem("m1", "a"), libraryItem("m2", "b")];
    mocks.text.m1 = { text: '{"n":1}', truncated: false };
    mocks.text.m2 = { text: '{"n":2}', truncated: false };

    const container = mount([member("plug-1", "m1"), member("plug-2", "m2")]);

    // One body of words, and the stack's other layers are unmarked plates.
    expect(
      container.querySelectorAll('[data-artifact-value="true"]'),
    ).toHaveLength(1);
    expect(container.textContent).toContain('"n": 1');
    expect(
      container.querySelectorAll("[data-stack-item]").length,
    ).toBeGreaterThan(1);
  });
});
