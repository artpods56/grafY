"use client";

import * as stylex from "@stylexjs/stylex";
import type { Connection } from "@xyflow/react";

import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { RunEdgeCollectionMode } from "@/lib/api";
import { overlay } from "@/lib/stylex/overlay.stylex";
import { tokens } from "@/lib/stylex/tokens.stylex";
import type { ConnectionRoute } from "../canvas/handles";
import {
  connectionRouteFeedDescription,
  connectionRouteFeedTitle,
} from "../model/connection-feeds";

interface ConnectionEndpoint {
  nodeTitle: string;
  portName: string;
  artifactType: string;
}

export interface PendingConnectionRoute {
  connection: Connection;
  collectionMode: RunEdgeCollectionMode;
  candidates: ConnectionRoute[];
  source: ConnectionEndpoint;
  target: ConnectionEndpoint;
  preferredProjectionPath?: readonly string[];
  /**
   * When set, the edge already exists (connect-first). Selecting a feed updates
   * it; cancel keeps the initial whole-output route.
   */
  refineEdgeId?: string;
}

interface ConnectionRouteDialogProps {
  pendingRoute: PendingConnectionRoute | null;
  onSelect: (route: ConnectionRoute) => void;
  onClose: () => void;
}

const s = stylex.create({
  projectionFlow: {
    display: "grid",
    gridTemplateColumns: "minmax(0,1fr) 24px minmax(0,1fr)",
    alignItems: "center",
    gap: "7px",
    marginBottom: "14px",
  },
  projectionEndpoint: {
    minWidth: 0,
    display: "grid",
    gap: "3px",
    padding: "9px 10px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "6px",
    backgroundColor: tokens.colorSurfaceMuted,
  },
  projectionDirection: {
    color: tokens.colorSubtle,
    fontSize: "10px",
    fontWeight: 800,
    letterSpacing: "0.1em",
    textTransform: "uppercase",
  },
  projectionEndpointName: {
    overflow: "hidden",
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeSm,
    fontWeight: 700,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  projectionEndpointType: {
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: tokens.fontSizeXs,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  projectionArrow: {
    color: tokens.colorSubtle,
    fontSize: "15px",
    textAlign: "center",
  },
  projectionPrompt: {
    marginBottom: "7px",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
  },
  projectionChoices: { display: "grid", gap: "6px" },
  projectionChoice: {
    width: "100%",
    minHeight: "44px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "12px",
    padding: "8px 10px",
    borderRadius: "6px",
    outlineColor: tokens.colorAccent,
    outlineStyle: "solid",
    outlineOffset: "-3px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
    color: tokens.colorText,
    cursor: "pointer",
    textAlign: "left",
  },
  projectionChoiceTitle: { fontSize: tokens.fontSizeSm, fontWeight: 720 },
  projectionChoicePath: {
    color: tokens.colorProjectionPath,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: tokens.fontSizeXs,
    textAlign: "right",
  },
  projectionActions: {
    display: "flex",
    justifyContent: "flex-end",
    marginTop: "12px",
  },
  projectionCancel: {
    minHeight: "29px",
    paddingInline: "10px",
    borderWidth: 0,
    borderRadius: "5px",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: tokens.colorMuted,
    cursor: "pointer",
    fontSize: tokens.fontSizeSm,
  },
});

export function ConnectionRouteDialog({
  pendingRoute,
  onSelect,
  onClose,
}: ConnectionRouteDialogProps) {
  return (
    <Dialog
      open={pendingRoute !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent size="compact">
        <DialogHeader>
          <DialogTitle>
            {pendingRoute
              ? `What should arrive at ${pendingRoute.target.portName}?`
              : "What should arrive?"}
          </DialogTitle>
          <DialogDescription>
            {pendingRoute?.refineEdgeId
              ? "The connection is already in place with the whole output. Pick a field if you want something more specific."
              : "Choose which value this connection feeds into the input."}
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          {pendingRoute ? (
            <>
              <div {...stylex.props(s.projectionFlow)}>
                <div {...stylex.props(s.projectionEndpoint)}>
                  <span {...stylex.props(s.projectionDirection)}>From</span>
                  <span {...stylex.props(s.projectionEndpointName)}>
                    {pendingRoute.source.nodeTitle} ·{" "}
                    {pendingRoute.source.portName}
                  </span>
                  <span {...stylex.props(s.projectionEndpointType)}>
                    {pendingRoute.source.artifactType}
                  </span>
                </div>
                <span aria-hidden="true" {...stylex.props(s.projectionArrow)}>
                  →
                </span>
                <div {...stylex.props(s.projectionEndpoint)}>
                  <span {...stylex.props(s.projectionDirection)}>Into</span>
                  <span {...stylex.props(s.projectionEndpointName)}>
                    {pendingRoute.target.nodeTitle} ·{" "}
                    {pendingRoute.target.portName}
                  </span>
                  <span {...stylex.props(s.projectionEndpointType)}>
                    {pendingRoute.target.artifactType}
                  </span>
                </div>
              </div>
              <p {...stylex.props(s.projectionPrompt)}>
                {pendingRoute.refineEdgeId
                  ? "Keep the whole output, or feed a declared field:"
                  : pendingRoute.preferredProjectionPath?.length
                    ? "More than one way to deliver that field:"
                    : "More than one compatible feed is available:"}
              </p>
              <div {...stylex.props(s.projectionChoices)}>
                {pendingRoute.candidates.map((candidate, index) => {
                  const title = connectionRouteFeedTitle(candidate);
                  const description = connectionRouteFeedDescription(
                    pendingRoute.source.portName,
                    candidate,
                  );
                  return (
                    <button
                      key={`${candidate.kind}-${description}-${index}`}
                      type="button"
                      autoFocus={index === 0}
                      aria-label={`Feed ${title} from ${pendingRoute.source.nodeTitle}`}
                      {...stylex.props(overlay.item, s.projectionChoice)}
                      onClick={() => {
                        onSelect(candidate);
                        onClose();
                      }}
                    >
                      <span {...stylex.props(s.projectionChoiceTitle)}>
                        {title}
                      </span>
                      <span {...stylex.props(s.projectionChoicePath)}>
                        {description}
                      </span>
                    </button>
                  );
                })}
              </div>
              <div {...stylex.props(s.projectionActions)}>
                <button
                  type="button"
                  {...stylex.props(s.projectionCancel)}
                  onClick={onClose}
                >
                  {pendingRoute.refineEdgeId ? "Keep whole output" : "Cancel"}
                </button>
              </div>
            </>
          ) : null}
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
