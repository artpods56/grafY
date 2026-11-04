"use client";

import { BaseEdge, EdgeLabelRenderer, type EdgeProps } from "@xyflow/react";
import * as stylex from "@stylexjs/stylex";
import { Layers, Unplug } from "lucide-react";
import { Button, IconButton } from "@/components/ui/button";
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
  /**
   * The kit's small Button draws the chip; these keep the control's declared
   * type and the edge-control surface it wore before the kit existed.
   */
  mapToggle: {
    fontSize: tokens.fontSizeXs,
    fontWeight: 650,
    backgroundColor: tokens.colorSurfaceRaised,
  },
  mapToggleActive: {
    borderColor: tokens.colorInfo,
    color: tokens.colorInfo,
  },
  disconnect: {
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusSm,
    backgroundColor: tokens.colorSurfaceRaised,
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
              <Button
                size="sm"
                pressed={mapped}
                title={
                  mapped
                    ? "Invoking the target once for every item"
                    : "Invoking the target once with the whole sequence"
                }
                xstyle={[s.mapToggle, mapped ? s.mapToggleActive : null]}
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
              </Button>
            ) : null}
            {data?.onDisconnect ? (
              <IconButton
                label="Disconnect artifact input"
                variant="soft"
                size="md"
                xstyle={s.disconnect}
                onClick={() => {
                  if (data) data.onDisconnect?.(data.originId);
                }}
              >
                <Unplug size={14} />
              </IconButton>
            ) : null}
          </div>
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
}
