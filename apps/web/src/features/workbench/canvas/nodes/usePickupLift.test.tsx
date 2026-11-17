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
 * The lift's frame-by-frame remeasure is a trade. One call re-measures this node's
 * handles, walks the absolute position of every node, and notifies the whole store, and
 * it is the only way React Flow learns where a card lifted by a CSS transform has taken
 * its ports. So the sweep has to follow a travelling card, and has to stop when the card
 * has stopped travelling; either half can be bought by deleting the other, so both are
 * asserted here.
 *
 * The height series are the positions a real lift passed through, sampled per painted
 * frame on the workbench at zoom 1: a selection raises the card 4 px and eases out, and
 * a hold carries it to 10 px.
 */
const SELECT_RISE = [
  0, 0.4, 1.27, 2.28, 3.01, 3.52, 3.85, 4.03, 4.11, 4.12, 4.09, 4.05, 4.01,
];
const SELECT_REST = 4;
const RELEASE_FALL = [10, 8.6, 7.2, 6.0, 5.1, 4.5, 4.2, 4.08, 4.0, 4.0];

function settleTransition(element: HTMLElement) {
  act(() => {
    const settle = new Event("transitionend") as Event & {
      propertyName?: string;
    };
    settle.propertyName = "transform";
    element.dispatchEvent(settle);
  });
}

function Harness({
  selected,
  dragging,
  updateNodeInternals,
  onTier,
}: {
  selected: boolean;
  dragging: boolean;
  updateNodeInternals: (id: string) => void;
  onTier: (tier: PickupTier) => void;
}) {
  const { tier, liftRef, holdHandlers } = usePickupLift({
    id: "node-1",
    selected,
    dragging,
    updateNodeInternals,
  });
  onTier(tier);
  return (
    <div
      data-testid="lift"
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

  /** Where the card sits on screen. The lift moves it; jsdom would not. */
  function placeAt(top: number) {
    element.getBoundingClientRect = () =>
      ({
        top,
        bottom: top,
        height: 0,
        width: 300,
        left: 100,
        right: 400,
        x: 100,
        y: top,
        toJSON: () => ({}),
      }) as DOMRect;
  }

  /** One painted frame at each height the animation passed through. */
  function paintThrough(heights: number[]) {
    for (const top of heights) {
      placeAt(top);
      act(() => {
        vi.advanceTimersByTime(16);
      });
    }
  }

  function paintStill(frames: number, top: number) {
    paintThrough(Array.from({ length: frames }, () => top));
  }

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
    element = host.querySelector<HTMLElement>("[data-testid='lift']")!;
    placeAt(0);
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
    paintStill(6, 0);
    expect(calls()).toBe(0);
    expect(tiers).toEqual(["rest", "rest"]);
  });

  it("does not measure a node that mounts already selected", () => {
    mount({ selected: true });
    render({ selected: true });
    paintStill(6, SELECT_REST);
    expect(tiers.at(-1)).toBe("active");
    expect(calls()).toBe(0);
  });

  it("follows the card on the frames that carry it", () => {
    mount({ selected: false });
    render({ selected: true });
    expect(tiers.at(-1)).toBe("active");

    paintThrough(SELECT_RISE);
    // The rise carries the card 4 px in thirteen painted frames. Five of them move it
    // further than the tolerance; the rest are the easing creeping to a stop, and those
    // are the frames this gate exists to skip.
    expect(calls()).toBeGreaterThanOrEqual(4);
    expect(calls()).toBeLessThan(SELECT_RISE.length);
  });

  it("goes quiet once the lift has settled, rather than every frame the node is held", () => {
    mount({ selected: false });
    render({ selected: true });
    paintThrough(SELECT_RISE);
    settleTransition(element);

    const afterSettle = calls();
    paintStill(20, SELECT_REST);
    expect(calls()).toBe(afterSettle);
  });

  it("measures the resting geometry when the transition ends", () => {
    mount({ selected: false });
    render({ selected: true });
    paintThrough([0, 1, 2]);
    const before = calls();

    settleTransition(element);
    expect(calls()).toBe(before + 1);
  });

  it("measures the resting geometry when the fallback stops the sweep", () => {
    mount({ selected: false });
    render({ selected: true });
    paintThrough([0, 1, 2]);
    const before = calls();

    // No transitionend ever arrives: an interrupted style, a hidden tab.
    act(() => {
      vi.advanceTimersByTime(260);
    });
    expect(calls()).toBe(before + 1);
  });

  it("follows the fall when the hand lets go", () => {
    mount({ selected: false });
    render({ selected: true });
    paintThrough(SELECT_RISE);
    settleTransition(element);

    render({ selected: true, dragging: true });
    placeAt(10);
    const atDrop = calls();

    render({ selected: true, dragging: false });
    expect(tiers.at(-1)).toBe("active");
    paintThrough(RELEASE_FALL);
    expect(calls() - atDrop).toBeGreaterThanOrEqual(4);
  });

  it("snaps a real drag past the lift and measures exactly once", () => {
    mount({ selected: false });
    render({ selected: true });
    paintThrough(SELECT_RISE);
    settleTransition(element);
    const before = calls();

    render({ selected: true, dragging: true });
    expect(tiers.at(-1)).toBe("dragged");
    expect(calls()).toBe(before + 1);
    // Past the spring, not along it: the drag loop needs lifted bounds now.
    expect(element.style.transition).toBe("none");

    // While the hand carries the node, React Flow is told where it is by the drag
    // itself; the lift adds no per-frame measurement.
    paintThrough([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
    expect(calls()).toBe(before + 1);
  });

  it("measures once and follows nothing when motion is reduced", () => {
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: query === "(prefers-reduced-motion: reduce)",
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }));
    mount({ selected: false });
    render({ selected: true });
    expect(calls()).toBe(1);

    paintThrough(SELECT_RISE);
    expect(calls()).toBe(1);
  });
});
