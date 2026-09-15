// @vitest-environment jsdom

import * as React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LibraryDrawer } from "./LibraryDrawer";
import type { LibraryItem } from "@/lib/api";

const listLibraryArtifacts = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", () => ({ listLibraryArtifacts }));

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
}));

const RUN_ITEM: LibraryItem = {
  artifact: {
    artifact_id: "artifact-run",
    artifact_type: "table",
    schema_version: 1,
    content_type: "application/json",
  },
  name: "sales-table",
  provenance: {
    source: "run",
    saved_at: "2026-09-11T12:00:00Z",
    graph_id: "graph-1",
    graph_title: "Sales",
    node_id: "resize-1",
    node_title: "Resize",
    graph_revision: 4,
    execution_id: "execution-1",
  },
  run: {
    execution_id: "execution-1",
    graph_id: "graph-1",
    finished_at: "2026-09-11T11:59:00Z",
  },
};

const UPLOAD_ITEM: LibraryItem = {
  artifact: {
    artifact_id: "artifact-upload",
    artifact_type: "csv",
    schema_version: 1,
    content_type: "text/csv",
  },
  name: "measurements.csv",
  provenance: {
    source: "upload",
    saved_at: "2026-09-11T12:00:00Z",
    original_filename: "measurements.csv",
  },
  run: null,
};

describe("LibraryDrawer", () => {
  const roots: ReturnType<typeof createRoot>[] = [];
  let workspaceCounter = 0;

  afterEach(() => {
    React.act(() => {
      for (const root of roots.splice(0)) root.unmount();
    });
    document.body.replaceChildren();
    listLibraryArtifacts.mockReset();
  });

  async function render(items: LibraryItem[], onOpenRun = vi.fn()) {
    listLibraryArtifacts.mockResolvedValue({ items });
    workspaceCounter += 1;
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    roots.push(root);
    await React.act(async () => {
      root.render(
        <LibraryDrawer
          workspaceId={`workspace-${workspaceCounter}`}
          onClose={vi.fn()}
          onOpenRun={onOpenRun}
        />,
      );
    });
    return { container, onOpenRun };
  }

  it("writes the frozen graph, node, revision and run marker on the row", async () => {
    const { container } = await render([RUN_ITEM]);

    expect(container.textContent).toContain(
      "Sales · Resize · revision 4 · from a run",
    );
  });

  it("links a run-backed item back to its execution", async () => {
    const { container, onOpenRun } = await render([RUN_ITEM]);

    const row = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Sales · Resize"),
    );
    await React.act(async () => {
      row!.click();
    });

    const link = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Open in execution history"),
    );
    expect(link).toBeDefined();
    expect(container.textContent).toContain("run execution-1");

    await React.act(async () => {
      link!.click();
    });

    expect(onOpenRun).toHaveBeenCalledWith("graph-1", "execution-1");
  });

  it("marks an upload with its original filename and offers no run link", async () => {
    const { container } = await render([UPLOAD_ITEM]);

    expect(container.textContent).toContain("uploaded · measurements.csv");
    await React.act(async () => {
      [...container.querySelectorAll("button")]
        .find((button) => button.textContent?.includes("uploaded ·"))!
        .click();
    });
    expect(container.textContent).not.toContain("Open in execution history");
  });

  it("keeps the run link absent once the run is gone", async () => {
    const { container } = await render([{ ...RUN_ITEM, run: null }]);

    expect(container.textContent).toContain(
      "Sales · Resize · revision 4 · from a run",
    );
    await React.act(async () => {
      [...container.querySelectorAll("button")]
        .find((button) => button.textContent?.includes("Sales · Resize"))!
        .click();
    });
    expect(container.textContent).not.toContain("Open in execution history");
  });

  it("says the Library is empty before anything is saved", async () => {
    const { container } = await render([]);

    expect(container.textContent).toContain("Nothing in the Library yet");
  });
});
