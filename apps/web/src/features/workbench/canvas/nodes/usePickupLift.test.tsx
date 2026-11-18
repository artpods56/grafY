// @vitest-environment jsdom

import * as React from "react";
import { createRoot } from "react-dom/client";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
  type Mock,
} from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

import { usePickupLift, type PickupTier } from "./usePickupLift";

const { act } = React;

/**
 * Keeping React Flow's handle bounds current under a CSS lift is a trade, and both
 * halves of it are asserted here.
 *
 * One call to `updateNodeInternals` re-measures this node's handles, walks the
 * absolute position of every node, and notifies the whole store — 6.4 ms of main
 * thread on a 17-node graph, against a 0.3 ms idle frame — and it is the only way
 * React Flow learns where a card lifted by a transform has taken its ports. So the
 * card is looked at once per tier, and only when it has stopped travelling: no look
 * may happen on a frame the animation is simply crossing, and the resting geometry
 * must still be taken, by settle or by the fallback stop, so a gesture never leaves a
 * stale port behind for the next wire to snap to.
 */

function settleTransition(element: HTMLElement) {
  act(() => {
    const settle = new Event("transitionend") as Event & {
      propertyName?: string;
    };
    settle.propertyName = "transform";
    element.dispatchEvent(settle);
  });
}

/** Painted frames the lift spends easing between two tiers. */
function frames(count: number) {
  for (let frame = 0; frame < count; frame += 1) {
    act(() => {
      vi.advanceTimersByTime(16);
    });
  }
}

function holdFor(element: HTMLElement, ms: number) {
  act(() => {
    element.dispatchEvent(
      new MouseEvent("pointerdown", {
        bubbles: true,
        clientX: 200,
        clientY: 200,
      }),
    );
  });
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

interface HarnessProps {
  id?: string;
  selected: boolean;
  dragging?: boolean;
  updateNodeInternals: (id: string) => void;
  onTier: (tier: PickupTier) => void;
}

function Harness({
  id = "node-1",
  selected,
  dragging,
  updateNodeInternals,
  onTier,
}: HarnessProps) {
  const { tier, liftRef, holdHandlers } = usePickupLift({
    id,
    selected,
    dragging,
    updateNodeInternals,
  });
  onTier(tier);
  return (
    <div
      data-testid={`lift-${id}`}
      ref={liftRef}
      data-node-tier={tier}
      {...holdHandlers}
    />
  );
}

describe("usePickupLift", () => {
  let root: ReturnType<typeof createRoot> | null = null;
  let host: HTMLElement;
  let element: HTMLElement;
  let updateNodeInternals: Mock<(id: string) => void>;
  let tiers: PickupTier[];

  function mount(props: { selected: boolean; dragging?: boolean }) {
    const created = createRoot(host);
    root = created;
    act(() => {
      created.render(
        <Harness
          selected={props.selected}
          dragging={props.dragging ?? false}
          updateNodeInternals={updateNodeInternals}
          onTier={(tier) => tiers.push(tier)}
        />,
      );
    });
    element = host.querySelector<HTMLElement>("[data-testid='lift-node-1']")!;
  }

  function render(props: { selected: boolean; dragging?: boolean }) {
    const mounted = root;
    if (!mounted) throw new Error("mount the harness before re-rendering it");
    act(() => {
      mounted.render(
        <Harness
          selected={props.selected}
          dragging={props.dragging ?? false}
          updateNodeInternals={updateNodeInternals}
          onTier={(tier) => tiers.push(tier)}
        />,
      );
    });
  }

  const calls = () => updateNodeInternals.mock.calls.length;

  beforeEach(() => {
    vi.useFakeTimers({
      toFake: [
        "setTimeout",
        "clearTimeout",
        "requestAnimationFrame",
        "cancelAnimationFrame",
        "Date",
      ],
    });
    host = document.createElement("div");
    document.body.appendChild(host);
    updateNodeInternals = vi.fn<(id: string) => void>();
    tiers = [];
  });

  afterEach(() => {
    React.act(() => {
      root?.unmount();
      root = null;
    });
    host.remove();
    vi.useRealTimers();
  });

  it("never measures a node that has not been picked up", () => {
    mount({ selected: false });
    render({ selected: false });
    frames(6);
    expect(calls()).toBe(0);
    expect(tiers).toEqual(["rest", "rest"]);
  });

  it("does not measure a node that mounts already selected", () => {
    mount({ selected: true });
    render({ selected: true });
    frames(6);

    expect(tiers.at(-1)).toBe("active");
    expect(calls()).toBe(0);
  });

  it("looks nowhere while the lift travels", () => {
    mount({ selected: false });
    render({ selected: true });
    expect(tiers.at(-1)).toBe("active");

    // The rise carries a connected port 4 px across ~thirteen painted frames. The
    // easing spends most of them creeping, and none of them are worth a store-wide
    // re-measurement: the wires jump the rest of the way when the card lands.
    frames(13);
    expect(calls()).toBe(0);
  });

  it("measures the resting geometry when the transition ends", () => {
    mount({ selected: false });
    render({ selected: true });
    frames(3);
    expect(calls()).toBe(0);

    settleTransition(element);
    expect(calls()).toBe(1);
  });

  it("measures the resting geometry when the fallback stops the wait", () => {
    mount({ selected: false });
    render({ selected: true });
    frames(3);
    expect(calls()).toBe(0);

    // No transitionend ever arrives: an interrupted style, a hidden tab.
    act(() => {
      vi.advanceTimersByTime(260);
    });
    expect(calls()).toBe(1);
  });

  it("goes quiet once the lift has settled, rather than every frame the node is held", () => {
    mount({ selected: false });
    render({ selected: true });
    settleTransition(element);

    const afterSettle = calls();
    frames(20);
    expect(calls()).toBe(afterSettle);
  });

  it("takes one measurement per tier and none for the travel between them", () => {
    mount({ selected: false });
    render({ selected: true });
    settleTransition(element);
    expect(calls()).toBe(1); // rest → active

    render({ selected: true, dragging: true });
    expect(tiers.at(-1)).toBe("dragged");
    frames(10);
    // While the hand carries the node, React Flow is told where it is by the drag
    // itself; the lift adds no look of its own until this tier stops moving.
    expect(calls()).toBe(1);
    settleTransition(element);
    expect(calls()).toBe(2); // active → dragged

    render({ selected: true, dragging: false });
    expect(tiers.at(-1)).toBe("active");
    frames(10);
    expect(calls()).toBe(2);
    settleTransition(element);
    expect(calls()).toBe(3); // dragged → active, the fall measured at rest
  });

  it("does not force a layout to measure at drag start", () => {
    mount({ selected: false });
    render({ selected: true });
    settleTransition(element);

    render({ selected: true, dragging: true });
    // The old snap wrote `transition: "none"`, read `offsetWidth`, and measured inside
    // the pointer gesture. A drag is already the most expensive frame on the canvas.
    expect(element.style.transition).toBe("");
    expect(calls()).toBe(1);
  });

  it("does not track anything when motion is reduced", () => {
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: query === "(prefers-reduced-motion: reduce)",
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }));
    mount({ selected: false });
    render({ selected: true });
    // Nothing animates, so the resting geometry is already where it will stay.
    expect(calls()).toBe(1);

    frames(13);
    expect(calls()).toBe(1);
  });
});

describe("usePickupLift hold lift across cards", () => {
  let roots: ReturnType<typeof createRoot>[] = [];
  let host: HTMLElement;
  let updateNodeInternals: Mock<(id: string) => void>;
  let renders: Record<string, PickupTier[]>;

  function Card(props: { id: string; selected: boolean }) {
    const { tier, liftRef, holdHandlers } = usePickupLift({
      id: props.id,
      selected: props.selected,
      dragging: false,
      updateNodeInternals,
    });
    (renders[props.id] ??= []).push(tier);
    return (
      <div
        data-testid={`lift-${props.id}`}
        ref={liftRef}
        data-node-tier={tier}
        {...holdHandlers}
      />
    );
  }

  /** Two cards in separate roots: the held id is module state, so it is shared. */
  function mountCards(cards: { id: string; selected: boolean }[]) {
    for (const card of cards) {
      // One container per root: two roots on one container would wipe each other.
      const slot = document.createElement("div");
      host.appendChild(slot);
      const created = createRoot(slot);
      roots.push(created);
      act(() => {
        created.render(<Card id={card.id} selected={card.selected} />);
      });
    }
  }

  const card = (id: string) =>
    host.querySelector<HTMLElement>(`[data-testid='lift-${id}']`)!;

  /** The tiers this card has been rendered at, oldest first. */
  const tiersOf = (id: string): PickupTier[] => {
    const seen = renders[id];
    if (!seen) throw new Error(`no card rendered as ${id}`);
    return seen;
  };

  beforeEach(() => {
    vi.useFakeTimers({
      toFake: [
        "setTimeout",
        "clearTimeout",
        "requestAnimationFrame",
        "cancelAnimationFrame",
        "Date",
      ],
    });
    host = document.createElement("div");
    document.body.appendChild(host);
    updateNodeInternals = vi.fn<(id: string) => void>();
    renders = {};
  });

  afterEach(() => {
    React.act(() => {
      for (const created of roots) created.unmount();
      roots = [];
    });
    host.remove();
    vi.useRealTimers();
  });

  it("lifts every selected card from a hold on one of them", () => {
    mountCards([
      { id: "a", selected: true },
      { id: "b", selected: true },
    ]);
    expect(card("a").dataset.nodeTier).toBe("active");

    holdFor(card("a"), 150);
    expect(card("a").dataset.nodeTier).toBe("dragged");
    expect(card("b").dataset.nodeTier).toBe("dragged");
  });

  it("leaves a card outside the selection alone while another is held", () => {
    mountCards([
      { id: "a", selected: true },
      { id: "outside", selected: false },
    ]);
    const heldBefore = tiersOf("outside").length;

    holdFor(card("a"), 150);
    expect(card("a").dataset.nodeTier).toBe("dragged");
    // A hold cannot lift an unselected card, so its snapshot never changes and React
    // skips the render: notifying every mounted card used to repaint the canvas for a
    // gesture on one of them.
    expect(tiersOf("outside").length).toBe(heldBefore);
    expect(card("outside").dataset.nodeTier).toBe("rest");
  });

  it("lifts a card that joins the selection after the hold began", () => {
    mountCards([{ id: "held", selected: true }]);
    holdFor(card("held"), 150);

    const slot = document.createElement("div");
    host.appendChild(slot);
    const created = createRoot(slot);
    roots.push(created);
    act(() => {
      created.render(<Card id="joined" selected />);
    });
    expect(card("joined").dataset.nodeTier).toBe("dragged");
  });

  it("puts the group back down when the hand lets go", () => {
    mountCards([
      { id: "a", selected: true },
      { id: "b", selected: true },
    ]);
    holdFor(card("a"), 150);
    expect(card("b").dataset.nodeTier).toBe("dragged");

    act(() => {
      window.dispatchEvent(new Event("pointerup"));
    });
    expect(card("a").dataset.nodeTier).toBe("active");
    expect(card("b").dataset.nodeTier).toBe("active");
  });
});
