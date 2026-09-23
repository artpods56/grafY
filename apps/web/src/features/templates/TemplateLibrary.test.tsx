// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { GraphFolder, GraphTemplate, Workspace } from "@/lib/api";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const testState = vi.hoisted(() => ({
  push: vi.fn(),
  mutate: vi.fn().mockResolvedValue(undefined),
  instantiate: vi.fn(),
  archive: vi.fn(),
  folders: [] as GraphFolder[],
  folderError: undefined as Error | undefined,
  foldersLoading: false,
  workspaces: [] as Workspace[],
  locatedTemplates: [] as Array<{
    template: GraphTemplate;
    location: Workspace;
  }>,
  swrError: undefined as Error | undefined,
  swrIsLoading: false,
}));

const locations: readonly Workspace[] = [
  {
    id: "personal-location",
    slug: "personal-user",
    name: "Personal",
    kind: "personal",
    role: "owner",
    capabilities: [
      "view_graph",
      "create_graph",
      "create_template",
      "manage_template_library",
    ],
  },
  {
    id: "team-location",
    slug: "research-team",
    name: "Research team",
    kind: "shared",
    role: "viewer",
    capabilities: ["view_graph"],
  },
];

const templates: readonly GraphTemplate[] = [
  {
    id: "template-analysis",
    workspace_id: "personal-location",
    source_graph_id: "graph-analysis",
    source_revision: 4,
    source_graph_name: "Quarterly analysis",
    created_by_user_id: "user-1",
    name: "Analysis starter",
    description: "A clean analysis graph",
    state: "active",
    node_count: 3,
    edge_count: 2,
    created_at: "2026-08-11T08:00:00Z",
    updated_at: "2026-08-11T08:00:00Z",
  },
  {
    id: "template-map",
    workspace_id: "team-location",
    source_graph_id: "graph-map",
    source_revision: 2,
    source_graph_name: "Field survey map",
    created_by_user_id: "user-2",
    name: "Map review",
    description: "Inspect field geometry",
    state: "active",
    node_count: 5,
    edge_count: 4,
    created_at: "2026-08-11T09:00:00Z",
    updated_at: "2026-08-11T09:00:00Z",
  },
];

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: testState.push }),
}));

vi.mock("next/link", () => ({
  default: ({ children, ...props }: React.ComponentProps<"a">) => (
    <a {...props}>{children}</a>
  ),
}));

vi.mock("@/features/auth/AuthSessionBoundary", () => ({
  useAuthSession: () => ({
    session: { user_id: "user-1" },
    logout: vi.fn(),
  }),
}));

vi.mock("@/features/workspaces/WorkspaceLayout", () => ({
  WorkspaceRail: () => null,
}));

vi.mock("@/hooks/use-api", () => ({
  useWorkspaces: () => ({ data: testState.workspaces }),
}));

vi.mock("swr", () => ({
  default: (key: unknown) =>
    Array.isArray(key) && key[0] === "graph-folders"
      ? {
          data: { folders: testState.folders },
          error: testState.folderError,
          isLoading: testState.foldersLoading,
        }
      : {
          data: testState.locatedTemplates,
          error: testState.swrError,
          isLoading: testState.swrIsLoading,
          mutate: testState.mutate,
        },
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    listWorkspaceGraphFolders: vi.fn(),
    listWorkspaceTemplates: vi.fn(),
    archiveWorkspaceTemplate: testState.archive,
    instantiateWorkspaceTemplate: testState.instantiate,
  };
});

import {
  TemplateLibrary,
  filterLocatedTemplates,
  nextTemplateKey,
  templatePreviewSummary,
} from "./TemplateLibrary";

function button(container: HTMLElement, label: string): HTMLButtonElement {
  const match = [...container.querySelectorAll("button")].find((candidate) =>
    candidate.textContent?.includes(label),
  );
  if (!(match instanceof HTMLButtonElement)) {
    throw new Error(`Button not found: ${label}`);
  }
  return match;
}

async function renderLibrary(): Promise<{
  container: HTMLDivElement;
  root: Root;
}> {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => root.render(<TemplateLibrary />));
  return { container, root };
}

beforeEach(() => {
  testState.push.mockReset();
  testState.instantiate.mockReset();
  testState.archive.mockReset();
  testState.mutate.mockClear();
  testState.folders = [
    {
      id: "folder-fieldwork",
      name: "Fieldwork",
      created_at: "2026-08-11T08:00:00Z",
      updated_at: "2026-08-11T08:00:00Z",
    },
  ];
  testState.folderError = undefined;
  testState.foldersLoading = false;
  testState.workspaces = [...locations];
  testState.locatedTemplates = [
    { template: templates[0]!, location: locations[0]! },
    { template: templates[1]!, location: locations[1]! },
  ];
  testState.swrError = undefined;
  testState.swrIsLoading = false;
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    callback(0);
    return 1;
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.replaceChildren();
});

describe("template library search and preview", () => {
  it("filters across source/location metadata and supports keyboard inspection", () => {
    const located = [
      { template: templates[0]!, location: locations[0]! },
      { template: templates[1]!, location: locations[1]! },
    ];

    expect(filterLocatedTemplates(located, "survey")).toEqual([located[1]]);
    expect(filterLocatedTemplates(located, "my graphs")).toEqual([located[0]]);
    expect(nextTemplateKey(located, null, 1)).toBe(
      "personal-location:template-analysis",
    );
    expect(
      nextTemplateKey(located, "personal-location:template-analysis", 1),
    ).toBe("team-location:template-map");
    expect(templatePreviewSummary(templates[1]!)).toBe(
      "5 nodes · 4 connections",
    );
  });

  it("renders source provenance and moves preview selection with arrow keys", async () => {
    const { container, root } = await renderLibrary();
    expect(container.textContent).toContain("Quarterly analysis · revision 4");
    expect(container.textContent).toContain("3 nodes · 2 connections");

    const search = container.querySelector("#template-search");
    await act(async () => {
      search?.dispatchEvent(
        new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }),
      );
    });
    expect(container.textContent).toContain("Field survey map · revision 2");
    expect(container.textContent).toContain("5 nodes · 4 connections");
    await act(async () => root.unmount());
  });

  it("renders recoverable loading, error, empty, and no-result states", async () => {
    testState.swrIsLoading = true;
    let rendered = await renderLibrary();
    expect(rendered.container.textContent).toContain("Loading templates");
    await act(async () => rendered.root.unmount());

    testState.swrIsLoading = false;
    testState.swrError = new Error("offline");
    rendered = await renderLibrary();
    expect(rendered.container.textContent).toContain(
      "Templates could not be loaded",
    );
    await act(async () => {
      button(rendered.container, "Retry").dispatchEvent(
        new MouseEvent("click", { bubbles: true }),
      );
    });
    expect(testState.mutate).toHaveBeenCalledOnce();
    await act(async () => rendered.root.unmount());

    testState.swrError = undefined;
    testState.locatedTemplates = [];
    rendered = await renderLibrary();
    expect(rendered.container.textContent).toContain("No templates yet");
    await act(async () => rendered.root.unmount());

    testState.locatedTemplates = [
      { template: templates[0]!, location: locations[0]! },
    ];
    rendered = await renderLibrary();
    expect(
      rendered.container.querySelector(".grafy-template-results__heading h2")
        ?.textContent,
    ).toBe("1 template");
    const search = rendered.container.querySelector("#template-search");
    await act(async () => {
      if (search instanceof HTMLInputElement) {
        const valueSetter = Object.getOwnPropertyDescriptor(
          HTMLInputElement.prototype,
          "value",
        )?.set;
        valueSetter?.call(search, "no such graph");
      }
      search?.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(rendered.container.textContent).toContain("No matching templates");
    await act(async () => rendered.root.unmount());
  });

  it("explains when templates are readable but no destination is writable", async () => {
    testState.workspaces = locations.map((location) => ({
      ...location,
      role: "viewer",
      capabilities: ["view_graph"],
    }));
    const { container, root } = await renderLibrary();
    expect(container.textContent).toContain(
      "you need graph creation permission in a save location",
    );
    expect(button(container, "Use template").disabled).toBe(true);
    await act(async () => root.unmount());
  });
});

describe("template use flow", () => {
  it("assigns the copy to an existing folder in the destination", async () => {
    testState.instantiate.mockResolvedValue({
      destination_workspace_id: "personal-location",
      graph_id: "created-graph",
      folder_id: "folder-fieldwork",
    });
    const { container, root } = await renderLibrary();

    await act(async () => {
      button(container, "Use template").dispatchEvent(
        new MouseEvent("click", { bubbles: true }),
      );
    });
    const form = container.querySelector(".grafy-template-use");
    const folderSelect = form?.querySelectorAll("select")[1];
    await act(async () => {
      if (folderSelect instanceof HTMLSelectElement) {
        const valueSetter = Object.getOwnPropertyDescriptor(
          HTMLSelectElement.prototype,
          "value",
        )?.set;
        valueSetter?.call(folderSelect, "folder-fieldwork");
        folderSelect.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
    await act(async () => {
      form?.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      );
    });

    expect(testState.instantiate).toHaveBeenCalledWith(
      "personal-location",
      "template-analysis",
      {
        destination_workspace_id: "personal-location",
        name: "Analysis starter",
        folder_id: "folder-fieldwork",
      },
    );
    await act(async () => root.unmount());
  });

  it("keeps the form open after failure and directly opens a successful copy", async () => {
    testState.instantiate
      .mockRejectedValueOnce(new Error("network unavailable"))
      .mockResolvedValueOnce({
        destination_workspace_id: "personal-location",
        graph_id: "created-graph",
      });
    const { container, root } = await renderLibrary();

    await act(async () => {
      button(container, "Use template").dispatchEvent(
        new MouseEvent("click", { bubbles: true }),
      );
    });
    const form = container.querySelector(".grafy-template-use");
    expect(form).not.toBeNull();

    await act(async () => {
      form?.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      );
    });
    expect(container.getAttribute("aria-busy")).toBeNull();
    expect(container.textContent).toContain(
      "Your template is unchanged; try again.",
    );
    expect(button(container, "Try again")).not.toBeNull();

    await act(async () => {
      form?.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      );
    });
    expect(testState.instantiate).toHaveBeenCalledTimes(2);
    expect(testState.push).toHaveBeenCalledWith(
      "/workspaces/personal-user/graphs/created-graph",
    );
    await act(async () => root.unmount());
  });

  it("restores focus to Use template when the copy form is cancelled", async () => {
    const { container, root } = await renderLibrary();
    const useButton = button(container, "Use template");
    await act(async () => {
      useButton.focus();
      useButton.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await act(async () => {
      button(container, "Cancel").dispatchEvent(
        new MouseEvent("click", { bubbles: true }),
      );
    });
    expect(document.activeElement).toBe(button(container, "Use template"));
    await act(async () => root.unmount());
  });
});
