"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Popover } from "@base-ui/react/popover";
import { Handle, Position, useEdges } from "@xyflow/react";
import { Power } from "lucide-react";

import type { Port } from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";

import { nodeChrome } from "../CanvasNodeChrome";
import { useHandleIsDocked } from "../../edges/useDockedConnection";
import { dockedHandleStyle, handleStyle } from "../../handle-style";
import { decodeHandleId, encodeHandleId } from "../../handles";
import { artifactTypeColor } from "../../nodes.css";
import {
  compatibilityHandleId,
  effectivePortShape,
  portHasInstancePlugs,
  portMetaForPort,
  resolvedPortArtifactType,
  type WorkflowEdge,
  type WorkflowNodeData,
} from "../../types";
import { useOptionalCanvasGridSettings } from "../../canvas-grid-settings";
import {
  GRID_CELL_SIZE_DEFAULT,
  PORT_RAIL_ROW_HEIGHT_CELLS,
  lengthFromSpan,
} from "../../grid-layout";
import { PortTypePopover } from "../type-inspector";

import { sharedStyles } from "./styles";

const s = stylex.create({
  compatibilityPort: {
    backgroundColor: {
      default: tokens.colorSurfaceSunken,
      ":hover": tokens.colorSurfaceSunken,
    },
    color: tokens.colorTextDisabled,
  },
  tabWithToggle: {
    paddingInlineEnd: "5px",
  },
  tabTrigger: {
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    gap: "7px",
    height: "100%",
    padding: 0,
    borderWidth: 0,
    backgroundColor: "transparent",
    color: "inherit",
    cursor: "pointer",
    font: "inherit",
  },
  tabDisabled: {
    color: tokens.colorTextDisabled,
    backgroundColor: {
      default: tokens.colorSurfaceSunken,
      ":hover": tokens.colorSurfaceSunken,
    },
  },
  connectionToggle: {
    width: "18px",
    height: "18px",
    flexShrink: 0,
    display: "grid",
    placeItems: "center",
    padding: 0,
    borderWidth: 0,
    borderRadius: "9999px",
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorHoverStrong,
    },
    color: tokens.colorMuted,
    cursor: "pointer",
  },
  connectionToggleEnabled: {
    color: tokens.colorAccent,
    backgroundColor: {
      default: tokens.colorAccentSoft,
      ":hover": tokens.colorAccentSoft,
    },
  },
  connectionToggleDisabled: {
    color: tokens.colorTextDisabled,
    backgroundColor: {
      default: tokens.colorSurface,
      ":hover": tokens.colorHover,
    },
  },
  plugConnectionToggle: {
    width: "18px",
    height: "20px",
    borderRadius: "5px",
  },
});

export function nodeInteractionProps(props: ReturnType<typeof stylex.props>) {
  return {
    ...props,
    className: `nodrag nowheel${props.className ? ` ${props.className}` : ""}`,
  };
}

export function useOptionalInputConnection(
  nodeId: string,
  port: Port,
  plugId?: string,
) {
  const edges = useEdges<WorkflowEdge>();
  return React.useMemo(() => {
    if (port.direction !== "input") return null;
    const edge = edges.find((candidate) => {
      if (candidate.target !== nodeId) return false;
      const handle = decodeHandleId(candidate.targetHandle);
      if (!handle || handle.portName !== port.name) return false;
      if (plugId !== undefined) return handle.plugId === plugId;
      return handle.plugId === undefined;
    });
    const onUpdate = edge?.data?.onUpdate;
    if (!edge || !onUpdate) return null;
    const enabled = edge.data?.enabled !== false;
    // Only optional ports can be disabled; still allow re-enabling a
    // connection that was left disabled against a required input.
    if (port.required && enabled) return null;
    return {
      enabled,
      toggle: () => onUpdate(edge.id, { enabled: !enabled }),
    };
  }, [edges, nodeId, plugId, port.direction, port.name, port.required]);
}

export function OptionalConnectionToggle({
  connection,
  label,
  compact = false,
}: {
  connection: { enabled: boolean; toggle: () => void };
  label: string;
  compact?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={connection.enabled}
      aria-label={`${label} connection enabled`}
      title={connection.enabled ? "Disable connection" : "Enable connection"}
      {...nodeInteractionProps(
        stylex.props(
          s.connectionToggle,
          connection.enabled
            ? s.connectionToggleEnabled
            : s.connectionToggleDisabled,
          compact ? s.plugConnectionToggle : null,
        ),
      )}
      onClick={(event) => {
        event.stopPropagation();
        connection.toggle();
      }}
    >
      <Power size={compact ? 10 : 11} aria-hidden="true" />
    </button>
  );
}

/**
 * Shared port rail: one lattice-tall row per index, input on the left and
 * output on the right so neighboring nodes can Lego-join on the same Y.
 */
export function PortRail({
  id,
  data,
  inputPorts,
  outputPorts,
}: {
  id: string;
  data: WorkflowNodeData;
  inputPorts: readonly Port[];
  outputPorts: readonly Port[];
}) {
  const grid = useOptionalCanvasGridSettings();
  const cellSize = grid?.settings.cellSize ?? GRID_CELL_SIZE_DEFAULT;
  const rowHeight = lengthFromSpan(PORT_RAIL_ROW_HEIGHT_CELLS, cellSize);
  const rowCount = Math.max(inputPorts.length, outputPorts.length);
  if (rowCount === 0) return null;

  return (
    <div data-testid="port-rail" {...stylex.props(nodeChrome.portRail)}>
      {Array.from({ length: rowCount }, (_, index) => {
        const input = inputPorts[index];
        const output = outputPorts[index];
        return (
          <div
            key={`port-rail-row-${index}`}
            data-testid="port-rail-row"
            style={{ height: rowHeight }}
            {...stylex.props(nodeChrome.portRailRow)}
          >
            <div {...stylex.props(nodeChrome.portRailSlot)}>
              {input ? (
                <PortTab
                  id={id}
                  data={data}
                  port={input}
                  shape={effectivePortShape(data, input)}
                />
              ) : null}
            </div>
            <div
              {...stylex.props(
                nodeChrome.portRailSlot,
                nodeChrome.portRailSlotOut,
              )}
            >
              {output ? (
                <PortTab
                  id={id}
                  data={data}
                  port={output}
                  shape={effectivePortShape(data, output)}
                />
              ) : null}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function PortTab({
  id,
  data,
  port,
  shape,
}: {
  id: string;
  data: WorkflowNodeData;
  port: Port;
  shape: Port["shape"];
}) {
  const input = port.direction === "input";
  const connection = useOptionalInputConnection(id, port);
  const visibleName = port.title ?? port.name;
  const artifactType = resolvedPortArtifactType(
    port,
    data.artifactTypeBindings,
  );
  const color = artifactType
    ? artifactTypeColor(artifactType.id, tokens.colorAccent)
    : tokens.colorAccent;
  const artifactContract = artifactType
    ? `${artifactType.id}@${artifactType.schema_version}`
    : "Any artifact";
  const effectiveContract =
    shape === "many" ? `list[${artifactContract}]` : artifactContract;
  const accessibleLabel = input
    ? `Input port ${visibleName}, accepts ${effectiveContract}${port.required ? ", required" : ""}`
    : `Output port ${visibleName}, provides ${effectiveContract}`;
  const connectionDisabled = Boolean(connection && !connection.enabled);
  const handleId = encodeHandleId(
    portMetaForPort(
      port,
      input ? port.shape : shape,
      undefined,
      data.artifactTypeBindings,
    ),
  );
  const docked = useHandleIsDocked(id, handleId);
  // A drawer drop lands on the row itself, so only a plain input port row
  // publishes the identity a drop reads. A port that takes plugs publishes it
  // on each plug row instead.
  const artifactDropRow = input && !portHasInstancePlugs(port);

  return (
    <div
      data-docked-port={docked ? "true" : undefined}
      data-input-node-id={artifactDropRow ? id : undefined}
      data-input-port-name={artifactDropRow ? port.name : undefined}
      {...stylex.props(nodeChrome.tabRow, input ? null : nodeChrome.tabRowOut)}
    >
      <div
        {...stylex.props(
          nodeChrome.tab,
          input ? nodeChrome.tabIn : nodeChrome.tabOut,
          connection ? s.tabWithToggle : null,
          connectionDisabled ? s.tabDisabled : null,
          docked ? nodeChrome.tabDocked : null,
        )}
      >
        <PortTypePopover
          port={port}
          shape={shape}
          artifactTypeBindings={data.artifactTypeBindings}
        >
          <Popover.Trigger
            type="button"
            aria-label={`Inspect ${visibleName} type`}
            title={port.description ?? `Inspect ${visibleName} type`}
            {...nodeInteractionProps(stylex.props(s.tabTrigger))}
          >
            <span {...stylex.props(nodeChrome.tabLabel)}>{visibleName}</span>
            {input && port.required ? (
              <span
                {...stylex.props(sharedStyles.required, nodeChrome.tabShape)}
              >
                *
              </span>
            ) : null}
            {shape === "many" ? (
              <span {...stylex.props(nodeChrome.tabShape)}>· many</span>
            ) : null}
          </Popover.Trigger>
        </PortTypePopover>
        {connection ? (
          <OptionalConnectionToggle
            connection={connection}
            label={visibleName}
          />
        ) : null}
      </div>
      <Handle
        type={input ? "target" : "source"}
        position={input ? Position.Left : Position.Right}
        id={handleId}
        aria-hidden={docked}
        aria-label={accessibleLabel}
        title={
          input
            ? `${accessibleLabel}. Connect a compatible output here.${port.description ? ` ${port.description}` : ""}`
            : `${accessibleLabel}. Drag to a compatible input. If fields are available, you can choose what arrives after connecting.${port.description ? ` ${port.description}` : ""}`
        }
        style={
          docked
            ? dockedHandleStyle("50%")
            : handleStyle("50%", color, shape === "many")
        }
      />
    </div>
  );
}

export function InstanceInputConnectionToggle({
  nodeId,
  port,
  plugId,
  label,
}: {
  nodeId: string;
  port: Port;
  plugId: string;
  label: string;
}) {
  const connection = useOptionalInputConnection(nodeId, port, plugId);
  if (!connection) return null;
  return (
    <OptionalConnectionToggle connection={connection} label={label} compact />
  );
}

export type IncompatibleWorkflowNodeCompatibility = Exclude<
  WorkflowNodeData["compatibility"],
  { status: "supported" }
>;

function CompatibilityPort({
  direction,
  endpoint,
}: {
  direction: "input" | "output";
  endpoint: IncompatibleWorkflowNodeCompatibility["inputs"][number];
}) {
  const input = direction === "input";
  const label = endpoint.plugId
    ? `${endpoint.portName} · ${endpoint.plugId}`
    : endpoint.portName;
  return (
    <div
      {...stylex.props(nodeChrome.tabRow, input ? null : nodeChrome.tabRowOut)}
    >
      <div
        {...stylex.props(
          nodeChrome.tab,
          input ? nodeChrome.tabIn : nodeChrome.tabOut,
          s.compatibilityPort,
        )}
        title={`Historical ${direction} ${label}`}
      >
        <span {...stylex.props(nodeChrome.tabLabel)}>{label}</span>
      </div>
      <Handle
        type={input ? "target" : "source"}
        position={input ? Position.Left : Position.Right}
        id={compatibilityHandleId(direction, endpoint)}
        isConnectable={false}
        aria-label={`Unavailable ${direction} port ${label}`}
        title={`This historical ${direction} cannot accept new connections.`}
        style={{
          ...handleStyle("50%", tokens.colorMuted),
          cursor: "not-allowed",
          opacity: 0.72,
        }}
      />
    </div>
  );
}

export function CompatibilityPortRail({
  inputs,
  outputs,
}: {
  inputs: IncompatibleWorkflowNodeCompatibility["inputs"];
  outputs: IncompatibleWorkflowNodeCompatibility["outputs"];
}) {
  const grid = useOptionalCanvasGridSettings();
  const cellSize = grid?.settings.cellSize ?? GRID_CELL_SIZE_DEFAULT;
  const rowHeight = lengthFromSpan(PORT_RAIL_ROW_HEIGHT_CELLS, cellSize);
  const rowCount = Math.max(inputs.length, outputs.length);
  if (rowCount === 0) return null;

  return (
    <div data-testid="port-rail" {...stylex.props(nodeChrome.portRail)}>
      {Array.from({ length: rowCount }, (_, index) => {
        const input = inputs[index];
        const output = outputs[index];
        return (
          <div
            key={`compat-rail-row-${index}`}
            data-testid="port-rail-row"
            style={{ height: rowHeight }}
            {...stylex.props(nodeChrome.portRailRow)}
          >
            <div {...stylex.props(nodeChrome.portRailSlot)}>
              {input ? (
                <CompatibilityPort direction="input" endpoint={input} />
              ) : null}
            </div>
            <div
              {...stylex.props(
                nodeChrome.portRailSlot,
                nodeChrome.portRailSlotOut,
              )}
            >
              {output ? (
                <CompatibilityPort direction="output" endpoint={output} />
              ) : null}
            </div>
          </div>
        );
      })}
    </div>
  );
}
