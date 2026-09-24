/** Smoothing time constant — catches ~20Hz samples without looking teleported. */
export const REMOTE_CURSOR_SMOOTHING_TAU_MS = 55;
/** Extrapolate along last velocity only while samples are this fresh. */
export const REMOTE_CURSOR_PREDICT_MS = 90;
/** Cap predicted lead so laggy peers don't overshoot. */
export const REMOTE_CURSOR_MAX_PREDICT_MS = 45;
/** After this without a sample, stop predicting and ease to the last point. */
export const REMOTE_CURSOR_STALE_MS = 220;
/** Fade-out duration once the peer leaves the canvas / room. */
export const REMOTE_CURSOR_FADE_MS = 180;
/** Snap when the jump is huge (pan/teleport) instead of sliding across the board. */
export const REMOTE_CURSOR_TELEPORT_DISTANCE = 1400;

export interface RemoteCursorSample {
  x: number;
  y: number;
  at: number;
}

export interface RemoteCursorMotion {
  x: number;
  y: number;
  vx: number;
  vy: number;
  targetX: number;
  targetY: number;
  lastSampleAt: number;
  opacity: number;
  fadingOut: boolean;
  initialized: boolean;
}

export function createRemoteCursorMotion(
  sample?: RemoteCursorSample | null,
): RemoteCursorMotion {
  if (!sample) {
    return {
      x: 0,
      y: 0,
      vx: 0,
      vy: 0,
      targetX: 0,
      targetY: 0,
      lastSampleAt: 0,
      opacity: 0,
      fadingOut: false,
      initialized: false,
    };
  }
  return {
    x: sample.x,
    y: sample.y,
    vx: 0,
    vy: 0,
    targetX: sample.x,
    targetY: sample.y,
    lastSampleAt: sample.at,
    opacity: 1,
    fadingOut: false,
    initialized: true,
  };
}

export function applyRemoteCursorSample(
  motion: RemoteCursorMotion,
  sample: RemoteCursorSample,
): RemoteCursorMotion {
  if (!motion.initialized) {
    return createRemoteCursorMotion(sample);
  }
  const dtSeconds = Math.max(0.001, (sample.at - motion.lastSampleAt) / 1000);
  const dx = sample.x - motion.targetX;
  const dy = sample.y - motion.targetY;
  const distance = Math.hypot(dx, dy);
  if (distance >= REMOTE_CURSOR_TELEPORT_DISTANCE) {
    return {
      ...motion,
      x: sample.x,
      y: sample.y,
      vx: 0,
      vy: 0,
      targetX: sample.x,
      targetY: sample.y,
      lastSampleAt: sample.at,
      opacity: 1,
      fadingOut: false,
    };
  }
  return {
    ...motion,
    vx: dx / dtSeconds,
    vy: dy / dtSeconds,
    targetX: sample.x,
    targetY: sample.y,
    lastSampleAt: sample.at,
    opacity: 1,
    fadingOut: false,
  };
}

export function beginRemoteCursorFade(
  motion: RemoteCursorMotion,
): RemoteCursorMotion {
  if (!motion.initialized) return motion;
  return {
    ...motion,
    vx: 0,
    vy: 0,
    fadingOut: true,
  };
}

/**
 * Advance displayed cursor toward the latest sample.
 * Returns null when a fade has finished and the cursor can be removed.
 */
export function stepRemoteCursorMotion(
  motion: RemoteCursorMotion,
  now: number,
  dtMs: number,
): RemoteCursorMotion | null {
  if (!motion.initialized) return motion;

  const dtSeconds = Math.max(0, Math.min(dtMs, 48)) / 1000;
  const ageMs = Math.max(0, now - motion.lastSampleAt);

  let aimX = motion.targetX;
  let aimY = motion.targetY;
  if (!motion.fadingOut && ageMs < REMOTE_CURSOR_PREDICT_MS) {
    const leadMs = Math.min(ageMs, REMOTE_CURSOR_MAX_PREDICT_MS);
    aimX += motion.vx * (leadMs / 1000);
    aimY += motion.vy * (leadMs / 1000);
  }

  const alpha = 1 - Math.exp(-dtMs / REMOTE_CURSOR_SMOOTHING_TAU_MS);
  let nextX = motion.x + (aimX - motion.x) * alpha;
  let nextY = motion.y + (aimY - motion.y) * alpha;

  // Settle once we're effectively on target to avoid endless sub-pixel churn.
  if (Math.hypot(aimX - nextX, aimY - nextY) < 0.15) {
    nextX = aimX;
    nextY = aimY;
  }

  // Stay fully visible while the peer is still on the canvas — idle cursors
  // intentionally stop sending samples, so age must not fade them out.
  let opacity = 1;
  if (motion.fadingOut) {
    opacity = Math.max(0, motion.opacity - dtMs / REMOTE_CURSOR_FADE_MS);
    if (opacity <= 0.01) return null;
  }

  return {
    ...motion,
    x: nextX,
    y: nextY,
    opacity,
    // Decay stored velocity when samples go stale so prediction winds down.
    vx:
      ageMs > REMOTE_CURSOR_STALE_MS
        ? motion.vx * Math.exp(-dtSeconds * 8)
        : motion.vx,
    vy:
      ageMs > REMOTE_CURSOR_STALE_MS
        ? motion.vy * Math.exp(-dtSeconds * 8)
        : motion.vy,
  };
}
