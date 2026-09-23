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
  conversionPathsEqual,
  edgeTransportChipLabel,
  feedChoicesFromRouteOptions,
  projectionsEqual,
} from "../../model/connection-feeds";
import { useOptionalCanvasGridSettings } from "../canvas-grid-settings";
import { GRID_CELL_SIZE_DEFAULT } from "../grid-layout";
import type {
  WorkflowEdge,
  WorkflowEdgeData,
  WorkflowEdgeRoute,
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
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorBorder,
  },
  sectionLast: { borderBottomWidth: 0 },
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
    color: { default: tokens.colorText, ":disabled": tokens.colorTextDisabled },
    cursor: { default: "pointer", ":disabled": "not-allowed" },
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

function routeSelection(option: WorkflowEdgeRouteOption): WorkflowEdgeRoute {
  return {
    projection: option.projection
      ? { path: [...option.projection.path] }
      : undefined,
    conversionPath: option.conversionPath.map((conversion) => ({
      id: conversion.id,
      version: conversion.version,
    })),
  };
}

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

export default function WorkflowEdgeControl({
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
}: EdgeProps<WorkflowEdge>) {
  const { deleteElements } = useReactFlow();
  const docked = useEdgeIsDocked(id);
  const cellSize =
    useOptionalCanvasGridSettings()?.settings.cellSize ??
    GRID_CELL_SIZE_DEFAULT;
  const edgeData: WorkflowEdgeData = data ?? {
    enabled: true,
    collectionMode: "direct",
  };
  const onUpdate = edgeData.onUpdate;
  const enabled = edgeData.enabled !== false;
  const compatibilityIssues = edgeData.compatibilityIssues ?? [];
  const compatible = compatibilityIssues.length === 0;
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

  const sourcePortName = edgeData.sourcePortName ?? "output";
  const activeRoute: WorkflowEdgeRoute = {
    projection: edgeData.projection,
    conversionPath: edgeData.conversionPath ?? [],
  };
  const routeOptions = edgeData.routeOptions?.length
    ? edgeData.routeOptions
    : [
        {
          ...activeRoute,
          conversionTitles: edgeData.conversionTitles ?? [],
        },
      ];
  const feedChoices = feedChoicesFromRouteOptions(sourcePortName, routeOptions);
  const activeProjectionTitle = routeOptions.find(
    (route) =>
      projectionsEqual(route.projection, activeRoute.projection) &&
      conversionPathsEqual(route.conversionPath, activeRoute.conversionPath),
  )?.projectionTitle;
  const allowedModes = edgeData.allowedCollectionModes ?? [
    edgeData.collectionMode,
  ];
  const showCollectionChooser = allowedModes.length > 1;
  const label = edgeTransportChipLabel({
    sourcePortName,
    projection: edgeData.projection,
    projectionTitle: activeProjectionTitle,
    conversionTitles: edgeData.conversionTitles,
    collectionMode: edgeData.collectionMode,
    enabled,
    compatible,
  });
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
        style={{
          ...style,
          opacity: docked
            ? 0
            : !compatible
              ? selected
                ? 0.82
                : 0.58
              : enabled
                ? style?.opacity
                : selected
                  ? 0.58
                  : 0.42,
          strokeDasharray:
            docked || (compatible && enabled) ? style?.strokeDasharray : "7 5",
          strokeWidth: selected ? 2.7 : (style?.strokeWidth ?? 2),
        }}
        interactionWidth={24}
      />
      <EdgeLabelRenderer>
        <EdgeSelectorBlock
          anchor={bridge?.anchor ?? anchor}
          selected={selected}
          disabled={!(enabled && compatible)}
          label={label}
          docked={docked}
          width={bridge?.width}
          height={bridge?.height}
          bendAriaLabel={`Bend connection ${label}`}
          bendDragging={draftRouteOffset != null}
          bendHandlers={bendHandlers}
          editAriaLabel={
            compatible
              ? `Edit connection ${label}`
              : `Connection unavailable: ${compatibilityIssues.join(" ")}`
          }
          editTitle={
            compatible
              ? "Edit what this connection feeds into the input"
              : compatibilityIssues.join(" ")
          }
          editDisabled={!compatible}
          removeAriaLabel={`Remove connection ${label}`}
          onRemove={() => {
            void deleteElements({ edges: [{ id }] });
          }}
        >
          <header {...stylex.props(s.header)}>
            <span {...stylex.props(s.title)}>What should arrive?</span>
            <span {...stylex.props(s.summary)}>
              This connection chooses the value fed into the input.
            </span>
          </header>

          <section
            {...stylex.props(
              s.section,
              showCollectionChooser ? null : s.sectionLast,
            )}
          >
            <span {...stylex.props(s.sectionTitle)}>Feed</span>
            {onUpdate
              ? feedChoices.map((choice) => (
                  <EdgeOption
                    key={choice.key}
                    title={choice.title}
                    description={choice.description}
                    active={
                      projectionsEqual(
                        activeRoute.projection,
                        choice.route.projection,
                      ) &&
                      conversionPathsEqual(
                        activeRoute.conversionPath,
                        choice.route.conversionPath,
                      )
                    }
                    onSelect={() =>
                      onUpdate(id, {
                        route: routeSelection(choice.route),
                      })
                    }
                  />
                ))
              : null}
          </section>

          {showCollectionChooser ? (
            <section {...stylex.props(s.section, s.sectionLast)}>
              <span {...stylex.props(s.sectionTitle)}>How many times?</span>
              <button
                type="button"
                disabled={!allowedModes.includes("direct")}
                {...stylex.props(
                  overlay.item,
                  s.option,
                  edgeData.collectionMode === "direct"
                    ? overlay.itemActive
                    : null,
                )}
                onClick={() =>
                  edgeData.onUpdate?.(id, {
                    collectionMode: "direct",
                  })
                }
              >
                <span {...stylex.props(s.optionCopy)}>
                  <span {...stylex.props(s.optionTitle)}>Pass whole value</span>
                  <span {...stylex.props(s.optionDescription)}>
                    Invoke the target once with this feed.
                  </span>
                </span>
                {edgeData.collectionMode === "direct" ? (
                  <Check size={12} {...stylex.props(s.check)} />
                ) : null}
              </button>
              <button
                type="button"
                disabled={!allowedModes.includes("map")}
                {...stylex.props(
                  overlay.item,
                  s.option,
                  edgeData.collectionMode === "map" ? overlay.itemActive : null,
                )}
                onClick={() =>
                  edgeData.onUpdate?.(id, { collectionMode: "map" })
                }
              >
                <span {...stylex.props(s.optionCopy)}>
                  <span {...stylex.props(s.optionTitle)}>Map each item</span>
                  <span {...stylex.props(s.optionDescription)}>
                    Invoke the target once for every item.
                  </span>
                </span>
                {edgeData.collectionMode === "map" ? (
                  <Check size={12} {...stylex.props(s.check)} />
                ) : null}
              </button>
            </section>
          ) : null}
        </EdgeSelectorBlock>
      </EdgeLabelRenderer>
    </>
  );
}
