// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Workspace } from "@/lib/api";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const testState = vi.hoisted(() => ({
  push: vi.fn(),
  create: vi.fn(),
}));
const mountedRoots = new Set<Root>();

const location: Workspace = {
  id: "personal-location",
  slug: "personal-user",
  name: "Personal",
  kind: "personal",
  role: "owner",
  capabilities: ["view_graph", "create_graph", "create_template"],
};

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
  useWorkspaces: () => ({ data: [location] }),
  useSavedGraphs: () => ({
    data: {
      graphs: [
        {
          id: "source-graph",
          name: "Quarterly analysis",
          revision: 9,
          node_count: 3,
          edge_count: 2,
          updated_at: "2026-08-11T08:00:00Z",
        },
      ],
    },
    error: undefined,
    isLoading: false,
    mutate: vi.fn(),
  }),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    createWorkspaceTemplate: testState.create,
  };
});

import { SaveAsTemplate } from "./SaveAsTemplate";

async function renderSaveFlow(
  source: Parameters<typeof SaveAsTemplate>[0]["source"] = {
    workspaceId: location.id,
    graphId: "source-graph",
    revision: 7,
  },
): Promise<{
  container: HTMLDivElement;
  root: Root;
}> {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  mountedRoots.add(root);
  await act(async () => root.render(<SaveAsTemplate source={source} />));
  return { container, root };
}

beforeEach(() => {
  testState.push.mockReset();
  testState.create.mockReset();
});

afterEach(async () => {
  await act(async () => {
    for (const root of mountedRoots) root.unmount();
  });
  mountedRoots.clear();
  vi.unstubAllGlobals();
  document.body.replaceChildren();
});

describe("save as template flow", () => {
  it.each([
    ["fine", true, true],
    ["coarse", false, false],
  ])(
    "focuses the template name on a %s pointer only when appropriate",
    async (_pointer, matches, shouldFocus) => {
      const matchMedia = vi.fn().mockReturnValue({ matches });
      vi.stubGlobal("matchMedia", matchMedia);

      const { container } = await renderSaveFlow();
      const nameInput = container.querySelector("input");

      expect(matchMedia).toHaveBeenCalledWith("(pointer: fine)");
      expect(document.activeElement === nameInput).toBe(shouldFocus);
    },
  );

  it("retries the exact-revision snapshot and returns to the template library", async () => {
    testState.create
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({ id: "created-template" });
    const { container } = await renderSaveFlow();
    expect(container.textContent).toContain("revision 7 · My graphs");

    const form = container.querySelector("form");
    await act(async () => {
      form?.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      );
    });
    expect(container.textContent).toContain(
      "Your template is unchanged; try again.",
    );

    await act(async () => {
      form?.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      );
    });
    expect(testState.create).toHaveBeenLastCalledWith("personal-location", {
      source_graph_id: "source-graph",
      source_revision: 7,
      name: "Quarterly analysis",
      description: null,
    });
    expect(testState.push).toHaveBeenCalledWith(
      "/templates?created=created-template",
    );
  });

  it("resets draft state when the exact source revision changes", async () => {
    const { container, root } = await renderSaveFlow();
    const nameInput = container.querySelector<HTMLInputElement>("input");
    const descriptionInput =
      container.querySelector<HTMLTextAreaElement>("textarea");

    await act(async () => {
      if (nameInput) {
        nameInput.value = "Unsaved custom name";
        nameInput.dispatchEvent(new Event("input", { bubbles: true }));
      }
      if (descriptionInput) {
        descriptionInput.value = "Unsaved description";
        descriptionInput.dispatchEvent(new Event("input", { bubbles: true }));
      }
    });

    expect(nameInput?.value).toBe("Unsaved custom name");
    expect(descriptionInput?.value).toBe("Unsaved description");

    await act(async () =>
      root.render(
        <SaveAsTemplate
          source={{
            workspaceId: location.id,
            graphId: "source-graph",
            revision: 8,
          }}
        />,
      ),
    );

    expect(container.querySelector<HTMLInputElement>("input")?.value).toBe(
      "Quarterly analysis",
    );
    expect(
      container.querySelector<HTMLTextAreaElement>("textarea")?.value,
    ).toBe("");
    expect(container.textContent).toContain("revision 8 · My graphs");
  });

  it("fails closed when the route has no exact source", async () => {
    const { container } = await renderSaveFlow(null);
    expect(container.textContent).toContain("Source graph is missing");
    expect(container.querySelector("form")).toBeNull();
  });
});
