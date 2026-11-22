import { describe, expect, it } from "vitest";

import {
  REMOTE_CURSOR_TELEPORT_DISTANCE,
  applyRemoteCursorSample,
  beginRemoteCursorFade,
  createRemoteCursorMotion,
  stepRemoteCursorMotion,
} from "./remote-cursor-motion";

describe("remote cursor motion", () => {
  it("lerps toward sparse samples instead of snapping", () => {
    let motion = createRemoteCursorMotion({ x: 0, y: 0, at: 0 });
    motion = applyRemoteCursorSample(motion, { x: 100, y: 0, at: 50 });

    const stepped = stepRemoteCursorMotion(motion, 66, 16);
    expect(stepped).not.toBeNull();
    expect(stepped!.x).toBeGreaterThan(0);
    expect(stepped!.x).toBeLessThan(100);
  });

  it("teleports across huge jumps", () => {
    let motion = createRemoteCursorMotion({ x: 0, y: 0, at: 0 });
    motion = applyRemoteCursorSample(motion, {
      x: REMOTE_CURSOR_TELEPORT_DISTANCE + 10,
      y: 0,
      at: 50,
    });
    expect(motion.x).toBe(REMOTE_CURSOR_TELEPORT_DISTANCE + 10);
    expect(motion.vx).toBe(0);
  });

  it("stays fully opaque while idle without new samples", () => {
    const motion = createRemoteCursorMotion({ x: 10, y: 20, at: 0 });
    const idle = stepRemoteCursorMotion(motion, 1000, 16);
    expect(idle).not.toBeNull();
    expect(idle!.opacity).toBe(1);
    expect(idle!.x).toBe(10);
    expect(idle!.y).toBe(20);
  });

  it("fades out and then removes the cursor only after leave", () => {
    let motion = createRemoteCursorMotion({ x: 10, y: 20, at: 0 });
    motion = beginRemoteCursorFade(motion);

    const mid = stepRemoteCursorMotion(motion, 80, 80);
    expect(mid).not.toBeNull();
    expect(mid!.opacity).toBeGreaterThan(0);
    expect(mid!.opacity).toBeLessThan(1);

    expect(stepRemoteCursorMotion(mid!, 200, 120)).toBeNull();
  });

  it("predicts slightly along recent velocity", () => {
    let motion = createRemoteCursorMotion({ x: 0, y: 0, at: 0 });
    motion = applyRemoteCursorSample(motion, { x: 100, y: 0, at: 50 });
    // Display still at origin; sample target is 100 with positive vx.
    motion = { ...motion, x: 0, y: 0 };

    const withoutAge = stepRemoteCursorMotion(
      { ...motion, lastSampleAt: 1000 },
      1000,
      16,
    );
    const withAge = stepRemoteCursorMotion(
      { ...motion, lastSampleAt: 1000 },
      1030,
      16,
    );

    expect(withAge!.x).toBeGreaterThan(withoutAge!.x);
  });
});
