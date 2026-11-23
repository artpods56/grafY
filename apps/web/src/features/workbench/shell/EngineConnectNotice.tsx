"use client";

import * as stylex from "@stylexjs/stylex";

import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";
import { tokens } from "@/lib/stylex/tokens.stylex";

const s = stylex.create({
  dock: {
    position: "fixed",
    zIndex: 80,
    right: "24px",
    bottom: "24px",
    maxWidth: "420px",
  },
  lead: {
    color: tokens.colorText,
  },
});

/** Quiet notice after an engine connects. Undo drops that provider batch only. */
export function EngineConnectNotice({
  lead,
  onUndo,
  onDismiss,
}: {
  lead: string;
  onUndo: () => void;
  onDismiss: () => void;
}) {
  return (
    <div data-engine-connect-notice="true" {...stylex.props(s.dock)}>
      <Notice tone="neutral" onDismiss={onDismiss} dismissLabel="Dismiss">
        <span {...stylex.props(s.lead)}>{lead}</span>
        {" · "}
        <Button size="xs" variant="ghost" onClick={onUndo}>
          Undo
        </Button>
      </Notice>
    </div>
  );
}
