// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  JsonArtifactEditor,
  parseJsonObject,
  prettyJson,
} from "./JsonArtifactEditor";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const roots: Root[] = [];

afterEach(async () => {
  for (const root of roots.splice(0)) {
    await act(async () => root.unmount());
  }
  document.body.replaceChildren();
});

async function renderEditor(
  props: Partial<React.ComponentProps<typeof JsonArtifactEditor>> = {},
) {
  const onSave = vi.fn();
  const onCancel = vi.fn();
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  roots.push(root);
  await act(async () => {
    root.render(
      <JsonArtifactEditor
        workspaceId="ws"
        artifactType="json.schema"
        schemaVersion={1}
        initialPayload={{ value: '{"type":"object"}' }}
        onSave={onSave}
        onCancel={onCancel}
        {...props}
      />,
    );
  });
  return { container, onSave, onCancel };
}

describe("parseJsonObject", () => {
  it("accepts objects and rejects arrays or invalid JSON", () => {
    expect(parseJsonObject('{"a":1}')).toEqual({
      ok: true,
      value: { a: 1 },
    });
    expect(parseJsonObject("[1]").ok).toBe(false);
    expect(parseJsonObject("{").ok).toBe(false);
    expect(prettyJson({ a: 1 })).toBe('{\n  "a": 1\n}');
  });
});

describe("JsonArtifactEditor", () => {
  it("saves parsed JSON and blocks invalid input", async () => {
    const { container, onSave } = await renderEditor();
    const textarea = container.querySelector("textarea");
    const save = [...container.querySelectorAll("button")].find(
      (button) => button.textContent === "Save",
    );
    if (!textarea || !save) throw new Error("missing controls");

    await act(async () => {
      save.click();
    });
    expect(onSave).toHaveBeenCalledWith({ value: '{"type":"object"}' });

    const setter = Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )?.set;
    await act(async () => {
      setter?.call(textarea, "[1]");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(save.disabled).toBe(true);
    expect(container.textContent).toContain(
      "JSON must be an object, not an array or value.",
    );
  });
});
