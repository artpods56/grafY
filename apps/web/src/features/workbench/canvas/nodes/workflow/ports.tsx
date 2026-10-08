"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Popover } from "@base-ui/react/popover";
import { useEdges } from "@xyflow/react";
import { Power } from "lucide-react";

import type { Port } from "@/lib/api";
import { artifactTypeVariableOptions } from "@/features/workbench/model/claimed-formats";
import { tokens } from "@/lib/stylex/tokens.stylex";

import {
  CanvasCardLeftRail,
  CanvasCardRailSlot,
  CanvasCardRightRail,
  useCanvasRailRowHeight,
} from "../CanvasCardLayout";
import { useHandleIsDocked } from "../../edges/useDockedConnection";
import { decodeHandleId, encodeHandleId } from "../../handles";
import { artifactTypeColor } from "../../nodes.css";
import {
  formatArtifactTypeContract,
  formatArtifactTypeLabel,
} from "../../artifact-type-label";
import { useArtifactTypeCatalog } from "../../use-artifact-type-catalog";
import {
  compatibilityHandleId,
  effectivePortShape,
  portHasInstancePlugs,
  portMetaForPort,
  resolvedPortArtifactType,
  type WorkflowEdge,
  type WorkflowNodeData,
} from "../../types";
import { PortBall } from "../PortBall";
import { PortTypePopover } from "../type-inspector";

const s = stylex.create({
  // Keeps "Inspect … type" reachable for assistive tech and Playwright without
  // putting a label back on the plate.
  inspectHit: {
    position: "absolute",
    width: "1px",
    height: "1px",
    padding: 0,
    margin: "-1px",
    overflow: "hidden",
    clipPath: "inset(50%)",
    borderWidth: 0,
    whiteSpace: "nowrap",
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
    pointerEvents: "auto",
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
  // An optional input's switch sits on its wire, just outside the ball, so it
  // never covers the ring and the ball stays on the mid-cell line.
  railToggle: {
    position: "absolute",
    top: "50%",
    right: "calc(100% + 2px)",
    transform: "translateY(-50%)",
    zIndex: 2,
  },
  railSlot: {
    position: "relative",
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
 * Port rails: balls hang outside the plate like an artifact card's. Names stay
 * off the plate and appear on ball hover via `PortBall` tips. Inputs stack
 * from the top; outputs pin to the bottom. The card gives the plate a floor of
 * one row per slot on the taller rail (`CanvasNodeShell`'s `railRows`).
 */
export function PortRail({
  id,
  data,
  inputPorts,
  outputPorts,
  typeLocked,
}: {
  id: string;
  data: WorkflowNodeData;
  inputPorts: readonly Port[];
  outputPorts: readonly Port[];
  typeLocked: boolean;
}) {
  const rowHeight = useCanvasRailRowHeight();
  if (inputPorts.length === 0 && outputPorts.length === 0) return null;

  return (
    <>
      {inputPorts.length > 0 ? (
        <CanvasCardLeftRail testId="port-rail">
          {inputPorts.map((port, index) => (
            <CanvasCardRailSlot key={`in-${port.name}`} height={rowHeight}>
              <RailPort
                id={id}
                data={data}
                port={port}
                shape={effectivePortShape(data, port)}
                typeLocked={typeLocked}
                order={index}
              />
            </CanvasCardRailSlot>
          ))}
        </CanvasCardLeftRail>
      ) : null}
      {outputPorts.length > 0 ? (
        <CanvasCardRightRail
          testId={inputPorts.length === 0 ? "port-rail" : "port-rail-out"}
        >
          {outputPorts.map((port, index) => (
            <CanvasCardRailSlot key={`out-${port.name}`} height={rowHeight}>
              <RailPort
                id={id}
                data={data}
                port={port}
                shape={effectivePortShape(data, port)}
                typeLocked={typeLocked}
                order={index}
              />
            </CanvasCardRailSlot>
          ))}
        </CanvasCardRightRail>
      ) : null}
    </>
  );
}

function RailPort({
  id,
  data,
  port,
  shape,
  typeLocked,
  order,
}: {
  id: string;
  data: WorkflowNodeData;
  port: Port;
  shape: Port["shape"];
  typeLocked: boolean;
  order: number;
}) {
  const input = port.direction === "input";
  const connection = useOptionalInputConnection(id, port);
  const artifactTypes = useArtifactTypeCatalog();
  const [inspectOpen, setInspectOpen] = React.useState(false);
  const visibleName = port.title ?? port.name;
  const artifactType = resolvedPortArtifactType(
    port,
    data.artifactTypeBindings,
  );
  const color = artifactType
    ? artifactTypeColor(artifactType.id, tokens.colorAccent)
    : tokens.colorAccent;
  const artifactContract = artifactType
    ? formatArtifactTypeContract(artifactType, artifactTypes)
    : "Any artifact";
  const effectiveContract =
    shape === "many" ? `list[${artifactContract}]` : artifactContract;
  const accessibleLabel = input
    ? `Input port ${visibleName}, accepts ${effectiveContract}${port.required ? ", required" : ""}`
    : `Output port ${visibleName}, provides ${effectiveContract}`;
  const handleId = encodeHandleId(
    portMetaForPort(
      port,
      input ? port.shape : shape,
      undefined,
      data.artifactTypeBindings,
    ),
  );
  const docked = useHandleIsDocked(id, handleId);
  // A drawer drop lands on the slot itself, so only a plain input port
  // publishes the identity a drop reads. A port that takes plugs publishes it
  // on each plug row instead.
  const artifactDropRow = input && !portHasInstancePlugs(port);
  const typeProps = usePortBallTypeProps({
    id,
    data,
    port,
    shape,
    locked: typeLocked,
    name: visibleName,
  });
  const tip = typeProps.tip
    ? {
        ...typeProps.tip,
        hint: typeProps.tip.hint
          ? `${typeProps.tip.hint} Double-click to inspect its schema.`
          : "Double-click to inspect its schema.",
      }
    : null;

  return (
    <PortTypePopover
      port={port}
      shape={shape}
      artifactTypeBindings={data.artifactTypeBindings}
      open={inspectOpen}
      onOpenChange={setInspectOpen}
    >
      <div
        data-docked-port={docked ? "true" : undefined}
        data-input-node-id={artifactDropRow ? id : undefined}
        data-input-port-name={artifactDropRow ? port.name : undefined}
        data-port-name={port.name}
        {...stylex.props(s.railSlot)}
        onDoubleClick={(event) => {
          event.stopPropagation();
          setInspectOpen(true);
        }}
      >
        <Popover.Trigger
          type="button"
          aria-label={`Inspect ${visibleName} type`}
          title={port.description ?? `Inspect ${visibleName} type`}
          {...nodeInteractionProps(stylex.props(s.inspectHit))}
        />
        {connection ? (
          <span {...stylex.props(s.railToggle)}>
            <OptionalConnectionToggle
              connection={connection}
              label={visibleName}
            />
          </span>
        ) : null}
        <PortBall
          nodeId={id}
          handleId={handleId}
          side={input ? "input" : "output"}
          color={color}
          sequence={shape === "many"}
          docked={docked}
          order={order}
          {...typeProps}
          tip={tip}
          ariaLabel={accessibleLabel}
          title={
            input
              ? `${accessibleLabel}. Connect a compatible output here.${port.description ? ` ${port.description}` : ""}`
              : `${accessibleLabel}. Drag to a compatible input. If fields are available, you can choose what arrives after connecting.${port.description ? ` ${port.description}` : ""}`
          }
        />
      </div>
    </PortTypePopover>
  );
}

export const ANY_TYPE_LABEL = "Any type";

/**
 * What a port's ball says and does about its type. The ring carries the type
 * in its colour; a generic port still open is dashed. Hovering tells the type
 * in full; clicking a free generic port's ball picks it.
 */
export function usePortBallTypeProps({
  id,
  data,
  port,
  shape,
  locked,
  name,
}: {
  id: string;
  data: WorkflowNodeData;
  port: Port;
  shape: Port["shape"];
  locked: boolean;
  name: string;
}): Pick<React.ComponentProps<typeof PortBall>, "open" | "tip" | "typeChoice"> {
  const variable = port.artifact_type_variable ?? null;
  const artifactTypes = useArtifactTypeCatalog();
  const artifactType = resolvedPortArtifactType(
    port,
    data.artifactTypeBindings,
  );
  const open = Boolean(variable) && !artifactType;
  const inner = artifactType
    ? formatArtifactTypeLabel(artifactType, artifactTypes)
    : "any";
  const type =
    shape === "many"
      ? `Sequence<${inner}>`
      : artifactType
        ? inner
        : ANY_TYPE_LABEL;
  const options = variable
    ? artifactTypeVariableOptions(
        data.spec.operator_id,
        variable,
        data.bindableArtifactTypes ?? [],
      )
    : [];
  const picks =
    variable !== null &&
    !locked &&
    data.onBindArtifactTypeBinding !== undefined &&
    options.length > 0;
  const hint = picks
    ? open
      ? "Click to choose its type, or connect a wire to set it."
      : "Click to change its type."
    : variable && locked
      ? "Its wire set this type. Disconnect it to change the type."
      : port.direction === "input"
        ? "Connect a matching output here."
        : "Drag to a matching input.";
  return {
    open,
    tip: { name, type, hint },
    typeChoice:
      picks && variable
        ? {
            current: data.artifactTypeBindings[variable] ?? null,
            options,
            onPick: (choice) => {
              if (choice) {
                data.onBindArtifactTypeBinding?.(id, variable, choice);
              } else if (data.artifactTypeBindings[variable]) {
                data.onResetArtifactTypeBinding?.(id, variable);
              }
            },
          }
        : null,
  };
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

function CompatibilityRailPort({
  nodeId,
  direction,
  endpoint,
  order,
}: {
  nodeId: string;
  direction: "input" | "output";
  endpoint: IncompatibleWorkflowNodeCompatibility["inputs"][number];
  order: number;
}) {
  const label = endpoint.plugId
    ? `${endpoint.portName} · ${endpoint.plugId}`
    : endpoint.portName;
  return (
    <PortBall
      nodeId={nodeId}
      handleId={compatibilityHandleId(direction, endpoint)}
      side={direction}
      color={tokens.colorMuted}
      locked
      order={order}
      ariaLabel={`Unavailable ${direction} port ${label}`}
      title={`This historical ${direction} cannot accept new connections.`}
      tip={{
        name: label,
        type: "Unavailable",
        hint: "This historical port cannot accept new connections.",
      }}
    />
  );
}

export function CompatibilityPortRail({
  nodeId,
  inputs,
  outputs,
}: {
  nodeId: string;
  inputs: IncompatibleWorkflowNodeCompatibility["inputs"];
  outputs: IncompatibleWorkflowNodeCompatibility["outputs"];
}) {
  const rowHeight = useCanvasRailRowHeight();
  if (inputs.length === 0 && outputs.length === 0) return null;

  return (
    <>
      {inputs.length > 0 ? (
        <CanvasCardLeftRail testId="port-rail">
          {inputs.map((endpoint, index) => (
            <CanvasCardRailSlot
              key={`compat-in-${endpoint.portName}-${endpoint.plugId ?? ""}`}
              height={rowHeight}
            >
              <CompatibilityRailPort
                nodeId={nodeId}
                direction="input"
                endpoint={endpoint}
                order={index}
              />
            </CanvasCardRailSlot>
          ))}
        </CanvasCardLeftRail>
      ) : null}
      {outputs.length > 0 ? (
        <CanvasCardRightRail
          testId={inputs.length === 0 ? "port-rail" : "port-rail-out"}
        >
          {outputs.map((endpoint, index) => (
            <CanvasCardRailSlot
              key={`compat-out-${endpoint.portName}-${endpoint.plugId ?? ""}`}
              height={rowHeight}
            >
              <CompatibilityRailPort
                nodeId={nodeId}
                direction="output"
                endpoint={endpoint}
                order={index}
              />
            </CanvasCardRailSlot>
          ))}
        </CanvasCardRightRail>
      ) : null}
    </>
  );
}
