import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Menu } from "@base-ui/react/menu";
import { Popover } from "@base-ui/react/popover";
import { Handle, Position } from "@xyflow/react";
import { Download, Info, MoreHorizontal, Trash2 } from "lucide-react";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { overlay } from "@/lib/stylex/overlay.stylex";
import { ARTIFACT_CARD_OUTPUT_HANDLE } from "../artifact-connections";
import { ARTIFACT_VIEWER_INPUT_HANDLE } from "../artifact-viewer";
import { handleStyle } from "../handle-style";

/**
 * Hit target of a port, and the rail width on a card that stacks its action
 * buttons in one column. Every mark centres on the rail, so the two rails
 * mirror each other and the actions cannot drift off the port centreline.
 */
export const ARTIFACT_RAIL_PORT = 30;
/**
 * Rail width when the two action buttons sit side by side. A file card body is
 * a short row, so it has no room for the stacked pair above the output port.
 */
export const ARTIFACT_RAIL_ACTIONS = 48;
/** Gap between the card and the rail, so the marks sit beside it. */
export const ARTIFACT_RAIL_GAP = 8;

const s = stylex.create({
  rail: {
    display: "flex",
    minWidth: 0,
    overflow: "hidden",
  },
  left: {
    gridColumn: 1,
    gridRow: 2,
    justifyContent: "center",
    alignItems: "flex-start",
  },
  right: {
    gridColumn: 3,
    gridRow: 2,
    position: "relative",
    flexDirection: "column",
    justifyContent: "flex-start",
    alignItems: "center",
  },
  concealed: {
    opacity: 0,
    visibility: "hidden",
    pointerEvents: "none",
  },
  port: {
    position: "relative",
    width: "30px",
    height: "30px",
    flexShrink: 0,
  },
  output: { marginTop: "auto" },
  // Out of the rail's flow: only the output port sets the rail height, so a
  // short file card still pins that port to the body's bottom edge. Centred on
  // the rail, which is where the port sits too.
  actions: {
    position: "absolute",
    top: 0,
    left: "50%",
    transform: "translateX(-50%)",
    display: "flex",
    flexDirection: "row",
    alignItems: "center",
    height: "30px",
    gap: "2px",
  },
  actionsStacked: {
    flexDirection: "column",
    height: "auto",
    // Half the difference between the 30px rail slot and a 22px button, so the
    // first button still sits level with the input port.
    paddingTop: "4px",
  },
  button: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    width: "22px",
    minWidth: "22px",
    height: "22px",
    padding: 0,
    borderWidth: 0,
    borderRadius: tokens.radiusSm,
    color: tokens.colorText,
    backgroundColor: "transparent",
    cursor: "pointer",
    ":hover": { backgroundColor: tokens.colorSurfaceRaised },
    ":focus-visible": { outline: `2px solid ${tokens.colorAccent}` },
    ":disabled": { opacity: 0.45, cursor: "default" },
  },
  textButton: { width: "auto", padding: "0 8px" },
  popup: {
    display: "grid",
    gap: "6px",
    padding: "12px",
    minWidth: "180px",
    maxWidth: "min(280px, calc(100vw - 24px))",
    fontSize: tokens.fontSizeXs,
    overflowWrap: "anywhere",
    zIndex: 60,
  },
  detail: { color: tokens.colorMuted },
  toolbar: {
    position: "absolute",
    bottom: "calc(100% + 10px)",
    left: 0,
    display: "flex",
    alignItems: "center",
    gap: "4px",
    padding: "3px",
    border: `1px solid ${tokens.colorBorder}`,
    borderRadius: tokens.radiusSm,
    backgroundColor: tokens.colorSurface,
    boxShadow: tokens.shadowNode,
    whiteSpace: "nowrap",
  },
});

function portMark(
  color: string,
  sequence: boolean,
  dimmed: boolean,
): React.CSSProperties {
  return {
    ...handleStyle(0, color, sequence),
    position: "absolute",
    top: 0,
    left: 0,
    transform: "none",
    opacity: dimmed ? 0.3 : 1,
  };
}

export function ArtifactLeftRail({
  color,
  sequence,
  showPorts,
  isConnectable,
}: {
  color: string;
  sequence: boolean;
  showPorts: boolean;
  isConnectable: boolean;
}) {
  return (
    <div data-artifact-rail="left" {...stylex.props(s.rail, s.left)}>
      <div
        data-artifact-port-side="input"
        data-artifact-ports={showPorts ? "on" : "off"}
        {...stylex.props(s.port, showPorts ? null : s.concealed)}
      >
        <Handle
          id={ARTIFACT_VIEWER_INPUT_HANDLE}
          type="target"
          position={Position.Left}
          isConnectable={isConnectable}
          aria-disabled={!isConnectable}
          aria-label="Input port Artifact, accepts any artifact"
          title="Connect a producer output"
          style={portMark(color, sequence, false)}
        />
      </div>
    </div>
  );
}

export function ArtifactRightRail({
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
  showPorts,
  stackActions,
  onOverlayChange,
  editableSequence,
  onRearrange,
  onRemove,
}: {
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
  showPorts: boolean;
  stackActions: boolean;
  onOverlayChange: (open: boolean) => void;
  editableSequence: boolean;
  onRearrange: () => void;
  onRemove?: () => void;
}) {
  const overlays = React.useRef({ info: false, menu: false });
  const reportOverlay = (which: "info" | "menu", open: boolean) => {
    overlays.current[which] = open;
    onOverlayChange(overlays.current.info || overlays.current.menu);
  };
  const button = stylex.props(s.button);
  const actions = stylex.props(
    s.actions,
    stackActions ? s.actionsStacked : null,
    showActions ? null : s.concealed,
  );
  const menu = stylex.props(overlay.popup);
  const popup = stylex.props(overlay.popup, s.popup);
  return (
    <div data-artifact-rail="right" {...stylex.props(s.rail, s.right)}>
      <div
        data-artifact-chrome={showActions ? "on" : "off"}
        {...actions}
        className={`nodrag nopan ${actions.className ?? ""}`}
      >
        <Popover.Root onOpenChange={(open) => reportOverlay("info", open)}>
          <Popover.Trigger
            {...button}
            aria-label={`Inspect ${contract} artifact`}
            title="Artifact info"
          >
            <Info size={14} />
          </Popover.Trigger>
          <Popover.Portal>
            <Popover.Positioner side="bottom" align="end" sideOffset={6}>
              <Popover.Popup
                {...popup}
                className={`nodrag nopan nowheel ${popup.className ?? ""}`}
              >
                <strong>{title}</strong>
                <span {...stylex.props(s.detail)}>{contract}</span>
                <span {...stylex.props(s.detail)}>{detail}</span>
                {artifactId ? (
                  <span {...stylex.props(s.detail)}>{artifactId}</span>
                ) : null}
              </Popover.Popup>
            </Popover.Positioner>
          </Popover.Portal>
        </Popover.Root>
        <Menu.Root onOpenChange={(open) => reportOverlay("menu", open)}>
          <Menu.Trigger
            {...button}
            aria-label={`Actions for ${contract}`}
            title="Artifact actions"
          >
            <MoreHorizontal size={14} />
          </Menu.Trigger>
          <Menu.Portal>
            <Menu.Positioner side="bottom" align="end" sideOffset={6}>
              <Menu.Popup
                {...menu}
                className={`nodrag nopan nowheel ${menu.className ?? ""}`}
              >
                {editableSequence ? (
                  <Menu.Item
                    onClick={onRearrange}
                    {...stylex.props(overlay.item)}
                  >
                    Reorder items
                  </Menu.Item>
                ) : null}
                <Menu.Item
                  disabled={!originalUrl}
                  onClick={() => {
                    if (originalUrl) {
                      const _ = window.open(
                        originalUrl,
                        "_blank",
                        "noopener,noreferrer",
                      );
                    }
                  }}
                  {...stylex.props(overlay.item)}
                >
                  <Download size={13} /> Open original
                </Menu.Item>
                <Menu.Item
                  disabled={!isConnectable}
                  onClick={onRemove}
                  {...stylex.props(overlay.item)}
                >
                  <Trash2 size={13} /> Remove from canvas
                </Menu.Item>
              </Menu.Popup>
            </Menu.Positioner>
          </Menu.Portal>
        </Menu.Root>
      </div>
      <div
        data-artifact-port-side="output"
        data-artifact-ports={showPorts ? "on" : "off"}
        {...stylex.props(s.port, s.output, showPorts ? null : s.concealed)}
      >
        <Handle
          id={ARTIFACT_CARD_OUTPUT_HANDLE}
          type="source"
          position={Position.Right}
          isConnectable={isConnectable && hasArtifacts}
          aria-disabled={!isConnectable || !hasArtifacts}
          aria-label={`Connect ${contract} to a node input`}
          title="Connect to a compatible input"
          style={portMark(color, sequence, !hasArtifacts)}
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
  const textButton = stylex.props(s.button, s.textButton);
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
