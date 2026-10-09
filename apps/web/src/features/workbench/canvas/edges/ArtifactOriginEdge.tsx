"use client";

import { BaseEdge, EdgeLabelRenderer, type EdgeProps } from "@xyflow/react";
import * as stylex from "@stylexjs/stylex";
import { Layers, Unplug } from "lucide-react";
import { tokens } from "@/lib/stylex/tokens.stylex";
import type { ArtifactOriginEdge } from "../artifact-origin-edge";
import { routedBezierPath } from "./edge-path";

const s = stylex.create({
  controls: {
    position: "absolute",
    display: "flex",
    alignItems: "center",
    gap: "4px",
    pointerEvents: "all",
  },
  mapped: {
    position: "absolute",
    padding: "1px 6px",
    borderRadius: "999px",
    backgroundColor: tokens.colorSurfaceRaised,
    color: tokens.colorInfo,
    fontSize: "10px",
    fontWeight: 700,
    pointerEvents: "none",
    whiteSpace: "nowrap",
  },
  mapToggle: {
    height: "28px",
    display: "flex",
    alignItems: "center",
    gap: "5px",
    padding: "0 8px",
    borderRadius: "6px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    backgroundColor: tokens.colorSurfaceRaised,
    color: tokens.colorText,
    fontSize: tokens.fontSizeXs,
    fontWeight: 650,
    cursor: "pointer",
    whiteSpace: "nowrap",
  },
  mapToggleActive: {
    borderColor: tokens.colorInfo,
    color: tokens.colorInfo,
  },
  disconnect: {
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
  const data = props.data;
  const mapped = data?.collectionMode === "map";
  const canToggleMode =
    Boolean(data?.onCollectionModeChange) &&
    (data?.allowedCollectionModes?.length ?? 0) > 1;
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
      {mapped && !props.selected ? (
        <EdgeLabelRenderer>
          <span
            {...stylex.props(s.mapped)}
            style={{
              transform: `translate(-50%, -50%) translate(${x}px, ${y}px)`,
            }}
          >
            each item
          </span>
        </EdgeLabelRenderer>
      ) : null}
      {props.selected && (data?.onDisconnect || canToggleMode) ? (
        <EdgeLabelRenderer>
          <div
            className="nodrag nopan"
            {...stylex.props(s.controls)}
            style={{
              transform: `translate(-50%, -50%) translate(${x}px, ${y}px)`,
            }}
          >
            {canToggleMode ? (
              <button
                type="button"
                aria-pressed={mapped}
                title={
                  mapped
                    ? "Invoking the target once for every item"
                    : "Invoking the target once with the whole sequence"
                }
                {...stylex.props(s.mapToggle, mapped && s.mapToggleActive)}
                onClick={() => {
                  if (data)
                    data.onCollectionModeChange?.(
                      data.originId,
                      mapped ? "direct" : "map",
                    );
                }}
              >
                <Layers size={13} />
                Map each item
              </button>
            ) : null}
            {data?.onDisconnect ? (
              <button
                type="button"
                aria-label="Disconnect artifact input"
                {...stylex.props(s.disconnect)}
                onClick={() => {
                  if (data) data.onDisconnect?.(data.originId);
                }}
              >
                <Unplug size={14} />
              </button>
            ) : null}
          </div>
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
}
