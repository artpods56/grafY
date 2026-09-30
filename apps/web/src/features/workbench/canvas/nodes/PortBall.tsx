"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  Handle,
  Position,
  useConnection,
  useNodeConnections,
} from "@xyflow/react";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { PORT_RING_REACH, portMarkStyle } from "../handle-style";

export { PORT_RING_REACH };
import { useFollowHandleMotion } from "./usePickupLift";

/**
 * The one port mark every canvas card uses: a typed ring on a hairline stem,
 * in a slot that sits a small gap outside the card. Geometry lives in
 * `handle-style` ({@link PORT_RING_REACH}).
 */

/** Stagger for the reveal, so a card's marks slide out one after another. */
const REVEAL_STAGGER_MS = 35;
/** How long a revealed or tucked mark keeps moving, stagger included. */
export const PORT_SETTLE_MS = 2 * REVEAL_STAGGER_MS + 240;

const s = stylex.create({
  slot: {
    position: "relative",
    width: "30px",
    height: "30px",
    flexShrink: 0,
  },
  // Revealed: in place, full size. The delay is set per mark for the stagger.
  shown: {
    opacity: 1,
    visibility: "visible",
    pointerEvents: "auto",
    transform: "translate3d(0, 0, 0) scale(1)",
    transitionProperty: "transform, opacity, visibility",
    transitionTimingFunction:
      "cubic-bezier(0.22, 1, 0.36, 1), ease-out, linear",
    transitionDuration: {
      default: "240ms, 160ms, 0s",
      "@media (prefers-reduced-motion: reduce)": "0s, 0s, 0s",
    },
    transitionDelay: {
      default:
        "var(--port-reveal-delay, 0ms), var(--port-reveal-delay, 0ms), 0s",
      "@media (prefers-reduced-motion: reduce)": "0s, 0s, 0s",
    },
  },
  // Tucked: slid back under the card and faded. Visibility flips only once the
  // slide is done, so the mark is seen going back rather than vanishing.
  tucked: {
    opacity: 0,
    visibility: "hidden",
    pointerEvents: "none",
    transitionProperty: "transform, opacity, visibility",
    transitionTimingFunction: "cubic-bezier(0.4, 0, 1, 1), ease-in, linear",
    transitionDuration: {
      default: "140ms, 120ms, 0s",
      "@media (prefers-reduced-motion: reduce)": "0s, 0s, 0s",
    },
    transitionDelay: {
      default: "0s, 0s, 140ms",
      "@media (prefers-reduced-motion: reduce)": "0s, 0s, 0s",
    },
  },
  // Tucked marks rest with their centre on the card's edge, half under it:
  // the gap (8px) plus half a slot (15px).
  tuckedInput: { transform: "translate3d(23px, 0, 0) scale(0.6)" },
  tuckedOutput: { transform: "translate3d(-23px, 0, 0) scale(0.6)" },
  // A docked join draws its own bridge: the ball stays where it measures but
  // paints nothing and takes no pointer.
  docked: {
    opacity: 0,
    pointerEvents: "none",
  },
  // The 30px grab area around the ring-sized handle. Presses on it reach the
  // handle, and it inherits the handle's pointer events, so an inert port
  // stays inert.
  grab: {
    position: "absolute",
    top: "-10px",
    left: "-10px",
    width: "30px",
    height: "30px",
    borderRadius: "9999px",
  },
  // From the ring's centre back to the card's edge; the ring covers its end.
  stem: {
    position: "absolute",
    top: "50%",
    width: "23px",
    height: "1px",
    marginTop: "-0.5px",
    opacity: 0.5,
    pointerEvents: "none",
  },
  // An input sits left of its card, so its stem runs right; an output's left.
  stemInput: { left: "50%" },
  stemOutput: { right: "50%" },
  // The catalog's hollow disc, drawn with a border so it stays round at any
  // zoom. It swells and fills with its type colour while it is the end being
  // wired.
  ring: {
    position: "absolute",
    top: "50%",
    left: "50%",
    width: "10px",
    height: "10px",
    marginTop: "-5px",
    marginLeft: "-5px",
    boxSizing: "border-box",
    borderWidth: 2,
    borderStyle: "solid",
    borderRadius: "9999px",
    backgroundColor: tokens.colorSurface,
    pointerEvents: "none",
    transitionProperty: "transform, background-color",
    transitionDuration: {
      default: "140ms",
      "@media (prefers-reduced-motion: reduce)": "0s",
    },
    transitionTimingFunction: "cubic-bezier(0.22, 1, 0.36, 1)",
  },
  // A value handed in by an origin rather than an edge.
  ringSquare: { borderRadius: "2px" },
  ringHot: { transform: "scale(1.3)" },
});

/**
 * The React Flow handle is exactly the ring, centred in its slot. Inline, so it
 * overrides React Flow's own handle placement and paint.
 */
function handleBoxStyle(idle: boolean, locked: boolean): React.CSSProperties {
  return {
    position: "absolute",
    top: "10px",
    left: "10px",
    width: "10px",
    height: "10px",
    minWidth: 0,
    minHeight: 0,
    transform: "none",
    border: "none",
    borderRadius: "9999px",
    background: "transparent",
    boxShadow: "none",
    cursor: locked ? "not-allowed" : idle ? "default" : "crosshair",
    touchAction: "none",
    opacity: idle ? 0.3 : 1,
  };
}

interface PortRevealState {
  /** The card is picked up (selected) or one of its menus is open. */
  active: boolean;
  /** A connection is being drawn somewhere on the canvas. */
  connecting: boolean;
  /** Handle ids on this card that carry an edge. */
  connected: ReadonlySet<string>;
}

const PortRevealContext = React.createContext<PortRevealState | null>(null);

/**
 * When a card's ports are out: while it is picked up, while any connection is
 * being drawn (so every port can take it), and always for a port that carries
 * an edge, so an edge never ends on nothing. Edges are remeasured while the
 * ports move.
 */
export function usePortReveal({
  id,
  active,
  updateNodeInternals,
}: {
  id: string;
  active: boolean;
  updateNodeInternals: (id: string) => void;
}): PortRevealState {
  const connecting = useConnection((connection) => connection.inProgress);
  const connections = useNodeConnections({ id });
  const signature = connections
    .flatMap((connection) => [
      connection.source === id ? connection.sourceHandle : null,
      connection.target === id ? connection.targetHandle : null,
    ])
    .filter((handle): handle is string => Boolean(handle))
    .sort()
    .join("|");
  const connected = React.useMemo(
    () => new Set(signature ? signature.split("|") : []),
    [signature],
  );
  useFollowHandleMotion({
    id,
    motion: `${active}:${connecting}:${signature}`,
    durationMs: PORT_SETTLE_MS,
    updateNodeInternals,
  });
  return React.useMemo(
    () => ({ active, connecting, connected }),
    [active, connecting, connected],
  );
}

export const PortRevealProvider = PortRevealContext.Provider;

/** The per-mark reveal delay, read by `shown` so marks slide out in turn. */
export function revealDelay(order: number): React.CSSProperties {
  return {
    ["--port-reveal-delay" as string]: `${order * REVEAL_STAGGER_MS}ms`,
  };
}

/**
 * The slide for anything that rides a card's side with its ports (a card's
 * "⋯", say): out and in place, or tucked under the card on that side.
 */
export function revealStyles(out: boolean, side: "input" | "output") {
  return out
    ? s.shown
    : [s.tucked, side === "input" ? s.tuckedInput : s.tuckedOutput];
}

export interface PortBallProps {
  nodeId: string;
  handleId: string;
  side: "input" | "output";
  color: string;
  /** Sequence shape: the ring gains a second, outer ring. */
  sequence?: boolean;
  /** Fed by an origin: the ring is squared off. */
  square?: boolean;
  isConnectable?: boolean;
  /** Nothing to pass on yet: the port shows faded and does not light up. */
  idle?: boolean;
  /** A historical port that takes no new connection. */
  locked?: boolean;
  /** A docked join hides the ball but keeps where it measures. */
  docked?: boolean;
  /** Overrides the card's reveal rule (for example, always out). */
  revealed?: boolean;
  /** Position in the card's reveal stagger. */
  order?: number;
  ariaLabel: string;
  title?: string;
  /** Pass-through attributes on the slot, for tests and drop targets. */
  slotProps?: Record<`data-${string}`, string | undefined>;
}

/**
 * One port: a slot that slides out from under its card, holding a ring-sized
 * React Flow handle with a 30px grab area, a stem back to the card and the
 * typed ring. The ring lights up while the pointer is on it or while a
 * connection is being drawn from or onto it.
 */
export function PortBall({
  nodeId,
  handleId,
  side,
  color,
  sequence = false,
  square = false,
  isConnectable = true,
  idle = false,
  locked = false,
  docked = false,
  revealed: revealedOverride,
  order = 0,
  ariaLabel,
  title,
  slotProps,
}: PortBallProps) {
  const reveal = React.useContext(PortRevealContext);
  const [hovered, setHovered] = React.useState(false);
  const wiring = useConnection(
    (connection) =>
      connection.inProgress &&
      ((connection.fromHandle?.nodeId === nodeId &&
        connection.fromHandle.id === handleId) ||
        (connection.toHandle?.nodeId === nodeId &&
          connection.toHandle.id === handleId)),
  );
  const revealed =
    revealedOverride ??
    (reveal
      ? reveal.active || reveal.connecting || reveal.connected.has(handleId)
      : true);
  // A docked ball keeps its revealed geometry, so docking cannot flip-flop.
  const out = revealed || docked;
  const hot = isConnectable && !locked && (hovered || wiring);
  const input = side === "input";
  return (
    <div
      {...slotProps}
      data-port-out={out ? "true" : "false"}
      {...stylex.props(
        s.slot,
        revealStyles(out, side),
        docked ? s.docked : null,
      )}
      style={revealDelay(order)}
    >
      <Handle
        id={handleId}
        type={input ? "target" : "source"}
        position={input ? Position.Left : Position.Right}
        isConnectable={isConnectable && !locked}
        aria-disabled={!isConnectable || locked}
        aria-hidden={docked || undefined}
        aria-label={ariaLabel}
        title={title}
        data-port-hot={hot ? "true" : undefined}
        onPointerEnter={() => setHovered(true)}
        onPointerLeave={() => setHovered(false)}
        style={handleBoxStyle(idle, locked)}
      >
        <span aria-hidden="true" {...stylex.props(s.grab)} />
        <span
          aria-hidden="true"
          {...stylex.props(s.stem, input ? s.stemInput : s.stemOutput)}
          style={{ backgroundColor: color }}
        />
        <span
          aria-hidden="true"
          {...stylex.props(
            s.ring,
            square ? s.ringSquare : null,
            hot ? s.ringHot : null,
          )}
          style={{
            ...portMarkStyle(color, sequence),
            ...(hot ? { backgroundColor: color } : null),
          }}
        />
      </Handle>
    </div>
  );
}
