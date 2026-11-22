// @vitest-environment node

import { describe, expect, it } from "vitest";

import {
  runEffectReducer,
  runEffectSequence,
} from "@/lib/state/effect-reducer";

import type { ArtifactStackItem } from "../cell-contracts";
import type { OpenSequenceSpreadLayout } from "../cell-artifact-stacking";
import { CELL_SIZE, type CellCardModel, type CellCoord } from "../cell-model";
import {
  createInitialSequenceSpreadState,
  displayedWindowStart,
  reorderDropIndex,
  sequenceSpreadReducer,
  visualSlotForSibling,
  type SequenceSpreadAction,
  type SequenceSpreadEffect,
  type SequenceSpreadState,
  type SpreadHitScene,
} from "./sequence-spread-reducer";

const CARD_WIDTH = 10 * CELL_SIZE;

const CARD: CellCardModel = {
  id: "pages",
  title: "PNG image",
  subtitle: "",
  kind: "artifact",
  col: 0,
  row: 0,
  widthCells: 10,
  heightCells: 8,
  ports: [],
};

function items(count: number): ArtifactStackItem[] {
  return Array.from({ length: count }, (_, index) => ({
    artifactId: `a${index}`,
    label: `page-${index + 1}.png`,
  }));
}

function layout(
  visible: number,
  itemCount: number,
  bounds?: { min?: number; max?: number },
): OpenSequenceSpreadLayout {
  return {
    canExpand: true,
    windowed: visible < itemCount,
    startCol: 0,
    row: 0,
    totalCols: visible * 10,
    heightCells: 8,
    visibleCount: visible,
    minVisibleCount: bounds?.min ?? 1,
    maxVisibleCount: bounds?.max ?? Math.max(visible, itemCount),
  };
}

function clock(
  nowMs: number,
  animateMotion = true,
  windowed = true,
): {
  nowMs: number;
  animateMotion: boolean;
  cardWidth: number;
  windowed: boolean;
} {
  return { nowMs, animateMotion, cardWidth: CARD_WIDTH, windowed };
}

function scene(patch: Partial<SpreadHitScene> = {}): SpreadHitScene {
  return {
    originX: 0,
    originY: 0,
    frameWidth: 4 * CARD_WIDTH,
    cardWidth: CARD_WIDTH,
    cardHeight: 8 * CELL_SIZE,
    windowed: true,
    layoutStartCol: 0,
    layoutRow: 0,
    layoutTotalCols: 40,
    card: CARD,
    foregroundCards: [CARD],
    canExtract: true,
    ...patch,
  };
}

function boot(
  count: number,
  visible: number,
  animateMotion: boolean,
  nowMs = 1000,
): { state: SequenceSpreadState; effects: readonly SequenceSpreadEffect[] } {
  const list = items(count);
  const open = layout(visible, count);
  const initial = createInitialSequenceSpreadState({
    items: list,
    layout: open,
    animateMotion,
  });
  return runEffectReducer(sequenceSpreadReducer, initial, {
    kind: "mounted",
    ...clock(nowMs, animateMotion, open.windowed),
  });
}

function act(
  state: SequenceSpreadState,
  action: SequenceSpreadAction,
): { state: SequenceSpreadState; effects: readonly SequenceSpreadEffect[] } {
  return runEffectReducer(sequenceSpreadReducer, state, action);
}

function kinds(effects: readonly SequenceSpreadEffect[]): string[] {
  return effects.map((effect) => effect.kind);
}

function phaseKind(
  state: SequenceSpreadState,
): SequenceSpreadState["phase"]["kind"] {
  return state.phase.kind;
}

function settleX(
  state: SequenceSpreadState,
  key: string,
): { x: number; vx: number; active: boolean } | undefined {
  if (state.phase.kind === "movingSpread") return undefined;
  const settle = state.phase.motionSettles.get(key);
  if (!settle) return undefined;
  return { x: settle.current.x, vx: settle.velocity.x, active: settle.active };
}

describe("mount expand", () => {
  it("fans slots out from x = 0 and settles back to idle", () => {
    const initial = createInitialSequenceSpreadState({
      items: items(6),
      layout: layout(4, 6),
      animateMotion: true,
    });
    expect(initial.phase.kind).toBe("idle");
    if (initial.phase.kind !== "idle") return;
    expect(initial.phase.motionSettles.get("a1:1")?.current.x).toBe(0);
    expect(initial.phase.motionSettles.get("a2:2")?.current.x).toBe(0);
    expect(initial.phase.motionSettles.has("a0:0")).toBe(false);

    const mounted = act(initial, { kind: "mounted", ...clock(1000) });
    expect(kinds(mounted.effects)).toContain("scheduleMotionFrame");
    expect(settleX(mounted.state, "a1:1")).toMatchObject({
      x: 0,
      active: true,
    });
    expect(
      mounted.state.phase.kind === "idle" &&
        mounted.state.phase.motionSettles.get("a1:1")?.to.x,
    ).toBe(CARD_WIDTH);

    const landed = act(mounted.state, { kind: "motionTick", nowMs: 4000 });
    expect(phaseKind(landed.state)).toBe("idle");
    if (landed.state.phase.kind !== "idle") return;
    expect(landed.state.phase.motionSettles.size).toBe(0);
    expect(kinds(landed.effects)).not.toContain("scheduleMotionFrame");
  });

  it("skips the fan when motion is reduced", () => {
    const mounted = boot(6, 4, false);
    expect(kinds(mounted.effects)).not.toContain("scheduleMotionFrame");
    if (mounted.state.phase.kind !== "idle") return;
    expect(mounted.state.phase.motionSettles.size).toBe(0);
    const stepped = act(mounted.state, {
      kind: "step",
      by: 1,
      ...clock(1000, false),
    });
    expect(stepped.state.windowStart).toBe(1);
    expect(phaseKind(stepped.state)).toBe("idle");
    expect(kinds(stepped.effects)).toEqual(["notifyWindowStartChange"]);
  });
});

describe("stepping", () => {
  it("steps forward and back, pages, and clamps", () => {
    const mounted = boot(6, 4, true);
    const rested = act(mounted.state, {
      kind: "motionTick",
      nowMs: 4000,
    }).state;
    const forward = act(rested, { kind: "step", by: 1, ...clock(4000) });
    expect(forward.state.windowStart).toBe(1);
    expect(phaseKind(forward.state)).toBe("stepping");
    if (forward.state.phase.kind !== "stepping") return;
    expect(forward.state.phase.underCard?.side).toBe("left");
    expect(forward.state.phase.underCard?.index).toBe(0);
    expect(kinds(forward.effects)).toEqual([
      "notifyWindowStartChange",
      "scheduleMotionFrame",
    ]);

    const back = act(
      act(forward.state, { kind: "motionTick", nowMs: 8000 }).state,
      {
        kind: "step",
        by: -1,
        ...clock(8000),
      },
    );
    expect(back.state.windowStart).toBe(0);
    if (back.state.phase.kind !== "stepping") return;
    expect(back.state.phase.underCard?.side).toBe("right");

    const paged = act(rested, { kind: "step", by: 3, ...clock(4000) });
    expect(paged.state.windowStart).toBe(2);
    if (paged.state.phase.kind !== "stepping") return;
    expect(
      paged.state.phase.stepTucks.map((tuck) => tuck.item.artifactId),
    ).toEqual(["a1"]);
    const clamped = act(paged.state, {
      kind: "step",
      by: 10,
      ...clock(4000, true),
    });
    expect(
      displayedWindowStart(
        clamped.state.windowStart,
        true,
        clamped.state.items.length,
        clamped.state.visibleCount,
      ),
    ).toBe(2);
  });

  it("accumulates wheel pixels and clamps at the ends", () => {
    const rested = act(boot(6, 4, false).state, {
      kind: "motionTick",
      nowMs: 1000,
    }).state;
    const wheeled = act(rested, {
      kind: "wheel",
      deltaX: 100,
      ...clock(1000, false),
    });
    expect(wheeled.state.windowStart).toBe(2);
    expect(wheeled.state.wheelAccumPx).toBe(20);
    const more = act(wheeled.state, {
      kind: "wheel",
      deltaX: 30,
      ...clock(1000, false),
    });
    expect(more.state.windowStart).toBe(2);
    expect(more.state.wheelAccumPx).toBe(10);
    const backward = act(more.state, {
      kind: "wheel",
      deltaX: -90,
      ...clock(1000, false),
    });
    expect(backward.state.windowStart).toBe(0);
  });

  it("keeps live spring position and velocity when a step reverses mid-flight", () => {
    const rested = act(boot(6, 4, true).state, {
      kind: "motionTick",
      nowMs: 4000,
    }).state;
    const forward = act(rested, { kind: "step", by: 1, ...clock(4000) }).state;
    const mid = act(forward, { kind: "motionTick", nowMs: 4050 }).state;
    const prior = settleX(mid, "a2:2");
    expect(prior?.active).toBe(true);
    const reversed = act(mid, { kind: "step", by: -1, ...clock(4050) }).state;
    if (reversed.phase.kind === "movingSpread") return;
    const next = reversed.phase.motionSettles.get("a2:2");
    expect(next).toBeDefined();
    expect(next?.origin.x).toBeCloseTo(prior?.x ?? 0);
    expect(next?.originVelocity.x).toBeCloseTo(prior?.vx ?? 0);
    expect(next?.to.x).toBe(2 * CARD_WIDTH);
    expect(reversed.windowStart).toBe(0);
  });
});

describe("resize", () => {
  function resizeDown(state: SequenceSpreadState, startX: number) {
    return act(state, {
      kind: "resizePointerDown",
      pointerId: 3,
      button: 0,
      startX,
    });
  }

  function resizeMove(
    state: SequenceSpreadState,
    worldX: number,
    nowMs: number,
    bounds: { min: number; max: number },
  ) {
    return act(state, {
      kind: "resizePointerMove",
      pointerId: 3,
      worldX,
      nowMs,
      animateMotion: true,
      cardWidth: CARD_WIDTH,
      minVisibleCount: bounds.min,
      maxVisibleCount: bounds.max,
    });
  }

  it("retargets tucks across a fast yank and keeps the glide after pointer up", () => {
    const open = layout(6, 6, { min: 1, max: 6 });
    let state = createInitialSequenceSpreadState({
      items: items(6),
      layout: open,
      animateMotion: true,
    });
    state = act(state, {
      kind: "mounted",
      ...clock(1000, true, false),
    }).state;
    state = act(state, { kind: "motionTick", nowMs: 4000 }).state;

    state = resizeDown(state, 0).state;
    expect(phaseKind(state)).toBe("resizing");

    const to5 = resizeMove(state, -CARD_WIDTH, 4000, { min: 1, max: 6 });
    expect(to5.effects).toContainEqual({
      kind: "notifyPreferredVisibleCountChange",
      count: 5,
    });
    expect(to5.state.visibleCount).toBe(5);
    if (to5.state.phase.kind !== "resizing") return;
    expect(
      to5.state.phase.resizeTucks.map((tuck) => tuck.item.artifactId),
    ).toEqual(["a5"]);
    expect(to5.state.phase.resizeBackSync?.driverKey).toBe("resize-tuck:a5:5");

    state = act(to5.state, { kind: "motionTick", nowMs: 4024 }).state;
    const to4 = resizeMove(state, -2 * CARD_WIDTH, 4024, { min: 1, max: 6 });
    state = act(to4.state, { kind: "motionTick", nowMs: 4048 }).state;
    const to3 = resizeMove(state, -3 * CARD_WIDTH, 4048, { min: 1, max: 6 });
    if (to3.state.phase.kind !== "resizing") return;
    expect(
      to3.state.phase.resizeTucks.map((tuck) => tuck.item.artifactId),
    ).toEqual(["a5", "a4", "a3"]);
    expect(to3.state.visibleCount).toBe(3);

    state = act(to3.state, { kind: "motionTick", nowMs: 4200 }).state;
    const liveA3 =
      state.phase.kind === "resizing"
        ? state.phase.motionSettles.get("resize-tuck:a3:3")
        : undefined;
    expect(liveA3?.active).toBe(true);

    const widened = resizeMove(state, -2 * CARD_WIDTH, 4200, {
      min: 1,
      max: 6,
    });
    if (widened.state.phase.kind !== "resizing") return;
    expect(
      widened.state.phase.resizeTucks.some(
        (tuck) => tuck.item.artifactId === "a3",
      ),
    ).toBe(false);
    const reopened = widened.state.phase.motionSettles.get("a3:3");
    expect(reopened?.current.x).toBeCloseTo(liveA3?.current.x ?? -1);
    expect(reopened?.originVelocity.x).toBeCloseTo(liveA3?.velocity.x ?? 0);
    expect(widened.state.phase.resizeBackSync?.driverKey).toBe("a3:3");

    const released = act(widened.state, {
      kind: "resizePointerEnd",
      pointerId: 3,
    });
    expect(released.state.phase.kind).toBe("resizing");
    if (released.state.phase.kind !== "resizing") return;
    expect(released.state.phase.pointer).toBeNull();
    expect(released.state.phase.motionSettles.get("a3:3")?.active).toBe(true);

    const done = act(released.state, { kind: "motionTick", nowMs: 9000 });
    expect(phaseKind(done.state)).toBe("idle");
  });

  it("does not glide when motion is reduced", () => {
    let state = boot(20, 6, false).state;
    state = act(state, {
      kind: "resizePointerDown",
      pointerId: 3,
      button: 0,
      startX: 0,
    }).state;
    const moved = act(state, {
      kind: "resizePointerMove",
      pointerId: 3,
      worldX: -2 * CARD_WIDTH - 10,
      nowMs: 1000,
      animateMotion: false,
      cardWidth: CARD_WIDTH,
      minVisibleCount: 1,
      maxVisibleCount: 12,
    });
    expect(moved.state.visibleCount).toBe(6);
    expect(moved.effects).toContainEqual({
      kind: "notifyPreferredVisibleCountChange",
      count: 4,
    });
    if (moved.state.phase.kind !== "resizing") return;
    expect(moved.state.phase.resizeTucks).toEqual([]);
  });
});

describe("rewind then fold", () => {
  function restedAt(startSteps: number): SequenceSpreadState {
    let state = act(boot(5, 3, true).state, {
      kind: "motionTick",
      nowMs: 3000,
    }).state;
    for (let step = 0; step < startSteps; step += 1) {
      state = act(state, {
        kind: "step",
        by: 1,
        ...clock(4000 + step * 2000),
      }).state;
      state = act(state, {
        kind: "motionTick",
        nowMs: 5000 + step * 2000,
      }).state;
    }
    return state;
  }

  it("rewinds, folds, then closes", () => {
    const open = restedAt(2);
    expect(open.windowStart).toBe(2);
    const closing = act(open, { kind: "requestClose", ...clock(9000) });
    expect(phaseKind(closing.state)).toBe("rewinding");
    expect(closing.state.windowStart).toBe(0);
    expect(kinds(closing.effects)).toContain("scheduleMotionFrame");
    expect(kinds(closing.effects)).not.toContain("notifyClose");
    if (closing.state.phase.kind !== "rewinding") return;
    expect(
      closing.state.phase.stepTucks.map((tuck) => tuck.item.artifactId),
    ).toEqual(["a3"]);
    expect(closing.state.phase.underCard?.index).toBe(4);

    const folded = act(closing.state, { kind: "motionTick", nowMs: 12000 });
    expect(phaseKind(folded.state)).toBe("folding");
    expect(kinds(folded.effects)).toContain("scheduleMotionFrame");
    expect(kinds(folded.effects)).not.toContain("notifyClose");
    if (folded.state.phase.kind !== "folding") return;
    expect(folded.state.phase.foldBackSync?.targetX).toBe(0);
    expect(folded.state.phase.foldBackSync).not.toBeNull();

    const closed = act(folded.state, { kind: "motionTick", nowMs: 16000 });
    expect(kinds(closed.effects)).toContain("notifyClose");
    expect(phaseKind(closed.state)).toBe("idle");
  });

  it("closes immediately when motion is reduced, and ignores a second request while rewinding", () => {
    const open = act(boot(5, 3, false).state, {
      kind: "step",
      by: 2,
      ...clock(1000, false),
    }).state;
    const first = act(open, { kind: "requestClose", ...clock(1000, false) });
    expect(kinds(first.effects)).toEqual(["notifyClose"]);
    expect(phaseKind(first.state)).toBe("idle");
    // Reduced motion stays idle, so a second request still notifies. The parent
    // unmounts the spread; Escape and the Stack button can both close it.
    const second = act(first.state, {
      kind: "requestClose",
      ...clock(1000, false),
    });
    expect(kinds(second.effects)).toEqual(["notifyClose"]);
    expect(second.state).toBe(first.state);

    const rewinding = act(restedAt(2), {
      kind: "requestClose",
      ...clock(9000),
    });
    const again = act(rewinding.state, {
      kind: "requestClose",
      ...clock(9100),
    });
    expect(again.effects).toEqual([]);
    expect(again.state).toBe(rewinding.state);
  });

  it("blocks step, drag, resize, move, and wheel while closing", () => {
    const closing = act(restedAt(2), {
      kind: "requestClose",
      ...clock(9000),
    }).state;
    expect(phaseKind(closing)).toBe("rewinding");
    const blocked = runEffectSequence(sequenceSpreadReducer, closing, [
      { kind: "step", by: 1, ...clock(9100) },
      {
        kind: "wheel",
        deltaX: 80,
        ...clock(9100),
      },
      {
        kind: "itemPointerDown",
        pointerId: 1,
        button: 0,
        index: 1,
        slot: 1,
        clientX: 0,
        clientY: 0,
        world: { x: 0, y: 0 },
        editable: true,
        originX: 0,
        originY: 0,
        cardWidth: CARD_WIDTH,
      },
      {
        kind: "movePointerDown",
        pointerId: 2,
        button: 0,
        clientX: 0,
        clientY: 0,
        world: { x: 0, y: 0 },
      },
      {
        kind: "resizePointerDown",
        pointerId: 3,
        button: 0,
        startX: 0,
      },
    ]);
    expect(blocked.effects).toEqual([]);
    expect(blocked.state).toBe(closing);
  });
});

describe("item drag", () => {
  function down(
    state: SequenceSpreadState,
    index: number,
    slot: number,
    client: CellCoord,
  ) {
    return act(state, {
      kind: "itemPointerDown",
      pointerId: 7,
      button: 0,
      index,
      slot,
      clientX: client.col,
      clientY: client.row,
      world: { x: client.col, y: client.row },
      editable: true,
      originX: 0,
      originY: 0,
      cardWidth: CARD_WIDTH,
    });
  }

  it("activates past the threshold, displaces siblings, and reorders on drop", () => {
    const state = boot(3, 3, false).state;
    const armed = down(state, 0, 0, { col: 100, row: 80 });
    expect(phaseKind(armed.state)).toBe("draggingItem");
    const nudge = act(armed.state, {
      kind: "itemPointerMove",
      pointerId: 7,
      clientX: 102,
      clientY: 80,
      world: { x: 102, y: 80 },
      scene: scene({
        windowed: false,
        frameWidth: 3 * CARD_WIDTH,
        layoutTotalCols: 30,
      }),
      ...clock(1000, false, false),
    });
    expect(nudge.state).toBe(armed.state);

    const dragging = act(armed.state, {
      kind: "itemPointerMove",
      pointerId: 7,
      clientX: 100 + 2 * CARD_WIDTH,
      clientY: 80,
      world: { x: 100 + 2 * CARD_WIDTH, y: 80 },
      scene: scene({
        windowed: false,
        frameWidth: 3 * CARD_WIDTH,
        layoutTotalCols: 30,
      }),
      ...clock(1000, false, false),
    });
    if (dragging.state.phase.kind !== "draggingItem") return;
    expect(dragging.state.phase.drag.active).toBe(true);
    expect(dragging.state.phase.drag.targetSlot).toBe(2);
    expect(dragging.state.phase.drag.siblingSettles.get(1)?.current.x).toBe(0);
    expect(dragging.state.phase.drag.siblingSettles.get(2)?.current.x).toBe(
      CARD_WIDTH,
    );

    const dropped = act(dragging.state, {
      kind: "itemPointerEnd",
      pointerId: 7,
      clientX: 100 + 2 * CARD_WIDTH,
      clientY: 80,
      world: { x: 100 + 2 * CARD_WIDTH, y: 80 },
      cancelled: false,
      cardId: "pages",
      scene: scene({
        windowed: false,
        frameWidth: 3 * CARD_WIDTH,
        layoutTotalCols: 30,
      }),
    });
    expect(dropped.effects).toContainEqual({
      kind: "notifyReorder",
      cardId: "pages",
      fromIndex: 0,
      toIndex: reorderDropIndex(0, 2),
    });
    expect(phaseKind(dropped.state)).toBe("idle");
    expect(visualSlotForSibling(2, 0, "reorder", 2, 0, 3)).toBe(1);
  });

  it("steps the window from a side stack and stays in the drag", () => {
    let state = boot(6, 4, false).state;
    state = down(state, 1, 1, { col: 300, row: 100 }).state;
    const overRight = act(state, {
      kind: "itemPointerMove",
      pointerId: 7,
      clientX: 3 * CARD_WIDTH + 40,
      clientY: 100,
      world: { x: 3 * CARD_WIDTH + 40, y: 100 },
      scene: scene(),
      ...clock(1000, false),
    });
    if (overRight.state.phase.kind !== "draggingItem") return;
    expect(overRight.state.phase.drag.mode).toBe("right");
    expect(kinds(overRight.effects)).toContain("armHoverStepTimer");

    const stepped = act(overRight.state, {
      kind: "hoverStackTimerFired",
      ...clock(1400, false),
    });
    expect(stepped.state.windowStart).toBe(1);
    expect(phaseKind(stepped.state)).toBe("draggingItem");
    expect(kinds(stepped.effects)).toContain("armHoverStepTimer");
    if (stepped.state.phase.kind !== "draggingItem") return;
    expect(stepped.state.phase.drag.siblingSettles.size).toBe(0);
  });

  it("extracts onto a non-overlapping cell and ignores pointercancel", () => {
    const blocker: CellCardModel = {
      ...CARD,
      id: "blocker",
      col: 10,
      row: 8,
    };
    const hit = scene({
      windowed: false,
      frameWidth: 3 * CARD_WIDTH,
      layoutTotalCols: 30,
      foregroundCards: [CARD, blocker],
    });
    let state = boot(3, 3, false).state;
    state = down(state, 0, 0, { col: 125, row: 100 }).state;
    const outside = { x: 10 * CELL_SIZE + 125, y: 8 * CELL_SIZE + 100 };
    state = act(state, {
      kind: "itemPointerMove",
      pointerId: 7,
      clientX: outside.x,
      clientY: outside.y,
      world: outside,
      scene: hit,
      ...clock(1000, false, false),
    }).state;
    if (state.phase.kind !== "draggingItem") return;
    expect(state.phase.drag.mode).toBe("extract");
    const landing = state.phase.drag.landing;
    expect(landing).not.toBeNull();
    if (!landing) return;
    const overlaps =
      landing.col < blocker.col + blocker.widthCells &&
      blocker.col < landing.col + CARD.widthCells &&
      landing.row < blocker.row + blocker.heightCells &&
      blocker.row < landing.row + CARD.heightCells;
    expect(overlaps).toBe(false);

    const dropped = act(state, {
      kind: "itemPointerEnd",
      pointerId: 7,
      clientX: outside.x,
      clientY: outside.y,
      world: outside,
      cancelled: false,
      cardId: "pages",
      scene: hit,
    });
    expect(dropped.effects).toContainEqual({
      kind: "notifyExtract",
      cardId: "pages",
      index: 0,
      targetCell: landing,
    });

    const cancelled = act(state, {
      kind: "itemPointerEnd",
      pointerId: 7,
      clientX: outside.x,
      clientY: outside.y,
      world: outside,
      cancelled: true,
      cardId: "pages",
      scene: hit,
    });
    expect(kinds(cancelled.effects)).toEqual([
      "cancelDragFrame",
      "clearHoverStepTimer",
    ]);
    expect(phaseKind(cancelled.state)).toBe("idle");
  });
});

describe("spread move", () => {
  const hit = scene({
    windowed: false,
    frameWidth: 3 * CARD_WIDTH,
    layoutTotalCols: 30,
    foregroundCards: [CARD, { ...CARD, id: "blocker", col: 4, row: 10 }],
  });

  it("moves by a non-overlapping delta and ignores pointercancel", () => {
    let state = boot(3, 3, false).state;
    state = act(state, {
      kind: "movePointerDown",
      pointerId: 4,
      button: 0,
      clientX: 200,
      clientY: 100,
      world: { x: 200, y: 100 },
    }).state;
    const nudged = act(state, {
      kind: "movePointerMove",
      pointerId: 4,
      clientX: 202,
      clientY: 100,
      world: { x: 202, y: 100 },
      scene: hit,
      nowMs: 1000,
      animateMotion: false,
    });
    expect(nudged.state).toBe(state);

    const moved = act(state, {
      kind: "movePointerMove",
      pointerId: 4,
      clientX: 200 + 4 * CELL_SIZE,
      clientY: 100 + 2 * CELL_SIZE,
      world: { x: 200 + 4 * CELL_SIZE, y: 100 + 2 * CELL_SIZE },
      scene: hit,
      nowMs: 1000,
      animateMotion: false,
    });
    if (moved.state.phase.kind !== "movingSpread") return;
    expect(moved.state.phase.move.active).toBe(true);
    expect(moved.state.phase.move.landingDelta).toEqual({ col: 4, row: 2 });

    const dropped = act(moved.state, {
      kind: "movePointerEnd",
      pointerId: 4,
      world: { x: 200 + 4 * CELL_SIZE, y: 100 + 2 * CELL_SIZE },
      cancelled: false,
      cardId: "pages",
      scene: hit,
    });
    expect(dropped.effects).toContainEqual({
      kind: "notifyMove",
      cardId: "pages",
      col: 4,
      row: 2,
    });

    const cancelled = act(moved.state, {
      kind: "movePointerEnd",
      pointerId: 4,
      world: { x: 200 + 4 * CELL_SIZE, y: 100 + 2 * CELL_SIZE },
      cancelled: true,
      cardId: "pages",
      scene: hit,
    });
    expect(kinds(cancelled.effects)).toEqual(["cancelMoveFrame"]);
    expect(
      cancelled.effects.some((effect) => effect.kind === "notifyMove"),
    ).toBe(false);
  });
});

describe("keyboard reorder and syncProps", () => {
  it("reorders the active item from the keyboard", () => {
    let state = boot(4, 4, false).state;
    state = act(state, { kind: "setActiveIndex", index: 1 }).state;
    const moved = act(state, {
      kind: "keyboardReorder",
      direction: 1,
      cardId: "pages",
      canReorder: true,
    });
    expect(moved.effects).toEqual([
      {
        kind: "notifyReorder",
        cardId: "pages",
        fromIndex: 1,
        toIndex: 2,
      },
    ]);
    expect(moved.state.activeIndex).toBe(2);
    const blocked = act(moved.state, {
      kind: "keyboardReorder",
      direction: 1,
      cardId: "pages",
      canReorder: false,
    });
    expect(blocked.state).toBe(moved.state);
  });

  it("clamps the stored window when items shrink and does not jump back", () => {
    let state = boot(6, 4, false).state;
    state = act(state, { kind: "step", by: 2, ...clock(1000, false) }).state;
    expect(state.windowStart).toBe(2);
    const shrunk = act(state, {
      kind: "syncProps",
      items: items(5),
      windowed: true,
      previousWindowed: true,
      layoutVisibleCount: 4,
    });
    expect(shrunk.state.windowStart).toBe(1);
    expect(shrunk.state.visibleCount).toBe(4);
    expect(shrunk.effects).toContainEqual({
      kind: "notifyWindowStartChange",
      windowStart: 1,
    });
    const grown = act(shrunk.state, {
      kind: "syncProps",
      items: items(6),
      windowed: true,
      previousWindowed: true,
      layoutVisibleCount: 4,
    });
    expect(grown.state.windowStart).toBe(1);
    expect(grown.effects).toEqual([]);
  });
});
