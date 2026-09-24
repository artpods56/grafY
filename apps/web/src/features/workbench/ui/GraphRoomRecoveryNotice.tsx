import * as stylex from "@stylexjs/stylex";
import { RefreshCw } from "lucide-react";

import { tokens } from "@/lib/stylex/tokens.stylex";
import type {
  GraphReadinessState,
  GraphRoomFailure,
  GraphRoomStatus,
  GraphRoomTerminalReason,
} from "../room";

interface GraphRoomRecoveryNoticeProps {
  readonly readiness: GraphReadinessState;
  readonly status: GraphRoomStatus;
  readonly failure: GraphRoomFailure | null;
  readonly terminalReason: GraphRoomTerminalReason | null;
  readonly onRetry: () => void;
  readonly onReload: () => void;
}

export function GraphRoomRecoveryNotice({
  readiness,
  status,
  failure,
  terminalReason,
  onRetry,
  onReload,
}: GraphRoomRecoveryNoticeProps) {
  if (readiness === "current") {
    return (
      <span
        role="status"
        aria-live="polite"
        {...stylex.props(s.visuallyHidden)}
      >
        Graph current. Graph operations are available according to your
        workspace permissions.
      </span>
    );
  }

  const incompatible = terminalReason === "protocol_incompatible";
  const exhausted = terminalReason === "reconnect_exhausted";
  const title =
    readiness === "stale" ? "Stale graph — read only" : "Graph unavailable";
  const preservation =
    readiness === "stale"
      ? "The last confirmed graph is shown. Server-accepted work is preserved; visible local changes stay on this device until reconnection confirms them."
      : "No confirmed graph is available yet.";
  const recovery = incompatible
    ? "The client and server collaboration protocols are incompatible. Reload the graph after updating either side."
    : exhausted
      ? "Automatic reconnection stopped. Retry the connection to request a fresh graph."
      : status === "connecting"
        ? "Connecting and loading the current graph."
        : "Reconnecting and loading a fresh graph before graph operations resume.";

  return (
    <section role="status" aria-live="polite" {...stylex.props(s.notice)}>
      <div {...stylex.props(s.copy)}>
        <strong {...stylex.props(s.title)}>{title}</strong>
        <span {...stylex.props(s.message)}>
          {preservation} Editing, saving, running, and Module setup are
          unavailable. {recovery}
        </span>
        {failure?.messageType ? (
          <span {...stylex.props(s.detail)}>
            Failure while receiving {failure.messageType}.
          </span>
        ) : null}
      </div>
      {incompatible ? (
        <button type="button" onClick={onReload} {...stylex.props(s.action)}>
          <RefreshCw size={14} aria-hidden="true" /> Reload graph
        </button>
      ) : exhausted ? (
        <button type="button" onClick={onRetry} {...stylex.props(s.action)}>
          <RefreshCw size={14} aria-hidden="true" /> Retry connection
        </button>
      ) : null}
    </section>
  );
}

const s = stylex.create({
  notice: {
    position: "absolute",
    zIndex: 35,
    top: "16px",
    left: "50%",
    width: "min(680px, calc(100% - 32px))",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "16px",
    padding: "12px 14px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "10px",
    backgroundColor: tokens.colorChrome,
    boxShadow: tokens.shadowNodeRaised,
    transform: "translateX(-50%)",
  },
  copy: { display: "grid", gap: "3px", minWidth: 0 },
  title: { color: tokens.colorTextEmphasis, fontSize: tokens.fontSizeSm },
  message: {
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
  detail: { color: tokens.colorSubtle, fontSize: tokens.fontSizeXs },
  action: {
    flexShrink: 0,
    display: "inline-flex",
    alignItems: "center",
    gap: "6px",
    minHeight: "34px",
    paddingInline: "10px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "7px",
    backgroundColor: { default: tokens.colorBg, ":hover": tokens.colorHover },
    color: tokens.colorTextEmphasis,
    cursor: "pointer",
    fontSize: tokens.fontSizeSm,
    fontWeight: 700,
  },
  visuallyHidden: {
    position: "absolute",
    width: "1px",
    height: "1px",
    margin: "-1px",
    padding: 0,
    overflow: "hidden",
    borderWidth: 0,
    clip: "rect(0, 0, 0, 0)",
    whiteSpace: "nowrap",
  },
});
