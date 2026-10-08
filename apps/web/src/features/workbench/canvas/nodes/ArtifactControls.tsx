import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { ArrowUpDown, Download, Trash2 } from "lucide-react";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { ARTIFACT_CARD_OUTPUT_HANDLE } from "../artifact-connections";
import { ARTIFACT_VIEWER_INPUT_HANDLE } from "../artifact-viewer";
import { canvasCardRail } from "./CanvasCardLayout";
import { NodeMenu, type NodeMenuItem } from "./NodeMenu";
import { PortBall, revealDelay, revealStyles } from "./PortBall";

/** @deprecated Prefer `canvasCardRail` from `CanvasCardLayout`. */
export const artifactRail = canvasCardRail;

const s = stylex.create({
  textButton: {
    display: "inline-flex",
    alignItems: "center",
    height: "22px",
    padding: "0 8px",
    borderWidth: 0,
    borderRadius: tokens.radiusSm,
    color: { default: tokens.colorText, ":disabled": tokens.colorTextDisabled },
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    fontSize: tokens.fontSizeXs,
    fontWeight: 500,
    cursor: { default: "pointer", ":disabled": "default" },
    ":focus-visible": { outline: `2px solid ${tokens.colorAccent}` },
  },
  toolbar: {
    position: "absolute",
    bottom: "calc(100% + 8px)",
    left: 0,
    display: "flex",
    alignItems: "center",
    gap: "2px",
    padding: "2px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorSurface,
    boxShadow: tokens.shadowNode,
    whiteSpace: "nowrap",
    // Rises into place as the card is picked up (keyframes in globals.css).
    animationName: "grafy-node-detail-in",
    animationDuration: {
      default: "180ms",
      "@media (prefers-reduced-motion: reduce)": "0s",
    },
    animationTimingFunction: "cubic-bezier(0.22, 1, 0.36, 1)",
    animationFillMode: "both",
  },
});

export function ArtifactLeftRail({
  nodeId,
  color,
  sequence,
  isConnectable,
}: {
  nodeId: string;
  color: string;
  sequence: boolean;
  isConnectable: boolean;
}) {
  return (
    <div
      data-artifact-rail="left"
      {...stylex.props(canvasCardRail.rail, canvasCardRail.left)}
    >
      <PortBall
        nodeId={nodeId}
        handleId={ARTIFACT_VIEWER_INPUT_HANDLE}
        side="input"
        color={color}
        sequence={sequence}
        isConnectable={isConnectable}
        ariaLabel="Input port Artifact, accepts any artifact"
        title="Connect a producer output"
        tip={{
          name: "Artifact",
          type: "Any artifact",
          hint: "Connect a producer output",
        }}
        slotProps={{ "data-artifact-port-side": "input" }}
      />
    </div>
  );
}

export function ArtifactRightRail({
  nodeId,
  contract,
  title,
  detail,
  artifactId,
  originalUrl,
  color,
  sequence,
  hasArtifacts,
  isConnectable,
  showActions,
  onOverlayChange,
  editableSequence,
  onRearrange,
  onRemove,
}: {
  nodeId: string;
  contract: string;
  title: string;
  detail: string;
  artifactId?: string;
  originalUrl?: string;
  color: string;
  sequence: boolean;
  hasArtifacts: boolean;
  isConnectable: boolean;
  showActions: boolean;
  onOverlayChange: (open: boolean) => void;
  editableSequence: boolean;
  onRearrange: () => void;
  onRemove?: () => void;
}) {
  const actions = stylex.props(
    canvasCardRail.actions,
    revealStyles(showActions, "output"),
  );
  const items: NodeMenuItem[] = [
    ...(editableSequence
      ? [
          {
            id: "reorder",
            label: "Reorder items",
            icon: <ArrowUpDown size={13} />,
            onClick: onRearrange,
          },
        ]
      : []),
    {
      id: "open-original",
      label: "Open original",
      icon: <Download size={13} />,
      disabled: !originalUrl,
      onClick: () => {
        if (originalUrl) {
          const _ = window.open(originalUrl, "_blank", "noopener,noreferrer");
        }
      },
    },
    {
      id: "remove",
      label: "Remove from canvas",
      icon: <Trash2 size={13} />,
      danger: true,
      disabled: !isConnectable,
      onClick: onRemove,
    },
  ];
  return (
    <div
      data-artifact-rail="right"
      {...stylex.props(canvasCardRail.rail, canvasCardRail.right)}
    >
      <div
        data-artifact-chrome={showActions ? "on" : "off"}
        {...actions}
        className={`nodrag nopan ${actions.className ?? ""}`}
        style={revealDelay(0)}
      >
        <NodeMenu
          label={`Actions for ${contract}`}
          title="Artifact info and actions"
          info={{ title, lines: [contract, detail], mono: artifactId }}
          items={items}
          onOpenChange={onOverlayChange}
        />
      </div>
      <div {...stylex.props(canvasCardRail.output)}>
        <PortBall
          nodeId={nodeId}
          handleId={ARTIFACT_CARD_OUTPUT_HANDLE}
          side="output"
          color={color}
          sequence={sequence}
          isConnectable={isConnectable && hasArtifacts}
          idle={!hasArtifacts}
          order={1}
          ariaLabel={`Connect ${contract} to a node input`}
          title="Connect to a compatible input"
          tip={{
            name: contract,
            type: sequence ? `Sequence<${contract}>` : contract,
            hint: "Connect to a compatible input",
          }}
          slotProps={{ "data-artifact-port-side": "output" }}
        />
      </div>
    </div>
  );
}

export function ArtifactSequenceBar({
  onRearrange,
  onUngroup,
  ungroupDisabledReason,
}: {
  onRearrange: () => void;
  onUngroup?: () => void;
  ungroupDisabledReason?: string | null;
}) {
  const textButton = stylex.props(s.textButton);
  const toolbar = stylex.props(s.toolbar);
  return (
    <div
      aria-label="Sequence actions"
      {...toolbar}
      className={`nodrag nopan ${toolbar.className ?? ""}`}
    >
      <button
        type="button"
        {...textButton}
        disabled={!onUngroup || Boolean(ungroupDisabledReason)}
        title={ungroupDisabledReason ?? "Restore individual artifacts"}
        onClick={onUngroup}
      >
        Ungroup
      </button>
      <button type="button" {...textButton} onClick={onRearrange}>
        Rearrange
      </button>
    </div>
  );
}
