// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles extends Record<string, object>>(styles: Styles) => styles,
  defineVars: <Variables,>(variables: Variables) => variables,
  props: () => ({ className: "" }),
}));
vi.mock("../canvas/use-artifact-type-catalog", () => ({
  useArtifactTypeCatalog: () => [],
}));

import type { ArtifactDropPayload } from "../model/artifact-drop";
import {
  ArtifactFolderDropDialog,
  type PendingFolderDrop,
} from "./ArtifactFolderDropDialog";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const mountedRoots = new Set<ReturnType<typeof createRoot>>();

afterEach(async () => {
  await act(async () => {
    for (const root of mountedRoots) root.unmount();
  });
  mountedRoots.clear();
  document.body.replaceChildren();
});

function ref(id: string, artifactType: string) {
  return {
    artifact_id: id,
    artifact_type: artifactType,
    schema_version: 1,
    content_hash: null,
  };
}

const csvSequence: ArtifactDropPayload = {
  shape: "many",
  value: {
    artifact_type: "file.csv",
    schema_version: 1,
    item_refs: [ref("a", "file.csv"), ref("b", "file.csv")],
    ordered: true,
    index_key: "order_index",
    sequence_id: "seq",
  },
};
const lonePng: ArtifactDropPayload = {
  shape: "one",
  value: ref("p", "file.png"),
};

async function open(pending: PendingFolderDrop) {
  const handlers = {
    onPlaceAll: vi.fn(),
    onPlaceGroup: vi.fn(),
    onClose: vi.fn(),
  };
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  mountedRoots.add(root);
  await act(async () => {
    root.render(<ArtifactFolderDropDialog pending={pending} {...handlers} />);
  });
  return handlers;
}

function button(label: RegExp | string): HTMLButtonElement {
  const found = Array.from(document.body.querySelectorAll("button")).find(
    (candidate) =>
      typeof label === "string"
        ? candidate.textContent?.includes(label) ||
          candidate.getAttribute("aria-label") === label
        : label.test(candidate.textContent ?? "") ||
          label.test(candidate.getAttribute("aria-label") ?? ""),
  );
  if (!found) throw new Error(`no button for ${String(label)}`);
  return found;
}

describe("ArtifactFolderDropDialog", () => {
  it("offers every sequence, one group, or cancel on empty canvas", async () => {
    const handlers = await open({
      folderName: "Field work",
      groups: [csvSequence, lonePng],
      canPlaceAll: true,
    });

    expect(document.body.textContent).toContain(
      "Field work holds 2 kinds of artifact",
    );
    expect(document.body.textContent).toContain("2 artifacts");
    expect(document.body.textContent).toContain("1 artifact");

    await act(async () => button("Create 2 sequences").click());
    expect(handlers.onPlaceAll).toHaveBeenCalledTimes(1);

    await act(async () => button("Place Sequence<file.csv@1>").click());
    expect(handlers.onPlaceGroup).toHaveBeenCalledWith(csvSequence);

    await act(async () => button("Cancel").click());
    expect(handlers.onClose).toHaveBeenCalledTimes(1);
  });

  it("only offers one group where the drop takes a single value", async () => {
    await open({
      folderName: "Field work",
      groups: [csvSequence, lonePng],
      canPlaceAll: false,
    });

    expect(document.body.textContent).not.toContain("Create 2 sequences");
    expect(document.body.textContent).toContain("Choose which group to place");
  });
});
