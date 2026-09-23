// @vitest-environment jsdom

import * as React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const gridMocks = vi.hoisted(() => ({
  cellSize: 50,
}));

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
}));

vi.mock("@base-ui/react/popover", () => ({
  Popover: {
    Root: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    Trigger: ({
      children,
      ...props
    }: React.ButtonHTMLAttributes<HTMLButtonElement> & {
      children: React.ReactNode;
    }) => (
      <button type="button" {...props}>
        {children}
      </button>
    ),
    Portal: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    Positioner: ({ children }: { children: React.ReactNode }) => (
      <>{children}</>
    ),
    Popup: ({ children }: { children: React.ReactNode }) => (
      <div data-testid="edge-selector-menu">{children}</div>
    ),
  },
}));

vi.mock("../canvas-grid-settings", () => ({
  useOptionalCanvasGridSettings: () => ({
    settings: {
      enabled: true,
      showBackground: true,
      snapPosition: true,
      snapSize: true,
      snapWhileDragging: false,
      snapWhileResizing: true,
      allowWorkflowCornerResize: false,
      cellSize: gridMocks.cellSize,
    },
    bypassSnap: false,
  }),
}));

import { EdgeSelectorBlock } from "./EdgeSelectorBlock";

const roots: Root[] = [];
const containers: HTMLElement[] = [];

afterEach(() => {
  React.act(() => {
    for (const root of roots.splice(0)) root.unmount();
  });
  for (const container of containers.splice(0)) container.remove();
  gridMocks.cellSize = 50;
});

function renderBlock(cellSize: number) {
  gridMocks.cellSize = cellSize;
  const container = document.createElement("div");
  document.body.append(container);
  containers.push(container);
  const root = createRoot(container);
  roots.push(root);
  React.act(() => {
    root.render(
      <EdgeSelectorBlock
        anchor={{ x: 10, y: 20 }}
        label="items"
        bendAriaLabel="Bend connection items"
        bendHandlers={{}}
        editAriaLabel="Edit connection items"
        editTitle="Edit feed"
        removeAriaLabel="Remove connection items"
        onRemove={() => undefined}
      >
        <span>menu</span>
      </EdgeSelectorBlock>,
    );
  });
  return container.querySelector(
    "[data-testid='edge-selector-block']",
  ) as HTMLElement;
}

describe("EdgeSelectorBlock", () => {
  it("occupies 3×1 cells from the live grid cell size", () => {
    const block = renderBlock(50);
    expect(block.style.width).toBe("150px");
    expect(block.style.height).toBe("50px");
    expect(block.dataset.widthCells).toBe("3");
    expect(block.dataset.heightCells).toBe("1");
    expect(block.dataset.cellSize).toBe("50");
  });

  it("resizes with a non-default cell size", () => {
    const block = renderBlock(60);
    expect(block.style.width).toBe("180px");
    expect(block.style.height).toBe("60px");
    expect(block.dataset.cellSize).toBe("60");
  });

  it("exposes a full-footprint bend grab plus menu and remove controls", () => {
    const block = renderBlock(50);
    expect(
      block.querySelector('[aria-label="Bend connection items"]'),
    ).toBeTruthy();
    expect(
      block.querySelector('[aria-label="Edit connection items"]'),
    ).toBeTruthy();
    expect(
      block.querySelector('[aria-label="Remove connection items"]'),
    ).toBeTruthy();
  });

  it("spans a pill-tall join without a bend grab when docked", () => {
    gridMocks.cellSize = 50;
    const container = document.createElement("div");
    document.body.append(container);
    containers.push(container);
    const root = createRoot(container);
    roots.push(root);
    React.act(() => {
      root.render(
        <EdgeSelectorBlock
          anchor={{ x: 300, y: 80 }}
          label="text"
          docked
          width={150}
          height={24}
          bendAriaLabel="Bend connection text"
          bendHandlers={{}}
          editAriaLabel="Edit connection text"
          editTitle="Edit feed"
          removeAriaLabel="Remove connection text"
          onRemove={() => undefined}
        >
          <span>menu</span>
        </EdgeSelectorBlock>,
      );
    });
    const block = container.querySelector(
      "[data-testid='edge-selector-block']",
    ) as HTMLElement;
    expect(block.dataset.docked).toBe("true");
    expect(block.style.width).toBe("150px");
    expect(block.style.height).toBe("24px");
    expect(
      block.querySelector('[aria-label="Bend connection text"]'),
    ).toBeNull();
    expect(
      block.querySelector('[aria-label="Edit connection text"]'),
    ).toBeTruthy();
  });
});
