// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_CELL_CLEANUP_PARAMS } from "../cell-canvas/cell-graph-cleanup";
import { CanvasCleanupPopover } from "./CanvasCleanupPopover";

(
  globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement | null = null;
let root: ReturnType<typeof createRoot> | null = null;

function mount(element: React.ReactElement) {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => {
    root?.render(element);
  });
  return host;
}

afterEach(() => {
  act(() => {
    root?.unmount();
  });
  root = null;
  host?.remove();
  host = null;
});

describe("CanvasCleanupPopover", () => {
  it("renders spacing sliders, sizing controls, and flow toggles, and applies with scope", () => {
    const onChange = vi.fn();
    const onReset = vi.fn();
    const onApply = vi.fn();
    const onClose = vi.fn();

    const container = mount(
      <CanvasCleanupPopover
        params={DEFAULT_CELL_CLEANUP_PARAMS}
        onChange={onChange}
        onReset={onReset}
        onApply={onApply}
        onClose={onClose}
        selectedCount={0}
        canApply={true}
        undoCount={0}
      />,
    );

    expect(container.textContent).toContain("Clean up canvas");
    expect(container.textContent).toContain("Column gap");
    expect(container.textContent).toContain("Branch gap");
    expect(container.textContent).toContain("Stack gap");
    expect(container.textContent).toContain("Experiment gap");
    expect(container.textContent).toContain("Resize cards to canonical sizes");
    expect(container.textContent).toContain("Tuck single-use providers");
    // Scope picker stays hidden until 2+ cards are selected
    expect(container.textContent).not.toContain("Whole canvas");

    const resetButton = container.querySelector<HTMLButtonElement>(
      'button[aria-label="Reset cleanup defaults"]',
    );
    expect(resetButton?.disabled).toBe(true);

    const applyButton = Array.from(container.querySelectorAll("button")).find(
      (btn) => btn.textContent?.includes("Clean up canvas"),
    );
    expect(applyButton).toBeTruthy();
    act(() => {
      applyButton?.click();
    });
    expect(onApply).toHaveBeenCalledWith("all");
  });

  it("enables reset when params differ, shows selection scope and single undo when available", () => {
    const onChange = vi.fn();
    const onReset = vi.fn();
    const onApply = vi.fn();
    const onUndo = vi.fn();
    const onClose = vi.fn();

    const container = mount(
      <CanvasCleanupPopover
        params={{
          ...DEFAULT_CELL_CLEANUP_PARAMS,
          columnGapCells: 6,
          cardSize: "compact",
        }}
        onChange={onChange}
        onReset={onReset}
        onApply={onApply}
        onUndo={onUndo}
        onClose={onClose}
        selectedCount={4}
        canApply={true}
        undoCount={1}
      />,
    );

    expect(container.textContent).toContain("Whole canvas");
    expect(container.textContent).toContain("Selection (4)");

    const resetButton = container.querySelector<HTMLButtonElement>(
      'button[aria-label="Reset cleanup defaults"]',
    );
    expect(resetButton?.disabled).toBe(false);
    act(() => {
      resetButton?.click();
    });
    expect(onReset).toHaveBeenCalledTimes(1);

    const undoButton = Array.from(container.querySelectorAll("button")).find(
      (btn) => btn.textContent?.includes("Undo"),
    );
    expect(undoButton).toBeTruthy();
    act(() => {
      undoButton?.click();
    });
    expect(onUndo).toHaveBeenCalledTimes(1);

    const applyButton = Array.from(container.querySelectorAll("button")).find(
      (btn) => btn.textContent?.includes("Tidy 4 selected"),
    );
    expect(applyButton).toBeTruthy();
    act(() => {
      applyButton?.click();
    });
    expect(onApply).toHaveBeenCalledWith("selected");
  });

  it("shows both step undo and restore initial after multiple cleanups", () => {
    const onUndo = vi.fn();
    const onRevertInitial = vi.fn();

    const container = mount(
      <CanvasCleanupPopover
        params={DEFAULT_CELL_CLEANUP_PARAMS}
        onChange={vi.fn()}
        onReset={vi.fn()}
        onApply={vi.fn()}
        onUndo={onUndo}
        onRevertInitial={onRevertInitial}
        onClose={vi.fn()}
        selectedCount={0}
        canApply={true}
        undoCount={2}
      />,
    );

    const stepButton = Array.from(container.querySelectorAll("button")).find(
      (btn) => btn.textContent?.includes("Undo step"),
    );
    const initialButton = Array.from(container.querySelectorAll("button")).find(
      (btn) => btn.textContent?.includes("Restore initial"),
    );
    expect(stepButton).toBeTruthy();
    expect(initialButton).toBeTruthy();

    act(() => {
      stepButton?.click();
      initialButton?.click();
    });
    expect(onUndo).toHaveBeenCalledTimes(1);
    expect(onRevertInitial).toHaveBeenCalledTimes(1);
  });
});
