"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  BaseEdge,
  EdgeLabelRenderer,
  type EdgeProps,
  useReactFlow,
} from "@xyflow/react";
import { Check } from "lucide-react";

import { tokens } from "@/lib/stylex/tokens.stylex";
import { overlay } from "@/lib/stylex/overlay.stylex";
import {
  feedChoicesFromRouteOptions,
  projectionsEqual,
} from "../../model/connection-feeds";
import type {
  ArtifactViewerEdge,
  ArtifactViewerEdgeData,
  CanvasEdge,
  CanvasNode,
} from "../artifact-viewer";
import { useOptionalCanvasGridSettings } from "../canvas-grid-settings";
import { GRID_CELL_SIZE_DEFAULT } from "../grid-layout";
import type {
  WorkflowEdgeRouteOffset,
  WorkflowEdgeRouteOption,
} from "../types";
import { dockedBridgeLayout } from "./docked-connection";
import { EdgeSelectorBlock } from "./EdgeSelectorBlock";
import { applyHandleFanOffset, routedBezierPath } from "./edge-path";
import { useEdgeIsDocked } from "./useDockedConnection";
import { useEdgeFanOffsets } from "./useEdgeFanOffsets";
import {
  useEdgeRouteBendHandlers,
  useResolvedEdgeRouteOffset,
} from "./useEdgeRouteBend";

/**
 * Presentation link (workflow output → artifact viewer).
 * Dashed stroke keeps it distinct from run edges; 2×1 selector matches workflow chrome.
 */

const s = stylex.create({
  header: {
    display: "grid",
    gap: "3px",
    padding: "10px 11px",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorBorder,
  },
  title: { fontSize: tokens.fontSizeSm, fontWeight: 750 },
  summary: {
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.4,
  },
  section: {
    display: "grid",
    gap: "5px",
    padding: "9px 11px 11px",
  },
  sectionTitle: {
    color: tokens.colorMuted,
    fontSize: "10px",
    fontWeight: 800,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
  },
  option: {
    width: "100%",
    minHeight: "35px",
    display: "grid",
    gridTemplateColumns: "minmax(0,1fr) 16px",
    alignItems: "center",
    gap: "7px",
    padding: "6px 7px",
    borderRadius: "6px",
    color: tokens.colorText,
    cursor: "pointer",
    textAlign: "left",
  },
  optionCopy: { minWidth: 0, display: "grid", gap: "2px" },
  optionTitle: {
    overflow: "hidden",
    fontSize: tokens.fontSizeXs,
    fontWeight: 700,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  optionDescription: {
    color: tokens.colorSubtle,
    fontSize: "10px",
    lineHeight: 1.35,
  },
  check: { color: tokens.colorAccent },
});

function EdgeOption({
  title,
  description,
  active,
  onSelect,
}: {
  title: string;
  description: string;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      {...stylex.props(
        overlay.item,
        s.option,
        active ? overlay.itemActive : null,
      )}
      onClick={onSelect}
    >
      <span {...stylex.props(s.optionCopy)}>
        <span {...stylex.props(s.optionTitle)}>{title}</span>
        <span {...stylex.props(s.optionDescription)}>{description}</span>
      </span>
      {active ? <Check size={12} {...stylex.props(s.check)} /> : null}
    </button>
  );
}

function viewerChipLabel(
  sourcePortName: string,
  projection: ArtifactViewerEdgeData["projection"],
  projectionTitle?: string,
): string {
  if (projection?.path.length) {
    return `preview · ${projectionTitle ?? projection.path.join(".")}`;
  }
  return `preview · ${sourcePortName}`;
}

export default function ArtifactViewerEdgeControl({
  id,
  data,
  source: sourceNodeId,
  sourceX,
  sourceY,
  target: targetNodeId,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerEnd,
  style,
  selected,
}: EdgeProps<ArtifactViewerEdge>) {
  const { deleteElements } = useReactFlow<CanvasNode, CanvasEdge>();
  const docked = useEdgeIsDocked(id);
  const cellSize =
    useOptionalCanvasGridSettings()?.settings.cellSize ??
    GRID_CELL_SIZE_DEFAULT;
  const edgeData: ArtifactViewerEdgeData = data ?? { sourcePortName: "output" };
  const sourcePortName = edgeData.sourcePortName || "output";
  const fan = useEdgeFanOffsets(id, sourcePosition, targetPosition);
  const source = applyHandleFanOffset(
    { x: sourceX, y: sourceY },
    sourcePosition,
    fan.source,
  );
  const target = applyHandleFanOffset(
    { x: targetX, y: targetY },
    targetPosition,
    fan.target,
  );
  const savedRouteOffset = edgeData.routeOffset ?? { x: 0, y: 0 };
  const [draftRouteOffset, setDraftRouteOffset] =
    React.useState<WorkflowEdgeRouteOffset | null>(null);
  const rawRouteOffset = draftRouteOffset ?? savedRouteOffset;
  const natural = routedBezierPath({
    source,
    target,
    sourcePosition,
    targetPosition,
    routeOffset: { x: 0, y: 0 },
  });
  const routeOffset = useResolvedEdgeRouteOffset(
    natural.anchor,
    rawRouteOffset,
    draftRouteOffset != null,
    sourceNodeId,
    targetNodeId,
  );
  const { anchor, path: edgePath } = routedBezierPath({
    source,
    target,
    sourcePosition,
    targetPosition,
    routeOffset,
  });
  const bendHandlers = useEdgeRouteBendHandlers({
    naturalAnchor: natural.anchor,
    anchor,
    savedRouteOffset,
    routeOffset,
    setDraftRouteOffset,
    onRouteOffsetChange: edgeData.onRouteOffsetChange
      ? (offset) => edgeData.onRouteOffsetChange?.(id, offset)
      : undefined,
  });
  const routeOptions: readonly WorkflowEdgeRouteOption[] = edgeData.routeOptions
    ?.length
    ? edgeData.routeOptions
    : [
        {
          projection: edgeData.projection,
          conversionPath: [],
          conversionTitles: [],
          projectionTitle: edgeData.projectionTitle,
        },
      ];
  const feedChoices = feedChoicesFromRouteOptions(sourcePortName, routeOptions);
  const activeProjectionTitle = routeOptions.find((route) =>
    projectionsEqual(route.projection, edgeData.projection),
  )?.projectionTitle;
  const label = viewerChipLabel(
    sourcePortName,
    edgeData.projection,
    activeProjectionTitle ?? edgeData.projectionTitle,
  );
  const onUpdate = edgeData.onUpdate;
  const bridge = docked ? dockedBridgeLayout(source, target, cellSize) : null;

  return (
    <>
      <BaseEdge
        id={id}
        path={
          docked
            ? `M${source.x},${source.y} L${target.x},${target.y}`
            : edgePath
        }
        markerEnd={docked ? undefined : markerEnd}
        interactionWidth={24}
        style={{
          ...style,
          opacity: docked ? 0 : selected ? 0.9 : 0.62,
          strokeDasharray: docked ? undefined : "6 5",
          strokeWidth: selected ? 2.5 : (style?.strokeWidth ?? 2),
        }}
      />
      <EdgeLabelRenderer>
        <EdgeSelectorBlock
          anchor={bridge?.anchor ?? anchor}
          selected={selected}
          label={label}
          docked={docked}
          width={bridge?.width}
          height={bridge?.height}
          bendAriaLabel={`Bend preview connection ${label}`}
          bendDragging={draftRouteOffset != null}
          bendHandlers={bendHandlers}
          editAriaLabel={`Edit preview feed ${label}`}
          editTitle="Choose what this preview shows from the output"
          removeAriaLabel={`Remove preview connection ${label}`}
          onRemove={() => {
            void deleteElements({ edges: [{ id }] });
          }}
        >
          <header {...stylex.props(s.header)}>
            <span {...stylex.props(s.title)}>What should the viewer show?</span>
            <span {...stylex.props(s.summary)}>
              Pick the whole output or a declared field projection.
            </span>
          </header>
          <section {...stylex.props(s.section)}>
            <span {...stylex.props(s.sectionTitle)}>Preview feed</span>
            {onUpdate
              ? feedChoices.map((choice) => (
                  <EdgeOption
                    key={choice.key}
                    title={choice.title}
                    description={choice.description}
                    active={projectionsEqual(
                      edgeData.projection,
                      choice.route.projection,
                    )}
                    onSelect={() =>
                      onUpdate(id, {
                        projection: choice.route.projection
                          ? { path: [...choice.route.projection.path] }
                          : null,
                      })
                    }
                  />
                ))
              : null}
          </section>
        </EdgeSelectorBlock>
      </EdgeLabelRenderer>
    </>
  );
}
