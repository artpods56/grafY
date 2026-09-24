"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { ViewportPortal } from "@xyflow/react";

import type { PresenceParticipant } from "./protocol";
import {
  applyRemoteCursorSample,
  beginRemoteCursorFade,
  createRemoteCursorMotion,
  stepRemoteCursorMotion,
  type RemoteCursorMotion,
} from "./remote-cursor-motion";
import { actorColor } from "./remote-selection";

const s = stylex.create({
  cursor: {
    position: "absolute",
    left: 0,
    top: 0,
    pointerEvents: "none",
    zIndex: 5,
    display: "grid",
    justifyItems: "start",
    gap: "2px",
    willChange: "transform, opacity",
  },
  pointer: {
    display: "block",
    width: "20px",
    height: "24px",
    overflow: "visible",
    filter: "drop-shadow(0 1px 1.5px rgba(0, 0, 0, 0.35))",
  },
  label: {
    maxWidth: "120px",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    marginLeft: "12px",
    marginTop: "-4px",
    padding: "1px 5px",
    borderRadius: "4px",
    color: "#fff",
    fontSize: "10px",
    fontWeight: 650,
    lineHeight: 1.3,
  },
  strip: {
    position: "absolute",
    zIndex: 25,
    top: "62px",
    right: "13px",
    display: "flex",
    flexWrap: "wrap",
    justifyContent: "flex-end",
    gap: "6px",
    maxWidth: "min(280px, 40vw)",
    pointerEvents: "none",
  },
  chip: {
    display: "inline-flex",
    alignItems: "center",
    gap: "5px",
    minHeight: "24px",
    padding: "2px 8px 2px 6px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor:
      "light-dark(rgba(15, 23, 42, 0.12), rgba(255, 255, 255, 0.14))",
    borderRadius: "999px",
    backgroundColor:
      "light-dark(rgba(255, 255, 255, 0.88), rgba(24, 26, 30, 0.88))",
    color: "light-dark(#1f2937, #e5e7eb)",
    fontSize: "11px",
    fontWeight: 600,
    lineHeight: 1,
    boxShadow: "0 1px 2px rgba(0, 0, 0, 0.08)",
  },
  dot: {
    width: "8px",
    height: "8px",
    borderRadius: "999px",
    flex: "0 0 auto",
  },
  activity: {
    color: "light-dark(#6b7280, #9ca3af)",
    fontWeight: 500,
  },
});

function activityLabel(
  activity: PresenceParticipant["activity"],
): string | null {
  if (activity === "moving_nodes") return "moving";
  if (activity === "editing_node") return "editing";
  if (activity === "connecting") return "connecting";
  return null;
}

interface CursorTrack {
  sessionId: string;
  displayName: string;
  color: string;
  motion: RemoteCursorMotion;
  element: HTMLDivElement | null;
}

interface CursorTrackView {
  sessionId: string;
  displayName: string;
  color: string;
  x: number;
  y: number;
  opacity: number;
}

export interface PresenceOverlayProps {
  participants: readonly PresenceParticipant[];
  localSessionId: string | null;
  /** Injectable clock for tests. */
  now?: () => number;
}

export function PresenceOverlay({
  participants,
  localSessionId,
  now = () => performance.now(),
}: PresenceOverlayProps) {
  const remote = React.useMemo(
    () =>
      participants.filter(
        (participant) => participant.graph_room_session_id !== localSessionId,
      ),
    [localSessionId, participants],
  );

  const tracksRef = React.useRef(new Map<string, CursorTrack>());
  const [cursorTracks, setCursorTracks] = React.useState<
    readonly CursorTrackView[]
  >([]);
  const rafRef = React.useRef<number | null>(null);
  const lastFrameRef = React.useRef<number | null>(null);
  const nowRef = React.useRef(now);

  React.useEffect(() => {
    nowRef.current = now;
  }, [now]);

  const publishCursorTracks = React.useCallback(() => {
    const next = [...tracksRef.current.values()].map((track) => ({
      sessionId: track.sessionId,
      displayName: track.displayName,
      color: track.color,
      x: track.motion.x,
      y: track.motion.y,
      opacity: track.motion.opacity,
    }));
    setCursorTracks((current) => {
      const unchanged =
        current.length === next.length &&
        current.every((track, index) => {
          const candidate = next[index];
          return (
            candidate !== undefined &&
            track.sessionId === candidate.sessionId &&
            track.displayName === candidate.displayName &&
            track.color === candidate.color
          );
        });
      return unchanged ? current : next;
    });
  }, []);

  const ensureAnimationLoop = React.useCallback(() => {
    if (rafRef.current !== null || tracksRef.current.size === 0) return;

    const frame = (frameTime: number) => {
      const previous = lastFrameRef.current ?? frameTime;
      lastFrameRef.current = frameTime;
      const dtMs = frameTime - previous;
      const clock = nowRef.current();
      let removed = false;

      for (const [sessionId, track] of tracksRef.current) {
        const next = stepRemoteCursorMotion(track.motion, clock, dtMs);
        if (next === null) {
          tracksRef.current.delete(sessionId);
          removed = true;
          continue;
        }
        track.motion = next;
        const element = track.element;
        if (element) {
          element.style.transform = `translate3d(${next.x}px, ${next.y}px, 0)`;
          element.style.opacity = String(next.opacity);
        }
      }

      if (removed) publishCursorTracks();
      if (tracksRef.current.size > 0) {
        rafRef.current = window.requestAnimationFrame(frame);
      } else {
        rafRef.current = null;
        lastFrameRef.current = null;
      }
    };

    rafRef.current = window.requestAnimationFrame(frame);
  }, [publishCursorTracks]);

  React.useEffect(() => {
    return () => {
      if (rafRef.current !== null) {
        window.cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      lastFrameRef.current = null;
    };
  }, []);

  // Merge presence samples into motion tracks (targets only — rAF owns display).
  React.useEffect(() => {
    const tracks = tracksRef.current;
    const seen = new Set<string>();
    const sampleAt = now();

    for (const participant of remote) {
      const sessionId = participant.graph_room_session_id;
      seen.add(sessionId);
      const color = actorColor(participant.actor.color);
      const existing = tracks.get(sessionId);
      if (!participant.cursor) {
        if (existing && !existing.motion.fadingOut) {
          tracks.set(sessionId, {
            ...existing,
            motion: beginRemoteCursorFade(existing.motion),
            displayName: participant.actor.display_name,
            color,
          });
        }
        continue;
      }
      if (!existing) {
        tracks.set(sessionId, {
          sessionId,
          displayName: participant.actor.display_name,
          color,
          motion: createRemoteCursorMotion({
            x: participant.cursor.x,
            y: participant.cursor.y,
            at: sampleAt,
          }),
          element: null,
        });
        continue;
      }
      tracks.set(sessionId, {
        ...existing,
        displayName: participant.actor.display_name,
        color,
        motion: applyRemoteCursorSample(existing.motion, {
          x: participant.cursor.x,
          y: participant.cursor.y,
          at: sampleAt,
        }),
      });
    }

    for (const [sessionId, track] of tracks) {
      if (seen.has(sessionId) || track.motion.fadingOut) continue;
      tracks.set(sessionId, {
        ...track,
        motion: beginRemoteCursorFade(track.motion),
      });
    }

    publishCursorTracks();
    ensureAnimationLoop();
  }, [ensureAnimationLoop, now, publishCursorTracks, remote]);

  if (remote.length === 0 && cursorTracks.length === 0) return null;

  return (
    <>
      {remote.length > 0 ? (
        <div {...stylex.props(s.strip)} aria-label="Collaborators">
          {remote.map((participant) => {
            const color = actorColor(participant.actor.color);
            const activity = activityLabel(participant.activity);
            return (
              <span
                key={participant.graph_room_session_id}
                {...stylex.props(s.chip)}
                title={participant.actor.display_name}
              >
                <span
                  {...stylex.props(s.dot)}
                  style={{ backgroundColor: color }}
                />
                {participant.actor.display_name}
                {activity ? (
                  <span {...stylex.props(s.activity)}>{activity}</span>
                ) : null}
              </span>
            );
          })}
        </div>
      ) : null}
      {cursorTracks.length > 0 ? (
        <ViewportPortal>
          {cursorTracks.map((track) => (
            <div
              key={`cursor-${track.sessionId}`}
              ref={(element) => {
                const current = tracksRef.current.get(track.sessionId);
                if (current) current.element = element;
                if (element) {
                  const motion = current?.motion ?? track;
                  element.style.transform = `translate3d(${motion.x}px, ${motion.y}px, 0)`;
                  element.style.opacity = String(motion.opacity);
                }
              }}
              {...stylex.props(s.cursor)}
              aria-hidden
            >
              <svg {...stylex.props(s.pointer)} viewBox="0 0 24 24" aria-hidden>
                {/* Classic OS-style pointer; tip is the hotspot at (0,0). */}
                <path
                  d="M0.6 0.6v17.4l4.9-4.7 3.5 8.1 2.9-1.3-3.6-7.9H18z"
                  fill={track.color}
                  stroke="#ffffff"
                  strokeWidth="1.4"
                  strokeLinejoin="round"
                  paintOrder="stroke fill"
                />
              </svg>
              <span
                {...stylex.props(s.label)}
                style={{ backgroundColor: track.color }}
              >
                {track.displayName}
              </span>
            </div>
          ))}
        </ViewportPortal>
      ) : null}
    </>
  );
}
