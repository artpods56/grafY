// @vitest-environment jsdom

import * as React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock("@xyflow/react", () => ({
  useNodeId: () => null,
  NodeToolbar: ({ children }: { children: React.ReactNode }) => children,
  Position: { Top: "top" },
  useViewport: () => ({ zoom: 1 }),
}));

import {
  ANNOTATION_COLOR_SWATCHES,
  ANNOTATION_NODE_TYPE,
  type AnnotationNodeData,
} from "../annotations";
import AnnotationNodeCard from "./AnnotationNode";

function rgb(color: string): string {
  const channels = [1, 3, 5].map((start) =>
    parseInt(color.slice(start, start + 2), 16),
  );
  return `rgb(${channels[0]}, ${channels[1]}, ${channels[2]})`;
}

describe("AnnotationNodeCard", () => {
  const roots: ReturnType<typeof createRoot>[] = [];

  afterEach(() => {
    React.act(() => {
      for (const root of roots.splice(0)) root.unmount();
    });
    document.body.replaceChildren();
  });

  it("ends text editing when the annotation is deselected", () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    roots.push(root);
    const props = {
      id: "annotation-1",
      type: ANNOTATION_NODE_TYPE,
      selected: true,
      data: {
        kind: "text" as const,
        layout: { width: 240, height: 120 },
        text: "Editable note",
        color: "#475569",
      },
    } as React.ComponentProps<typeof AnnotationNodeCard>;

    React.act(() => root.render(<AnnotationNodeCard {...props} />));
    React.act(() => {
      container
        .querySelector<HTMLElement>('[aria-label="Annotation text"]')
        ?.dispatchEvent(new MouseEvent("dblclick", { bubbles: true }));
    });
    expect(
      container.querySelector('[aria-label="Edit annotation markdown"]'),
    ).not.toBeNull();

    React.act(() => {
      root.render(<AnnotationNodeCard {...props} selected={false} />);
    });
    expect(
      container.querySelector('[aria-label="Edit annotation markdown"]'),
    ).toBeNull();

    React.act(() => {
      root.render(<AnnotationNodeCard {...props} selected />);
    });
    expect(
      container.querySelector('[aria-label="Annotation text"]'),
    ).not.toBeNull();
  });

  it("marks the annotation's own colour as the pressed swatch", () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    roots.push(root);
    const onColorChange = vi.fn();
    const data: AnnotationNodeData = {
      kind: "text",
      layout: { width: 240, height: 120 },
      text: "Note",
      color: "#475569",
      onColorChange,
    };
    const props = {
      id: "annotation-1",
      type: ANNOTATION_NODE_TYPE,
      selected: true,
      data,
    } as React.ComponentProps<typeof AnnotationNodeCard>;

    React.act(() => root.render(<AnnotationNodeCard {...props} />));
    React.act(() => {
      container
        .querySelector<HTMLElement>('[aria-label="Annotation color"]')
        ?.dispatchEvent(
          new MouseEvent("pointerdown", { bubbles: true, cancelable: true }),
        );
    });

    const swatches = [
      ...container.querySelectorAll<HTMLElement>(
        'button[aria-label^="Color "]',
      ),
    ];
    expect(
      swatches.map((swatch) => swatch.getAttribute("aria-pressed")),
    ).toEqual([
      "true",
      "false",
      "false",
      "false",
      "false",
      "false",
      "false",
      "false",
    ]);
    // Each swatch keeps its hex as its tooltip, and paints that colour on the
    // chip inside the button rather than on the button itself.
    expect(swatches.map((swatch) => swatch.getAttribute("title"))).toEqual([
      ...ANNOTATION_COLOR_SWATCHES,
    ]);
    expect(
      swatches.map((swatch) => {
        const chip = swatch.firstElementChild;
        return chip ? getComputedStyle(chip).backgroundColor : null;
      }),
    ).toEqual(ANNOTATION_COLOR_SWATCHES.map((hex) => rgb(hex)));

    const second = swatches[1];
    if (!second) throw new Error("the palette has a second swatch");
    React.act(() => {
      second.dispatchEvent(
        new MouseEvent("pointerdown", { bubbles: true, cancelable: true }),
      );
    });

    expect(onColorChange).toHaveBeenCalledWith("annotation-1", "#b45309");
  });
});
