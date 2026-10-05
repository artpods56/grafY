"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { ArrowDown, ArrowUp, GripVertical, Plus, Trash2 } from "lucide-react";

import type { Port } from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";

import { CanvasPortBall, nodeChrome } from "../CanvasNodeChrome";
import { encodeHandleId } from "../../handles";
import { inputPlugsForPort } from "../../input-plugs";
import { artifactTypeColor } from "../../nodes.css";
import {
  acceptedPortShapes,
  portMetaForPort,
  resolvedPortArtifactType,
  type WorkflowInputPlug,
  type WorkflowNodeData,
} from "../../types";
import { PortTypePopover } from "../type-inspector";

import {
  OptionalConnectionToggle,
  nodeInteractionProps,
  portBallTypeProps,
  useOptionalInputConnection,
} from "./ports";
import { sharedStyles } from "./styles";

const s = stylex.create({
  plugGroup: {
    display: "grid",
    gap: "5px",
    paddingBottom: "4px",
  },
  plugPortHeader: {
    minHeight: "24px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "8px",
    paddingInline: "10px",
  },
  // Reads like any other port name; the plug balls carry the type colour.
  plugPortTitle: {
    display: "flex",
    minWidth: 0,
    alignItems: "center",
    gap: "4px",
    padding: 0,
    overflow: "hidden",
    borderWidth: 0,
    backgroundColor: "transparent",
    color: { default: tokens.colorMuted, ":hover": tokens.colorText },
    cursor: "pointer",
    fontSize: tokens.fontSizeXs,
    fontWeight: 500,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  plugPortRule: {
    flexShrink: 0,
    color: tokens.colorSubtle,
    fontSize: "10px",
  },
  // Rows sit 8px in from the plate; their balls hang that much further out.
  plugList: {
    display: "grid",
    gap: "4px",
    paddingInline: "8px",
    ["--port-inset" as string]: "8px",
  },
  plugRow: {
    position: "relative",
    minWidth: 0,
    minHeight: "38px",
    display: "grid",
    gridTemplateColumns: "20px 20px minmax(0, 1fr) auto",
    alignItems: "center",
    gap: "4px",
    padding: "3px 4px 3px 6px",
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorSurfaceMuted,
  },
  plugRowDragging: {
    backgroundColor: tokens.colorAccentSoft,
    boxShadow: `inset 0 0 0 1px ${tokens.colorAccentBorder}`,
  },
  plugGrip: {
    width: "20px",
    height: "26px",
    display: "grid",
    placeItems: "center",
    padding: 0,
    borderWidth: 0,
    borderRadius: "5px",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: tokens.colorSubtle,
    cursor: "grab",
    touchAction: "none",
  },
  plugIndex: {
    color: tokens.colorSubtle,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "10px",
    textAlign: "center",
  },
  plugCopy: {
    minWidth: 0,
    display: "grid",
    gap: "1px",
  },
  plugMeta: {
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontSize: "10px",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  plugActions: { display: "flex", alignItems: "center", gap: "1px" },
  plugAction: {
    width: "18px",
    height: "20px",
    display: "grid",
    placeItems: "center",
    padding: 0,
    borderWidth: 0,
    borderRadius: "5px",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: { default: tokens.colorSubtle, ":hover": tokens.colorText },
    cursor: "pointer",
  },
  plugActionDisabled: {
    color: tokens.colorTextDisabled,
    cursor: "default",
    opacity: 0.45,
  },
  plugRemove: {
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorDangerHover,
    },
    color: { default: tokens.colorSubtle, ":hover": tokens.colorDanger },
  },
  addPlug: {
    minHeight: "26px",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "5px",
    marginInline: "8px",
    paddingInline: "8px",
    borderWidth: 0,
    borderRadius: tokens.radiusMd,
    backgroundColor: {
      default: tokens.colorSurfaceMuted,
      ":hover": tokens.colorHoverStrong,
    },
    color: tokens.colorMuted,
    cursor: "pointer",
    fontSize: tokens.fontSizeXs,
    fontWeight: 500,
  },
});

function InstancePlugRow({
  id,
  data,
  port,
  plug,
  index,
  plugCount,
  visibleName,
  acceptedShapeLabel,
  color,
  draggedPlugId,
  draggedPlugIdRef,
  lastPointerTargetRef,
  setDraggedPlugId,
  finishPointerDrag,
  typeLocked,
}: {
  id: string;
  data: WorkflowNodeData;
  port: Port;
  plug: WorkflowInputPlug;
  index: number;
  plugCount: number;
  visibleName: string;
  acceptedShapeLabel: string;
  color: string;
  draggedPlugId: string | null;
  draggedPlugIdRef: React.MutableRefObject<string | null>;
  lastPointerTargetRef: React.MutableRefObject<string | null>;
  setDraggedPlugId: React.Dispatch<React.SetStateAction<string | null>>;
  finishPointerDrag: (event: React.PointerEvent<HTMLButtonElement>) => void;
  typeLocked: boolean;
}) {
  const connection = useOptionalInputConnection(id, port, plug.id);
  const binding = data.inputPlugBindings[plug.id];
  const connectionMeta = binding
    ? [
        binding.sourceShape === "many" ? "sequence" : "single",
        binding.conversionLabel ? `feed ${binding.conversionLabel}` : null,
        binding.contributionLabel,
      ]
        .filter((label): label is string => Boolean(label))
        .join(" · ")
    : `Accepts ${acceptedShapeLabel}`;
  const accessibleLabel = `${visibleName} input ${index + 1}, accepts ${acceptedShapeLabel}`;

  return (
    <div
      data-input-node-id={id}
      data-input-plug-id={plug.id}
      data-input-plug-port={port.name}
      {...stylex.props(
        s.plugRow,
        draggedPlugId === plug.id ? s.plugRowDragging : null,
      )}
    >
      <CanvasPortBall
        nodeId={id}
        handleId={encodeHandleId(
          portMetaForPort(port, port.shape, plug.id, data.artifactTypeBindings),
        )}
        side="input"
        color={color}
        sequence
        square={Boolean(binding)}
        {...portBallTypeProps({
          id,
          data,
          port,
          shape: port.shape,
          locked: typeLocked,
          name: `${visibleName} ${index + 1}`,
        })}
        ariaLabel={accessibleLabel}
        title={`${accessibleLabel}. Connect one compatible output here.`}
      />
      <button
        type="button"
        aria-label={`Drag to reorder ${visibleName} input ${index + 1}`}
        title="Drag to reorder; arrow buttons also move this input"
        {...nodeInteractionProps(stylex.props(s.plugGrip))}
        onPointerDown={(event) => {
          if (event.button !== 0) return;
          event.stopPropagation();
          event.currentTarget.setPointerCapture(event.pointerId);
          draggedPlugIdRef.current = plug.id;
          lastPointerTargetRef.current = plug.id;
          setDraggedPlugId(plug.id);
        }}
        onPointerMove={(event) => {
          const activePlugId = draggedPlugIdRef.current;
          if (!activePlugId) return;
          event.preventDefault();
          event.stopPropagation();
          const target = document
            .elementFromPoint(event.clientX, event.clientY)
            ?.closest<HTMLElement>("[data-input-plug-id]");
          const targetPlugId = target?.dataset.inputPlugId;
          if (targetPlugId === activePlugId) {
            lastPointerTargetRef.current = null;
            return;
          }
          if (
            !targetPlugId ||
            target?.dataset.inputPlugPort !== port.name ||
            targetPlugId === lastPointerTargetRef.current
          ) {
            return;
          }
          const targetIndex = inputPlugsForPort(
            data.inputPlugs,
            port.name,
          ).findIndex((candidate) => candidate.id === targetPlugId);
          if (targetIndex === -1) return;
          lastPointerTargetRef.current = targetPlugId;
          data.onReorderInputPlug?.(id, port.name, activePlugId, targetIndex);
        }}
        onPointerUp={finishPointerDrag}
        onPointerCancel={finishPointerDrag}
      >
        <GripVertical size={12} />
      </button>
      <span {...stylex.props(s.plugIndex)}>{index + 1}</span>
      {/* An input fed by an origin is marked by its own handle shape, so the
          row copy says nothing about where the value comes from. */}
      <span {...stylex.props(s.plugCopy)}>
        <span {...stylex.props(s.plugMeta)} title={connectionMeta}>
          {connectionMeta}
        </span>
      </span>
      <span {...stylex.props(s.plugActions)}>
        {connection ? (
          <OptionalConnectionToggle
            connection={connection}
            label={`${visibleName} input ${index + 1}`}
            compact
          />
        ) : null}
        <button
          type="button"
          disabled={index === 0}
          aria-label={`Move ${visibleName} input ${index + 1} up`}
          title="Move input up"
          {...nodeInteractionProps(
            stylex.props(
              s.plugAction,
              index === 0 ? s.plugActionDisabled : null,
            ),
          )}
          onClick={() =>
            data.onReorderInputPlug?.(id, port.name, plug.id, index - 1)
          }
        >
          <ArrowUp size={10} />
        </button>
        <button
          type="button"
          disabled={index === plugCount - 1}
          aria-label={`Move ${visibleName} input ${index + 1} down`}
          title="Move input down"
          {...nodeInteractionProps(
            stylex.props(
              s.plugAction,
              index === plugCount - 1 ? s.plugActionDisabled : null,
            ),
          )}
          onClick={() =>
            data.onReorderInputPlug?.(id, port.name, plug.id, index + 1)
          }
        >
          <ArrowDown size={10} />
        </button>
        <button
          type="button"
          aria-label={`Remove ${visibleName} input ${index + 1}`}
          title="Remove input and its connection"
          {...nodeInteractionProps(stylex.props(s.plugAction, s.plugRemove))}
          onClick={() => data.onRemoveInputPlug?.(id, plug.id)}
        >
          <Trash2 size={10} />
        </button>
      </span>
    </div>
  );
}

export function InstancePlugPort({
  id,
  data,
  port,
  typeLocked,
}: {
  id: string;
  data: WorkflowNodeData;
  port: Port;
  typeLocked: boolean;
}) {
  const plugs = inputPlugsForPort(data.inputPlugs, port.name);
  const [draggedPlugId, setDraggedPlugId] = React.useState<string | null>(null);
  const draggedPlugIdRef = React.useRef<string | null>(null);
  const lastPointerTargetRef = React.useRef<string | null>(null);
  const visibleName = port.title ?? port.name;
  const artifactType = resolvedPortArtifactType(
    port,
    data.artifactTypeBindings,
  );
  const color = artifactType
    ? artifactTypeColor(artifactType.id, tokens.colorAccent)
    : tokens.colorAccent;
  const acceptedShapeLabel = acceptedPortShapes(port)
    .map((shape) => (shape === "many" ? "sequence" : "single"))
    .join(" or ");

  const finishPointerDrag = (event: React.PointerEvent<HTMLButtonElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    draggedPlugIdRef.current = null;
    lastPointerTargetRef.current = null;
    setDraggedPlugId(null);
  };

  return (
    <section
      {...stylex.props(s.plugGroup)}
      aria-label={`${visibleName} inputs`}
    >
      <div {...stylex.props(s.plugPortHeader)}>
        <PortTypePopover
          port={port}
          shape={port.shape}
          artifactTypeBindings={data.artifactTypeBindings}
        >
          <button
            type="button"
            aria-label={`Inspect ${visibleName} type`}
            title={port.description ?? `Inspect ${visibleName} type`}
            {...nodeInteractionProps(stylex.props(s.plugPortTitle))}
          >
            <span {...stylex.props(nodeChrome.tabLabel)}>{visibleName}</span>
            {port.required ? (
              <span {...stylex.props(sharedStyles.required)}>*</span>
            ) : null}
          </button>
        </PortTypePopover>
        <span {...stylex.props(s.plugPortRule)}>
          {acceptedShapeLabel} · plug order
        </span>
      </div>

      <div {...stylex.props(s.plugList)}>
        {plugs.map((plug, index) => (
          <InstancePlugRow
            key={plug.id}
            id={id}
            data={data}
            port={port}
            plug={plug}
            index={index}
            plugCount={plugs.length}
            visibleName={visibleName}
            acceptedShapeLabel={acceptedShapeLabel}
            color={color}
            draggedPlugId={draggedPlugId}
            draggedPlugIdRef={draggedPlugIdRef}
            lastPointerTargetRef={lastPointerTargetRef}
            setDraggedPlugId={setDraggedPlugId}
            finishPointerDrag={finishPointerDrag}
            typeLocked={typeLocked}
          />
        ))}
      </div>
      <button
        type="button"
        {...nodeInteractionProps(stylex.props(s.addPlug))}
        onClick={() => data.onAddInputPlug?.(id, port.name)}
      >
        <Plus size={11} />
        Add input
      </button>
    </section>
  );
}
