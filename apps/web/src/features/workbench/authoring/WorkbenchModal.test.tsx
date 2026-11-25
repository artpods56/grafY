// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkbenchModal, type WorkbenchModalProps } from "./WorkbenchModal";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const mountedRoots = new Set<Root>();

afterEach(async () => {
  await act(async () => {
    for (const root of mountedRoots) root.unmount();
  });
  mountedRoots.clear();
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

/**
 * Mounts the modal the way a workbench consumer does: a controlled `open`
 * prop plus an `onOpenChange` that records every call.
 */
async function mountModal(
  props: Partial<WorkbenchModalProps> = {},
  initialOpen = true,
) {
  const openChanges: boolean[] = [];
  const { children, ...rest } = props;
  function Harness() {
    const [open, setOpen] = React.useState(initialOpen);
    return (
      <WorkbenchModal
        title="Edit system prompt"
        open={open}
        onOpenChange={(next) => {
          openChanges.push(next);
          setOpen(next);
        }}
        {...rest}
      >
        {children ?? <div>editor surface</div>}
      </WorkbenchModal>
    );
  }
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  mountedRoots.add(root);
  await act(async () => root.render(<Harness />));
  return { container, root, openChanges };
}

function popup(): HTMLElement | null {
  return document.querySelector<HTMLElement>('[role="dialog"]');
}

function buttonWithText(text: string): HTMLButtonElement {
  const button = [...document.querySelectorAll("button")].find(
    (candidate) => candidate.textContent === text,
  );
  if (!button) throw new Error(`expected a "${text}" button`);
  return button;
}

function closeButton(): HTMLButtonElement {
  const button = document.querySelector<HTMLButtonElement>(
    'button[aria-label="Close"]',
  );
  if (!button) throw new Error("expected the kit Close button");
  return button;
}

describe("WorkbenchModal", () => {
  it("renders title, description, children, headerActions, and footer when open", async () => {
    await mountModal({
      description: "Long prompts get more room here.",
      headerActions: <button type="button">Pop back</button>,
      footer: <span>3 unsaved edits</span>,
      children: <div>editor surface</div>,
    });

    const dialog = popup();
    expect(dialog).not.toBeNull();
    expect(dialog?.textContent).toContain("Edit system prompt");
    expect(dialog?.textContent).toContain("Long prompts get more room here.");
    expect(dialog?.textContent).toContain("editor surface");
    expect(dialog?.textContent).toContain("Pop back");
    expect(
      document.querySelector("[data-workbench-modal-footer]")?.textContent,
    ).toContain("3 unsaved edits");
  });

  it("renders nothing when closed", async () => {
    await mountModal({}, false);
    expect(popup()).toBeNull();
  });

  it("opens from a closed mount without reporting a close of its own", async () => {
    // The shell mounts closed and the consumer opens it, which is how a card
    // uses it. The phase the modal reached while closed must not be read back
    // as a dismissal the person never asked for.
    const openChanges: boolean[] = [];
    function Harness() {
      const [open, setOpen] = React.useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Expand the prompt
          </button>
          <WorkbenchModal
            title="Edit system prompt"
            open={open}
            onOpenChange={(next) => {
              openChanges.push(next);
              setOpen(next);
            }}
          >
            <div>editor surface</div>
          </WorkbenchModal>
        </>
      );
    }
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    mountedRoots.add(root);
    await act(async () => root.render(<Harness />));

    await act(async () => {
      container.querySelector<HTMLButtonElement>("button")!.click();
    });

    expect(popup()?.textContent).toContain("editor surface");
    expect(openChanges).toEqual([]);

    await act(async () => closeButton().click());
    expect(openChanges).toEqual([false]);
    expect(popup()).toBeNull();
  });

  it("defaults the DialogContent size to wide", async () => {
    await mountModal({});
    expect(popup()?.classList.contains("sizeWide")).toBe(true);
  });

  it("passes size through to DialogContent", async () => {
    await mountModal({ size: "viewport" });
    expect(popup()?.classList.contains("sizeViewport")).toBe(true);
  });

  it("keeps the canvas gesture classes on the popup", async () => {
    await mountModal({});
    const classes = popup()?.className.split(" ") ?? [];
    expect(classes).toContain("nodrag");
    expect(classes).toContain("nopan");
    expect(classes).toContain("nowheel");
  });

  it("uses the scroll body by default and the fill body on demand", async () => {
    await mountModal({ children: <div>scroll content</div> });
    const scrollBody = document.querySelector<HTMLElement>(
      '[data-body-layout="scroll"]',
    );
    expect(scrollBody).not.toBeNull();
    expect(scrollBody?.classList.contains("bodyFill")).toBe(false);

    await mountModal({
      bodyLayout: "fill",
      children: <div>fill content</div>,
    });
    const fillBody = document.querySelector<HTMLElement>(
      '[data-body-layout="fill"]',
    );
    expect(fillBody).not.toBeNull();
    expect(fillBody?.classList.contains("bodyFill")).toBe(true);
    expect(fillBody?.textContent).toContain("fill content");
  });

  it("closes immediately through onOpenChange when clean", async () => {
    const { openChanges } = await mountModal({});

    await act(async () => closeButton().click());

    expect(openChanges).toEqual([false]);
    expect(popup()).toBeNull();
    expect(document.querySelector("[data-workbench-modal-discard]")).toBeNull();
  });

  it("asks before closing when dirty, then keeps editing", async () => {
    const { openChanges } = await mountModal({ dirty: true });

    await act(async () => closeButton().click());

    // Still open, banner up, no close reported.
    expect(openChanges).toEqual([]);
    const banner = document.querySelector<HTMLElement>(
      "[data-workbench-modal-discard]",
    );
    expect(banner).not.toBeNull();
    expect(banner?.textContent).toContain("Unsaved changes");
    expect(banner?.textContent).toContain(
      "Closing now will discard your unsaved edits.",
    );
    expect(popup()).not.toBeNull();

    await act(async () => buttonWithText("Keep editing").click());

    expect(openChanges).toEqual([]);
    expect(document.querySelector("[data-workbench-modal-discard]")).toBeNull();
    expect(popup()).not.toBeNull();
  });

  it("confirms the discard: onDiscard fires, then onOpenChange(false)", async () => {
    const onDiscard = vi.fn();
    const { openChanges } = await mountModal({ dirty: true, onDiscard });

    await act(async () => closeButton().click());
    expect(
      document.querySelector("[data-workbench-modal-discard]"),
    ).not.toBeNull();

    await act(async () => buttonWithText("Discard").click());

    expect(onDiscard).toHaveBeenCalledOnce();
    expect(openChanges).toEqual([false]);
    expect(popup()).toBeNull();
  });

  it("honours custom discard copy", async () => {
    await mountModal({
      dirty: true,
      discardTitle: "Lose the TIFF crop?",
      discardBody: "The crop has not been applied yet.",
    });

    await act(async () => closeButton().click());

    const banner = document.querySelector<HTMLElement>(
      "[data-workbench-modal-discard]",
    );
    expect(banner?.textContent).toContain("Lose the TIFF crop?");
    expect(banner?.textContent).toContain("The crop has not been applied yet.");
  });
});
