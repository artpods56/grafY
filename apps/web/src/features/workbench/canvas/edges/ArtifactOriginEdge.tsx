"use client";

import { BaseEdge, EdgeLabelRenderer, type EdgeProps } from "@xyflow/react";
import * as stylex from "@stylexjs/stylex";
import { Unplug } from "lucide-react";
import { tokens } from "@/lib/stylex/tokens.stylex";
import type { ArtifactOriginEdge } from "../artifact-connections";
import { routedBezierPath } from "./edge-path";

const s = stylex.create({
  disconnect: {
    position: "absolute",
    display: "grid",
    placeItems: "center",
    width: "28px",
    height: "28px",
    borderRadius: "6px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    backgroundColor: tokens.colorSurfaceRaised,
    color: tokens.colorText,
    pointerEvents: "all",
    cursor: "pointer",
  },
});

export default function ArtifactOriginEdgeControl(
  props: EdgeProps<ArtifactOriginEdge>,
) {
  // The same exit-then-turn curve as every other canvas edge.
  const {
    path,
    anchor: { x, y },
  } = routedBezierPath({
    source: { x: props.sourceX, y: props.sourceY },
    target: { x: props.targetX, y: props.targetY },
    sourcePosition: props.sourcePosition,
    targetPosition: props.targetPosition,
    routeOffset: { x: 0, y: 0 },
  });
  return (
    <>
      <BaseEdge
        id={props.id}
        path={path}
        style={{
          stroke: tokens.colorInfo,
          strokeWidth: props.selected ? 3 : 2,
        }}
      />
      {props.selected && props.data?.onDisconnect ? (
        <EdgeLabelRenderer>
          <button
            type="button"
            className="nodrag nopan"
            aria-label="Disconnect artifact input"
            {...stylex.props(s.disconnect)}
            style={{
              transform: `translate(-50%, -50%) translate(${x}px, ${y}px)`,
            }}
            onClick={() => {
              if (props.data) props.data.onDisconnect?.(props.data.originId);
            }}
          >
            <Unplug size={14} />
          </button>
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
}
