// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TableArtifactEditor } from "./TableArtifactEditor";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const roots: Root[] = [];

afterEach(async () => {
  for (const root of roots.splice(0)) {
    await act(async () => root.unmount());
  }
  document.body.replaceChildren();
});

describe("TableArtifactEditor", () => {
  it("saves the edited table.data@1 payload", async () => {
    const onSave = vi.fn();
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    roots.push(root);
    await act(async () => {
      root.render(
        <TableArtifactEditor
          workspaceId="ws"
          artifactType="table.data"
          schemaVersion={1}
          initialPayload={{
            columns: [{ id: "name", title: "Name", value_type: "text" }],
            rows: [{ name: "Ada" }],
          }}
          onSave={onSave}
          onCancel={() => {}}
        />,
      );
    });
    const cell = container.querySelector<HTMLInputElement>(
      'input[aria-label="Name, row 1"]',
    );
    const save = [...container.querySelectorAll("button")].find(
      (button) => button.textContent === "Save",
    );
    if (!cell || !save) throw new Error("missing controls");
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )?.set;
    await act(async () => {
      setter?.call(cell, "Grace");
      cell.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => {
      save.click();
    });
    expect(onSave).toHaveBeenCalledWith({
      columns: [{ id: "name", title: "Name", value_type: "text" }],
      rows: [{ name: "Grace" }],
    });
  });
});
