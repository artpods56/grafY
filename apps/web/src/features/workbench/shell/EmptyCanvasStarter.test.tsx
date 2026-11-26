// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EmptyCanvasStarter } from "./EmptyCanvasStarter";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const roots: Root[] = [];

afterEach(async () => {
  for (const root of roots.splice(0)) {
    await act(async () => root.unmount());
  }
  document.body.replaceChildren();
});

async function renderStarter(
  props: Partial<React.ComponentProps<typeof EmptyCanvasStarter>> = {},
) {
  const onFiles = vi.fn();
  const onSample = vi.fn();
  const onBrowseSteps = vi.fn();
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  roots.push(root);
  await act(async () => {
    root.render(
      <EmptyCanvasStarter
        status={null}
        onFiles={onFiles}
        onSample={onSample}
        onBrowseSteps={onBrowseSteps}
        {...props}
      />,
    );
  });
  return { container, onFiles, onSample, onBrowseSteps };
}

function buttonNamed(container: ParentNode, name: string): HTMLButtonElement {
  const match = [...container.querySelectorAll("button")].find((candidate) =>
    candidate.textContent?.includes(name),
  );
  if (!(match instanceof HTMLButtonElement)) {
    throw new Error(`Button not found: ${name}`);
  }
  return match;
}

describe("EmptyCanvasStarter", () => {
  it("offers a drop, the sample page, and the step list", async () => {
    const { container } = await renderStarter();
    expect(container.textContent).toContain(
      "Drop a scanned page, PDF, or spreadsheet here",
    );
    expect(container.textContent).toContain("Try a sample historical page");
    expect(container.textContent).toContain("Browse steps");
    expect(container.textContent).not.toContain("Create artifact");
  });

  it("offers creating an artifact when that action is provided", async () => {
    const onCreateArtifact = vi.fn();
    const { container } = await renderStarter({ onCreateArtifact });
    expect(container.textContent).toContain("Create artifact");
    await act(async () => {
      buttonNamed(container, "Create artifact").click();
    });
    expect(onCreateArtifact).toHaveBeenCalledTimes(1);
  });

  it("sends a chosen file, the sample, and a request to browse steps", async () => {
    const { container, onFiles, onSample, onBrowseSteps } =
      await renderStarter();
    const file = new File(["scan"], "page.png", { type: "image/png" });
    const input =
      container.querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error("File input not found");
    Object.defineProperty(input, "files", {
      configurable: true,
      value: {
        0: file,
        length: 1,
        item: (index: number) => (index === 0 ? file : null),
      },
    });

    await act(async () => {
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(onFiles).toHaveBeenCalledWith([file]);

    await act(async () => {
      buttonNamed(container, "Try a sample historical page").click();
    });
    expect(onSample).toHaveBeenCalledOnce();

    await act(async () => {
      buttonNamed(container, "Browse steps").click();
    });
    expect(onBrowseSteps).toHaveBeenCalledOnce();
  });

  it("keeps Browse steps available while a sample is on its way", async () => {
    const { container, onFiles, onSample, onBrowseSteps } = await renderStarter(
      {
        samplePending: true,
      },
    );
    const drop = buttonNamed(
      container,
      "Drop a scanned page, PDF, or spreadsheet here",
    );
    const sample = buttonNamed(container, "Try a sample historical page");
    const browse = buttonNamed(container, "Browse steps");

    expect(drop.disabled).toBe(true);
    expect(sample.disabled).toBe(true);
    expect(browse.disabled).toBe(false);

    await act(async () => {
      sample.click();
      browse.click();
    });
    expect(onSample).not.toHaveBeenCalled();
    expect(onBrowseSteps).toHaveBeenCalledOnce();
    expect(onFiles).not.toHaveBeenCalled();
  });
});
