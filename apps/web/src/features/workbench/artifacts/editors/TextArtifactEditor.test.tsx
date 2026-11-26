// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  TextArtifactEditor,
  textCounts,
  textPayloadValue,
} from "./TextArtifactEditor";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const roots: Root[] = [];

afterEach(async () => {
  for (const root of roots.splice(0)) {
    await act(async () => root.unmount());
  }
  document.body.replaceChildren();
});

describe("text payload helpers", () => {
  it("reads the string value and counts characters and lines", () => {
    expect(textPayloadValue({ value: "Hi\nthere" })).toBe("Hi\nthere");
    expect(textPayloadValue({ value: 1 })).toBe("");
    expect(textCounts("Hi\nthere")).toEqual({ characters: 8, lines: 2 });
  });
});

describe("TextArtifactEditor", () => {
  it("saves { value } from the textarea", async () => {
    const onSave = vi.fn();
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    roots.push(root);
    await act(async () => {
      root.render(
        <TextArtifactEditor
          workspaceId="ws"
          artifactType="scalar.text"
          schemaVersion={1}
          initialPayload={{ value: "Draft" }}
          onSave={onSave}
          onCancel={() => {}}
        />,
      );
    });
    const textarea = container.querySelector("textarea");
    const save = [...container.querySelectorAll("button")].find(
      (button) => button.textContent === "Save",
    );
    if (!textarea || !save) throw new Error("missing controls");
    const setter = Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )?.set;
    await act(async () => {
      setter?.call(textarea, "Hello");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(container.textContent).toContain("5 characters");
    await act(async () => {
      save.click();
    });
    expect(onSave).toHaveBeenCalledWith({ value: "Hello" });
  });
});
