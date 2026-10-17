// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { GraphFolder, GraphTemplate, Workspace } from "@/lib/api";
import { ApiError } from "@/lib/api/client";

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

  it("sends one copy request when submit fires twice before React repaints", async () => {
    testState.instantiate.mockResolvedValue({
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
    await act(async () => {
      form?.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      );
      form?.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      );
    });

    expect(testState.instantiate).toHaveBeenCalledTimes(1);
    expect(testState.push).toHaveBeenCalledWith(
      "/workspaces/personal-user/graphs/created-graph",
    );
    await act(async () => root.unmount());
  });
});

describe("copy form follows the inspected template", () => {
  it("closes the form instead of copying a different template under the typed name", async () => {
    testState.instantiate.mockResolvedValue({
      destination_workspace_id: "personal-location",
      graph_id: "created-graph",
    });
    const { container, root } = await renderLibrary();
    await act(async () => {
      button(container, "Use template").dispatchEvent(
        new MouseEvent("click", { bubbles: true }),
      );
    });
    expect(
      (container.querySelector(".grafy-template-use input") as HTMLInputElement)
        .value,
    ).toBe("Analysis starter");

    const search = container.querySelector("#template-search");
    await act(async () => {
      search?.dispatchEvent(
        new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }),
      );
    });

    expect(container.querySelector(".grafy-template-use")).toBeNull();
    expect(
      container.querySelector(".grafy-template-preview h2")?.textContent,
    ).toBe("Map review");
    expect(testState.instantiate).not.toHaveBeenCalled();
    await act(async () => root.unmount());
  });

  it("keeps the form open when arrow inspection lands on the same template", async () => {
    testState.locatedTemplates = [
      { template: templates[0]!, location: locations[0]! },
    ];
    const { container, root } = await renderLibrary();
    await act(async () => {
      button(container, "Use template").dispatchEvent(
        new MouseEvent("click", { bubbles: true }),
      );
    });
    const search = container.querySelector("#template-search");
    await act(async () => {
      search?.dispatchEvent(
        new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }),
      );
    });

    expect(container.querySelector(".grafy-template-use")).not.toBeNull();
    await act(async () => root.unmount());
  });
});

describe("template archive flow", () => {
  it("archives the inspected template and refreshes the library", async () => {
    vi.stubGlobal(
      "confirm",
      vi.fn(() => true),
    );
    testState.archive.mockResolvedValue(undefined);
    const { container, root } = await renderLibrary();

    await act(async () => {
      button(container, "Archive").dispatchEvent(
        new MouseEvent("click", { bubbles: true }),
      );
    });

    expect(testState.archive).toHaveBeenCalledWith(
      "personal-location",
      "template-analysis",
    );
    expect(testState.mutate).toHaveBeenCalledOnce();
    expect(container.textContent).not.toContain("could not be created");
    await act(async () => root.unmount());
  });

  it("keeps an archive failure with the template it happened to", async () => {
    vi.stubGlobal(
      "confirm",
      vi.fn(() => true),
    );
    testState.archive.mockRejectedValueOnce(new Error("offline"));
    const { container, root } = await renderLibrary();

    await act(async () => {
      button(container, "Archive").dispatchEvent(
        new MouseEvent("click", { bubbles: true }),
      );
    });
    expect(container.textContent).toContain(
      "Your template is unchanged; try again.",
    );

    const search = container.querySelector("#template-search");
    await act(async () => {
      search?.dispatchEvent(
        new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }),
      );
    });
    expect(container.textContent).toContain("Map review");
    expect(container.textContent).not.toContain(
      "Your template is unchanged; try again.",
    );
    await act(async () => root.unmount());
  });
});

function clickButton(container: HTMLElement, label: string): void {
  button(container, label).dispatchEvent(
    new MouseEvent("click", { bubbles: true }),
  );
}

function archiveButton(container: HTMLElement): HTMLButtonElement | undefined {
  return [...container.querySelectorAll("button")].find((candidate) =>
    candidate.textContent?.includes("Archi"),
  ) as HTMLButtonElement | undefined;
}

async function typeSearch(
  container: HTMLElement,
  value: string,
): Promise<void> {
  const search = container.querySelector("#template-search");
  await act(async () => {
    if (search instanceof HTMLInputElement) {
      const valueSetter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )?.set;
      valueSetter?.call(search, value);
    }
    search?.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function submitCopyForm(container: HTMLElement): Promise<void> {
  const form = container.querySelector(".grafy-template-use");
  await act(async () => {
    form?.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );
  });
}

/**
 * The copy form's primary action. Tests reach for it directly because a disabled
 * button still answers a `submit` dispatched on the form, which is what proves the
 * request stays locked when the visible state has not caught up.
 */
function copySubmitButton(container: HTMLElement): HTMLButtonElement {
  const submit = container.querySelector(
    ".grafy-template-use button[type='submit']",
  );
  if (!(submit instanceof HTMLButtonElement)) {
    throw new Error("Copy form action not found");
  }
  return submit;
}

type Deferred = {
  promise: Promise<unknown>;
  settle: (value: unknown) => void;
  reject: (error: unknown) => void;
};

function deferred(): Deferred {
  let settle!: (value: unknown) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise((resolve, rejectNow) => {
    settle = resolve;
    reject = rejectNow;
  });
  return { promise, settle, reject };
}

/** Copy requests that stay pending until the test answers them, in call order. */
function deferredQueue(): { items: Deferred[]; next: () => Promise<unknown> } {
  const items: Deferred[] = [];
  return {
    items,
    next() {
      const item = deferred();
      items.push(item);
      return item.promise;
    },
  };
}

const createdGraph = (id: string) => ({
  destination_workspace_id: "personal-location",
  graph_id: id,
});

async function openCopyFormForInspectedTemplate(
  container: HTMLElement,
): Promise<void> {
  await act(async () => {
    clickButton(container, "Use template");
  });
}

describe("copy requests answer only their own form", () => {
  it("copies another template while a request the person abandoned is still running", async () => {
    const abandoned = deferred();
    testState.instantiate
      .mockImplementationOnce(() => abandoned.promise)
      .mockResolvedValue({
        destination_workspace_id: "personal-location",
        graph_id: "copy-of-map",
      });
    const { container, root } = await renderLibrary();

    await openCopyFormForInspectedTemplate(container);
    await submitCopyForm(container);
    expect(testState.instantiate).toHaveBeenCalledTimes(1);

    // The search box is still reachable, so the request is abandoned in flight
    // and the copy that replaces it belongs to another template.
    await typeSearch(container, "map");
    await openCopyFormForInspectedTemplate(container);
    await submitCopyForm(container);

    expect(testState.instantiate).toHaveBeenNthCalledWith(
      1,
      "personal-location",
      "template-analysis",
      expect.objectContaining({ name: "Analysis starter" }),
    );
    expect(testState.instantiate).toHaveBeenNthCalledWith(
      2,
      "team-location",
      "template-map",
      {
        destination_workspace_id: "personal-location",
        name: "Map review",
        folder_id: null,
      },
    );

    await act(async () => {
      abandoned.settle({
        destination_workspace_id: "personal-location",
        graph_id: "late-copy",
      });
    });
    // Both copies open their own graph when they land. What must not happen is
    // the abandoned request answering for the copy that replaced it.
    expect(testState.push).toHaveBeenCalledWith(
      "/workspaces/personal-user/graphs/copy-of-map",
    );
    await act(async () => root.unmount());
  });

  it("keeps an abandoned copy's failure off the copy that replaced it", async () => {
    const abandoned = deferred();
    const running = deferred();
    testState.instantiate
      .mockImplementationOnce(() => abandoned.promise)
      .mockImplementationOnce(() => running.promise);
    const { container, root } = await renderLibrary();

    await openCopyFormForInspectedTemplate(container);
    await submitCopyForm(container);
    await typeSearch(container, "map");
    await openCopyFormForInspectedTemplate(container);
    await submitCopyForm(container);

    await act(async () => {
      abandoned.reject(new ApiError(422, "A copy named that already exists"));
    });
    expect(container.querySelector(".grafy-template-use__error")).toBeNull();
    expect(button(container, "Creating…").disabled).toBe(true);

    await act(async () => {
      running.reject(new Error("offline"));
    });
    expect(
      container.querySelector(".grafy-template-use__error")?.textContent,
    ).toContain("Your template is unchanged; try again.");
    expect(container.textContent).not.toContain(
      "A copy named that already exists",
    );
    await act(async () => root.unmount());
  });
});

describe("one copy request runs per template", () => {
  it("refuses to copy a template the person returned to while its request runs", async () => {
    const queue = deferredQueue();
    testState.instantiate.mockImplementation(() => queue.next());
    const { container, root } = await renderLibrary();

    // A copy of "Analysis starter" starts and is abandoned mid-flight.
    await openCopyFormForInspectedTemplate(container);
    await submitCopyForm(container);

    // A copy of another template starts and is left running as well.
    await typeSearch(container, "map");
    await openCopyFormForInspectedTemplate(container);
    await submitCopyForm(container);
    expect(testState.instantiate).toHaveBeenCalledTimes(2);

    // Coming back to the first template reopens its form. That form still may
    // not copy: the request started for this same template has not answered.
    await typeSearch(container, "analysis");
    await openCopyFormForInspectedTemplate(container);
    await submitCopyForm(container);
    expect(testState.instantiate).toHaveBeenCalledTimes(2);

    // The abandoned answer belongs to the request that started it, not to the
    // form that reopened afterwards.
    await act(async () => {
      queue.items[0]!.reject(new ApiError(422, "The first request gave up"));
    });
    expect(container.querySelector(".grafy-template-use__error")).toBeNull();

    // Now that the template's own request has answered, this form may start one.
    await submitCopyForm(container);
    expect(testState.instantiate).toHaveBeenCalledTimes(3);
    await act(async () => {
      queue.items[2]!.reject(new ApiError(422, "A copy named that exists"));
    });
    expect(
      container.querySelector(".grafy-template-use__error")?.textContent,
    ).toContain("A copy named that exists");

    await act(async () => {
      queue.items[1]!.settle(createdGraph("copy-of-map"));
    });
    await act(async () => root.unmount());
  });

  it("does not unlock a running copy when another template's copy finishes", async () => {
    const queue = deferredQueue();
    testState.instantiate.mockImplementation(() => queue.next());
    const { container, root } = await renderLibrary();

    await openCopyFormForInspectedTemplate(container);
    await submitCopyForm(container);
    await typeSearch(container, "map");
    await openCopyFormForInspectedTemplate(container);
    await submitCopyForm(container);

    // The second copy lands while the first is still running.
    await act(async () => {
      queue.items[1]!.settle(createdGraph("copy-of-map"));
    });
    expect(testState.push).toHaveBeenCalledWith(
      "/workspaces/personal-user/graphs/copy-of-map",
    );

    await typeSearch(container, "analysis");
    await openCopyFormForInspectedTemplate(container);
    await submitCopyForm(container);
    expect(testState.instantiate).toHaveBeenCalledTimes(2);

    // The first request answering is what releases that template's copy.
    await act(async () => {
      queue.items[0]!.settle(createdGraph("copy-of-analysis"));
    });
    await submitCopyForm(container);
    expect(testState.instantiate).toHaveBeenCalledTimes(3);
    await act(async () => {
      queue.items[2]!.settle(createdGraph("copy-of-analysis-again"));
    });
    await act(async () => root.unmount());
  });
});

describe("a reopened copy form shows the copy still running", () => {
  it("says the copy is running, then lets the form start one when it answers", async () => {
    const running = deferred();
    testState.instantiate.mockImplementationOnce(() => running.promise);
    const { container, root } = await renderLibrary();

    // A copy of "Analysis starter" starts and the person leaves its form.
    await openCopyFormForInspectedTemplate(container);
    await submitCopyForm(container);
    expect(testState.instantiate).toHaveBeenCalledTimes(1);

    // They inspect another template, return to the first, and open the form again.
    await typeSearch(container, "map");
    await typeSearch(container, "analysis");
    await openCopyFormForInspectedTemplate(container);

    // The reopened form names the same request that is still running, so it shows
    // that request instead of an action that would be refused.
    const action = copySubmitButton(container);
    expect(action.disabled).toBe(true);
    expect(action.textContent).toContain("Creating…");
    expect(container.querySelector(".grafy-template-spin")).not.toBeNull();
    expect(button(container, "Cancel").disabled).toBe(true);

    // Submitting the form anyway still cannot send a second request for the
    // template whose copy has not answered.
    await submitCopyForm(container);
    expect(testState.instantiate).toHaveBeenCalledTimes(1);

    // The original request fails. Its answer belongs to the request that started
    // it, so this form becomes usable without taking on that failure.
    await act(async () => {
      running.reject(new ApiError(422, "A copy named that already exists"));
    });
    expect(container.querySelector(".grafy-template-use__error")).toBeNull();
    const retry = copySubmitButton(container);
    expect(retry.disabled).toBe(false);
    expect(retry.textContent).toContain("Create and open");
    expect(button(container, "Cancel").disabled).toBe(false);

    testState.instantiate.mockResolvedValueOnce(createdGraph("copy-on-retry"));
    await submitCopyForm(container);
    expect(testState.instantiate).toHaveBeenCalledTimes(2);
    expect(testState.push).toHaveBeenCalledWith(
      "/workspaces/personal-user/graphs/copy-on-retry",
    );
    await act(async () => root.unmount());
  });

  it("shows the running copy again when a retry from the reopened form fails", async () => {
    const first = deferred();
    const retry = deferred();
    testState.instantiate
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => retry.promise);
    const { container, root } = await renderLibrary();

    await openCopyFormForInspectedTemplate(container);
    await submitCopyForm(container);
    await typeSearch(container, "map");
    await typeSearch(container, "analysis");
    await openCopyFormForInspectedTemplate(container);

    await act(async () => {
      first.settle(createdGraph("copy-of-analysis"));
    });
    expect(copySubmitButton(container).disabled).toBe(false);

    // The form is usable again, and the request it starts shows as running.
    await submitCopyForm(container);
    expect(testState.instantiate).toHaveBeenCalledTimes(2);
    expect(copySubmitButton(container).disabled).toBe(true);

    await act(async () => {
      retry.reject(new ApiError(422, "A copy named that already exists"));
    });
    expect(
      container.querySelector(".grafy-template-use__error")?.textContent,
    ).toContain("A copy named that already exists");
    expect(copySubmitButton(container).textContent).toContain("Try again");
    await act(async () => root.unmount());
  });
});

describe("template archive is one operation at a time", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "confirm",
      vi.fn(() => true),
    );
  });

  it("sends one archive request when the button fires twice before React repaints", async () => {
    const running = deferred();
    testState.archive.mockImplementation(() => running.promise);
    const { container, root } = await renderLibrary();

    await act(async () => {
      const archive = archiveButton(container);
      archive?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      archive?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(testState.archive).toHaveBeenCalledTimes(1);
    await act(async () => {
      running.settle(undefined);
    });
    await act(async () => root.unmount());
  });

  it("keeps the archive button out of reach until the running archive lands", async () => {
    const running = deferred();
    testState.archive.mockImplementation(() => running.promise);
    // Both locations can manage their library, so either result offers Archive.
    testState.locatedTemplates = [
      {
        template: templates[0]!,
        location: {
          ...locations[0]!,
          capabilities: [
            ...locations[0]!.capabilities,
            "manage_template_library",
          ],
        },
      },
      {
        template: templates[1]!,
        location: {
          ...locations[1]!,
          capabilities: [
            ...locations[1]!.capabilities,
            "manage_template_library",
          ],
        },
      },
    ];
    const { container, root } = await renderLibrary();

    await act(async () => {
      archiveButton(container)?.dispatchEvent(
        new MouseEvent("click", { bubbles: true }),
      );
    });
    expect(archiveButton(container)?.textContent).toContain("Archiving");

    const search = container.querySelector("#template-search");
    await act(async () => {
      search?.dispatchEvent(
        new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }),
      );
    });
    const other = archiveButton(container);
    expect(other?.disabled).toBe(true);
    expect(other?.textContent).toContain("Archive");
    expect(other?.title).toContain("An archive is already running.");

    await act(async () => {
      other?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(testState.archive).toHaveBeenCalledTimes(1);
    await act(async () => {
      running.settle(undefined);
    });
    await act(async () => root.unmount());
  });

  it("does not report an archive failure when only the library refresh failed", async () => {
    testState.archive.mockResolvedValue(undefined);
    testState.mutate.mockRejectedValueOnce(new Error("offline"));
    const { container, root } = await renderLibrary();

    await act(async () => {
      archiveButton(container)?.dispatchEvent(
        new MouseEvent("click", { bubbles: true }),
      );
    });

    expect(testState.archive).toHaveBeenCalledTimes(1);
    expect(testState.mutate).toHaveBeenCalledOnce();
    expect(container.querySelector("[role='alert']")).toBeNull();
    expect(container.textContent).not.toContain("Your template is unchanged");
    await act(async () => root.unmount());
  });
});

describe("the copy form follows the result set", () => {
  it("drops the form when its template leaves the results", async () => {
    const { container, root } = await renderLibrary();
    await openCopyFormForInspectedTemplate(container);
    expect(container.querySelector(".grafy-template-use")).not.toBeNull();

    // A teammate archives the inspected template; the list changes underneath
    // the open form without the person touching it.
    testState.locatedTemplates = [
      { template: templates[1]!, location: locations[1]! },
    ];
    const nameInput = container.querySelector<HTMLInputElement>(
      ".grafy-template-use input",
    );
    await act(async () => {
      if (nameInput) {
        const valueSetter = Object.getOwnPropertyDescriptor(
          HTMLInputElement.prototype,
          "value",
        )?.set;
        valueSetter?.call(nameInput, "Typed while the list changed");
        nameInput.dispatchEvent(new Event("input", { bubbles: true }));
      }
    });

    expect(container.querySelector(".grafy-template-use")).toBeNull();
    expect(
      container.querySelector(".grafy-template-preview h2")?.textContent,
    ).toBe("Map review");
    expect(testState.instantiate).not.toHaveBeenCalled();
    await act(async () => root.unmount());
  });
});
