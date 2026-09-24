// @vitest-environment jsdom

import * as React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
}));

vi.mock("@xyflow/react", () => ({
  NodeToolbar: ({ children }: { children: React.ReactNode }) => children,
  Position: { Top: "top" },
  useViewport: () => ({ zoom: 1 }),
}));

import { ANNOTATION_NODE_TYPE } from "../annotations";
import AnnotationNodeCard from "./AnnotationNode";

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
});
