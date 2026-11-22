"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Popover } from "@base-ui/react/popover";
import { KeyRound } from "lucide-react";

import { Button, IconButton } from "@/components/ui/button";
import { overlay } from "@/lib/stylex/overlay.stylex";
import { tokens } from "@/lib/stylex/tokens.stylex";

import {
  nodeSecretDependencyRevision,
  nodeSecretInputs,
  type WorkflowNodeSecretState,
} from "../../node-secrets";
import type { WorkflowNodeData } from "../../types";

import { SecretInputField, effectiveSecretStatus } from "./config-fields";

const s = stylex.create({
  positioner: { zIndex: 90 },
  popup: {
    width: "min(300px, calc(100vw - 24px))",
    maxHeight: "calc(100dvh - 32px)",
    display: "grid",
    gap: "10px",
    overflowY: "auto",
    padding: "11px 12px 12px",
  },
  header: { display: "grid", gap: "2px" },
  title: {
    margin: 0,
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeSm,
    fontWeight: 600,
  },
  subtitle: {
    margin: 0,
    color: tokens.colorSubtle,
    fontSize: "10px",
    lineHeight: 1.35,
  },
  inputs: { display: "grid", gap: "12px" },
  configured: { color: tokens.colorSuccess },
  needed: {
    backgroundColor: {
      default: tokens.colorWarningSoft,
      ":hover:not(:disabled)": tokens.colorWarningSoft,
    },
    color: tokens.colorWarning,
  },
  failed: { color: tokens.colorDanger },
  pill: { gap: "4px", borderRadius: "9999px" },
});

type CredentialsTone = "configured" | "needed" | "stale" | "error" | "pending";

/** The worst state wins: one key that needs attention is the card's state. */
function credentialsTone(
  states: readonly WorkflowNodeSecretState[],
): CredentialsTone {
  if (states.includes("error")) return "error";
  if (states.includes("stale")) return "stale";
  if (states.includes("unconfigured")) return "needed";
  if (states.every((state) => state === "configured")) return "configured";
  return "pending";
}

const PILL_LABEL: Record<Exclude<CredentialsTone, "configured">, string> = {
  needed: "Key needed",
  stale: "Key out of date",
  error: "Key error",
  pending: "Credentials",
};

/**
 * Write-only keys live behind one header control instead of in the config
 * board: configured keys collapse to a quiet key icon, and a node that still
 * needs one says so in words on the card itself.
 */
export function CredentialsPopover({
  id,
  data,
  onOpenChange,
}: {
  id: string;
  data: WorkflowNodeData;
  onOpenChange?: (open: boolean) => void;
}) {
  const [open, setOpen] = React.useState(false);
  const inputs = nodeSecretInputs(data.spec);
  if (!inputs.length) return null;
  const tone = credentialsTone(
    inputs.map((input) => effectiveSecretStatus(data, input).state),
  );
  const triggerName = `Credentials for ${data.spec.title}`;
  const popup = stylex.props(overlay.popup, s.popup);
  const trigger =
    tone === "configured" ? (
      <IconButton
        label={triggerName}
        title="Credentials configured"
        size="xs"
        shape="round"
        className="nodrag nopan nowheel"
        xstyle={s.configured}
      />
    ) : (
      <Button
        size="xs"
        variant="soft"
        aria-label={`${triggerName}: ${PILL_LABEL[tone]}`}
        title={`${PILL_LABEL[tone]} — ${triggerName}`}
        className="nodrag nopan nowheel"
        xstyle={[s.pill, tone === "error" ? s.failed : s.needed]}
      />
    );

  return (
    <Popover.Root
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        onOpenChange?.(next);
      }}
    >
      <Popover.Trigger render={trigger}>
        <KeyRound size={11} aria-hidden="true" />
        {tone === "configured" ? null : PILL_LABEL[tone]}
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Positioner
          {...stylex.props(s.positioner)}
          side="bottom"
          align="end"
          sideOffset={6}
          collisionPadding={12}
        >
          <Popover.Popup
            aria-label={triggerName}
            className={`nodrag nopan nowheel ${popup.className ?? ""}`}
            style={popup.style}
          >
            <header {...stylex.props(s.header)}>
              <h3 {...stylex.props(s.title)}>Credentials</h3>
              <p {...stylex.props(s.subtitle)}>
                Saved write-only for this node. A saved key cannot be read back.
              </p>
            </header>
            <div {...stylex.props(s.inputs)}>
              {inputs.map((input) => (
                <SecretInputField
                  key={`${data.secretInputScope}:${input.name}:${nodeSecretDependencyRevision(input, data.config)}`}
                  id={id}
                  data={data}
                  input={input}
                />
              ))}
            </div>
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
  );
}
