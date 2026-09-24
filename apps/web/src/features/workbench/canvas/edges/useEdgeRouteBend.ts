"use client";

import * as React from "react";
import { useReactFlow, useStore, useViewport } from "@xyflow/react";

import { useOptionalCanvasGridSettings } from "../canvas-grid-settings";
import {
  GRID_CELL_SIZE_DEFAULT,
  edgeSelectorBlockSize,
  edgeSelectorSnapPitch,
  shouldSnapPosition,
  snapEdgeSelectorRouteOffset,
} from "../grid-layout";
import type { WorkflowEdgeRouteOffset } from "../types";
import type { EdgeSelectorBendHandlers } from "./EdgeSelectorBlock";

interface Point {
  x: number;
  y: number;
}

/** Stable bend handlers; read live geometry from refs each event. */
export function useEdgeRouteBendHandlers({
  naturalAnchor,
  anchor,
  savedRouteOffset,
  routeOffset,
  setDraftRouteOffset,
  onRouteOffsetChange,
}: {
  /** Path midpoint with zero route offset — used when snapping. */
  naturalAnchor: Point;
  anchor: Point;
  savedRouteOffset: WorkflowEdgeRouteOffset;
  routeOffset: WorkflowEdgeRouteOffset;
  setDraftRouteOffset: React.Dispatch<
    React.SetStateAction<WorkflowEdgeRouteOffset | null>
  >;
  onRouteOffsetChange?: (offset: WorkflowEdgeRouteOffset) => void;
}): EdgeSelectorBendHandlers {
  const { screenToFlowPosition } = useReactFlow();
  const { zoom } = useViewport();
  const grid = useOptionalCanvasGridSettings();
  const dragRef = React.useRef<{
    grabOffset: Point;
    latestOffset: WorkflowEdgeRouteOffset;
    pointerId: number;
  } | null>(null);
  const liveRef = React.useRef({
    naturalAnchor,
    anchor,
    savedRouteOffset,
    routeOffset,
    setDraftRouteOffset,
    onRouteOffsetChange,
    zoom,
    screenToFlowPosition,
    grid,
  });
  React.useLayoutEffect(() => {
    liveRef.current = {
      naturalAnchor,
      anchor,
      savedRouteOffset,
      routeOffset,
      setDraftRouteOffset,
      onRouteOffsetChange,
      zoom,
      screenToFlowPosition,
      grid,
    };
  }, [
    anchor,
    grid,
    naturalAnchor,
    onRouteOffsetChange,
    routeOffset,
    savedRouteOffset,
    screenToFlowPosition,
    setDraftRouteOffset,
    zoom,
  ]);

  const snapOffset = React.useCallback(
    (offset: WorkflowEdgeRouteOffset, dragging: boolean) => {
      const { grid: currentGrid, naturalAnchor: mid } = liveRef.current;
      const settings = currentGrid?.settings;
      const bypass = currentGrid?.bypassSnap ?? false;
      if (!settings || !shouldSnapPosition(settings, { dragging, bypass })) {
        return offset;
      }
      const cellSize = settings.cellSize;
      const { width, height } = edgeSelectorBlockSize(cellSize);
      return snapEdgeSelectorRouteOffset(mid, offset, width, height, cellSize);
    },
    [],
  );

  return React.useMemo<EdgeSelectorBendHandlers>(
    () => ({
      onClick: (event) => event.stopPropagation(),
      onDoubleClick: (event) => {
        event.preventDefault();
        event.stopPropagation();
        liveRef.current.onRouteOffsetChange?.(
          snapOffset({ x: 0, y: 0 }, false),
        );
      },
      onKeyDown: (event) => {
        const {
          zoom: currentZoom,
          savedRouteOffset: saved,
          onRouteOffsetChange: commit,
          grid: currentGrid,
        } = liveRef.current;
        const settings = currentGrid?.settings;
        const bypass = currentGrid?.bypassSnap ?? false;
        const snapping = Boolean(
          settings && shouldSnapPosition(settings, { dragging: false, bypass }),
        );
        const pitch = snapping
          ? edgeSelectorSnapPitch(settings!.cellSize)
          : (event.shiftKey ? 24 : 8) / Math.max(currentZoom, 0.01);
        const step = snapping ? (event.shiftKey ? pitch * 2 : pitch) : pitch;
        let nextOffset: WorkflowEdgeRouteOffset | null = null;
        if (event.key === "Home") {
          nextOffset = { x: 0, y: 0 };
        } else if (event.key === "ArrowLeft") {
          nextOffset = { x: saved.x - step, y: saved.y };
        } else if (event.key === "ArrowRight") {
          nextOffset = { x: saved.x + step, y: saved.y };
        } else if (event.key === "ArrowUp") {
          nextOffset = { x: saved.x, y: saved.y - step };
        } else if (event.key === "ArrowDown") {
          nextOffset = { x: saved.x, y: saved.y + step };
        }
        if (!nextOffset) return;
        event.preventDefault();
        event.stopPropagation();
        commit?.(snapOffset(nextOffset, false));
      },
      onPointerDown: (event) => {
        const {
          onRouteOffsetChange: commit,
          screenToFlowPosition: toFlow,
          anchor: currentAnchor,
          routeOffset: currentOffset,
          setDraftRouteOffset: setDraft,
        } = liveRef.current;
        if (event.button !== 0 || !commit) return;
        event.preventDefault();
        event.stopPropagation();
        const pointer = toFlow({
          x: event.clientX,
          y: event.clientY,
        });
        // Start from the resolved (possibly lattice-snapped) offset so the
        // chip does not jump when drag begins.
        const startOffset = snapOffset(currentOffset, false);
        event.currentTarget.setPointerCapture(event.pointerId);
        dragRef.current = {
          pointerId: event.pointerId,
          grabOffset: {
            x: pointer.x - currentAnchor.x,
            y: pointer.y - currentAnchor.y,
          },
          latestOffset: startOffset,
        };
        setDraft(startOffset);
      },
      onPointerMove: (event) => {
        const drag = dragRef.current;
        if (!drag || drag.pointerId !== event.pointerId) return;
        event.preventDefault();
        event.stopPropagation();
        const {
          screenToFlowPosition: toFlow,
          anchor: currentAnchor,
          routeOffset: currentOffset,
          setDraftRouteOffset: setDraft,
        } = liveRef.current;
        const pointer = toFlow({
          x: event.clientX,
          y: event.clientY,
        });
        const nextOffset = {
          x:
            pointer.x - drag.grabOffset.x - (currentAnchor.x - currentOffset.x),
          y:
            pointer.y - drag.grabOffset.y - (currentAnchor.y - currentOffset.y),
        };
        const snapped = snapOffset(nextOffset, true);
        drag.latestOffset = snapped;
        setDraft(snapped);
      },
      onPointerUp: (event) => {
        const drag = dragRef.current;
        if (!drag || drag.pointerId !== event.pointerId) return;
        event.preventDefault();
        event.stopPropagation();
        dragRef.current = null;
        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
          event.currentTarget.releasePointerCapture(event.pointerId);
        }
        liveRef.current.onRouteOffsetChange?.(
          snapOffset(drag.latestOffset, false),
        );
        liveRef.current.setDraftRouteOffset(null);
      },
      onPointerCancel: (event) => {
        const drag = dragRef.current;
        if (!drag || drag.pointerId !== event.pointerId) return;
        event.stopPropagation();
        dragRef.current = null;
        liveRef.current.setDraftRouteOffset(null);
      },
      onLostPointerCapture: (event) => {
        const drag = dragRef.current;
        if (!drag || drag.pointerId !== event.pointerId) return;
        dragRef.current = null;
        liveRef.current.setDraftRouteOffset(null);
      },
    }),
    [snapOffset],
  );
}

export function useResolvedEdgeRouteOffset(
  naturalAnchor: Point,
  rawOffset: WorkflowEdgeRouteOffset,
  dragging: boolean,
  sourceNodeId: string,
  targetNodeId: string,
): WorkflowEdgeRouteOffset {
  const endpointDragging = useStore(
    React.useCallback(
      (state) =>
        state.nodeLookup.get(sourceNodeId)?.dragging === true ||
        state.nodeLookup.get(targetNodeId)?.dragging === true,
      [sourceNodeId, targetNodeId],
    ),
  );
  const grid = useOptionalCanvasGridSettings();
  const settings = grid?.settings;
  const bypass = grid?.bypassSnap ?? false;
  if (
    !settings ||
    !shouldSnapPosition(settings, {
      dragging: dragging || endpointDragging,
      bypass,
    })
  ) {
    return rawOffset;
  }
  const cellSize = settings.cellSize ?? GRID_CELL_SIZE_DEFAULT;
  const { width, height } = edgeSelectorBlockSize(cellSize);
  return snapEdgeSelectorRouteOffset(
    naturalAnchor,
    rawOffset,
    width,
    height,
    cellSize,
  );
}
