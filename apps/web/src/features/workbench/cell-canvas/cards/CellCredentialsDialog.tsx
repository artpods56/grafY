"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { KeyRound, LoaderCircle } from "lucide-react";

import { Button, IconButton } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { TextInput } from "@/components/ui/field";
import { nodeCredentialTone } from "@/features/credentials/credential-display";
import { tokens } from "@/lib/stylex/tokens.stylex";

import { CellVaultCredential } from "./CellVaultCredential";
import {
  credentialsDialogInitialState,
  credentialsDialogReducer,
} from "./credentials-dialog-state";
import type { CellSecretInputSpec } from "../cell-contracts";

/**
 * A node's write-only keys, behind one key button in its card's header.
 *
 * It is a dialog and not a popover on purpose. A popover anchored to a card is
 * drawn at one scale and sits on a surface drawn at another: the canvas layer
 * carries `scale(zoom)` (`CellCanvas.tsx`), so an anchored plate reads as a
 * shrunken piece of the card at 200% and as a billboard wider than its node at
 * fit zoom. A dialog is app chrome, so it looks the same at every zoom. It also
 * cannot dismiss silently: an Escape or a backdrop press over an unsaved key
 * asks first (`credentials-dialog-state.ts`), because a saved key is never read
 * back and a typed one is worth more than a stray click.
 *
 * The button's dot still carries the worst state among the keys, so a card that
 * needs one says so at rest.
 */

const spin = stylex.keyframes({
  from: { transform: "rotate(0deg)" },
  to: { transform: "rotate(360deg)" },
});

const s = stylex.create({
  owner: { display: "inline-flex" },
  trigger: { position: "relative" },
  dot: {
    position: "absolute",
    top: "2px",
    right: "2px",
    width: "5px",
    height: "5px",
    borderRadius: "9999px",
    boxShadow: `0 0 0 1.5px ${tokens.colorSurface}`,
    pointerEvents: "none",
  },
  dotConfigured: { backgroundColor: tokens.colorSuccess },
  dotNeeded: { backgroundColor: tokens.colorWarning },
  dotError: { backgroundColor: tokens.colorDanger },
  dotPending: { backgroundColor: tokens.colorSubtle },
  discard: {
    display: "grid",
    gap: "8px",
    padding: "10px 12px",
    borderRadius: tokens.radiusMd,
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: `color-mix(in oklab, ${tokens.colorWarning} 30%, transparent)`,
    backgroundColor: tokens.colorWarningSoft,
  },
  discardTitle: {
    margin: 0,
    color: tokens.colorWarning,
    fontSize: tokens.fontSizeSm,
    fontWeight: 600,
  },
  discardBody: {
    margin: 0,
    color: tokens.colorText,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
  discardActions: {
    display: "flex",
    justifyContent: "flex-end",
    gap: "8px",
  },
  inputs: { display: "grid", gap: "16px" },
  /** Each vault key after the first starts under a hairline. */
  vaultSlot: {
    paddingTop: {
      default: "16px",
      ":first-child": "0px",
    },
    borderTopWidth: { default: "1px", ":first-child": "0px" },
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
  },
  legacy: {
    marginTop: "12px",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeSm,
  },
  legacySummary: {
    cursor: "pointer",
    color: {
      default: tokens.colorMuted,
      ":hover": tokens.colorText,
    },
    fontWeight: 600,
  },
  legacyBody: { marginTop: "10px" },
  input: {
    display: "grid",
    gap: "8px",
    margin: 0,
    paddingTop: {
      default: "14px",
      ":first-child": "0px",
    },
    borderTopWidth: { default: "1px", ":first-child": "0px" },
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
  },
  inputHeader: {
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "10px",
  },
  inputTitle: {
    minWidth: 0,
    overflow: "hidden",
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeMd,
    fontWeight: 600,
    textOverflow: "ellipsis",
    textTransform: "capitalize",
    whiteSpace: "nowrap",
  },
  badge: {
    flexShrink: 0,
    display: "inline-flex",
    alignItems: "center",
    height: "20px",
    paddingInline: "8px",
    borderRadius: "9999px",
    fontSize: tokens.fontSizeXs,
    fontWeight: 600,
    whiteSpace: "nowrap",
  },
  badgeConfigured: {
    backgroundColor: `color-mix(in oklab, ${tokens.colorSuccess} 14%, transparent)`,
    color: tokens.colorSuccess,
  },
  badgeNeeded: {
    backgroundColor: tokens.colorWarningSoft,
    color: tokens.colorWarning,
  },
  badgeError: {
    backgroundColor: `color-mix(in oklab, ${tokens.colorDanger} 14%, transparent)`,
    color: tokens.colorDanger,
  },
  badgePending: {
    backgroundColor: tokens.colorHover,
    color: tokens.colorSubtle,
  },
  control: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) auto",
    gap: "8px",
    alignItems: "center",
  },
  footer: {
    minHeight: "28px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "12px",
  },
  hint: {
    minWidth: 0,
    margin: 0,
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
  hintError: { color: tokens.colorDanger },
  spinner: {
    animationName: spin,
    animationDuration: {
      default: "900ms",
      "@media (prefers-reduced-motion: reduce)": "0s",
    },
    animationIterationCount: "infinite",
    animationTimingFunction: "linear",
  },
});

type CredentialsTone = "configured" | "needed" | "error" | "pending";

type BadgeTone = CredentialsTone;

/** What one key's badge says, and in which tone. */
export function secretInputBadge(input: CellSecretInputSpec): {
  label: string;
  tone: BadgeTone;
} {
  if (input.state === "stale") return { label: "Out of date", tone: "needed" };
  if (!input.ready) return { label: "Save node first", tone: "needed" };
  if (
    input.vault &&
    (input.state === "configured" || input.state === "unconfigured")
  ) {
    return vaultBadge(input.vault.status);
  }
  switch (input.state) {
    case "configured":
      return { label: "Configured", tone: "configured" };
    case "unconfigured":
      return { label: "Not set", tone: "needed" };
    case "applying":
      return { label: "Saving…", tone: "pending" };
    case "removing":
      return { label: "Removing…", tone: "pending" };
    case "loading":
      return { label: "Checking…", tone: "pending" };
    case "error":
      return { label: "Error", tone: "error" };
    case "unknown":
      return { label: "Unavailable", tone: "pending" };
  }
}

/**
 * A vault key's badge follows the key that runs the node, not only whether one
 * is set: a key the provider refused or a shared key that is gone is an error,
 * one that could not be reached needs attention.
 */
function vaultBadge(
  status: NonNullable<CellSecretInputSpec["vault"]>["status"],
): {
  label: string;
  tone: BadgeTone;
} {
  const tone = nodeCredentialTone(status);
  if (status.shared_credential_missing) {
    return { label: "Shared key missing", tone };
  }
  switch (status.effective_verification_status) {
    case "invalid":
      return { label: "Key invalid", tone };
    case "egress_blocked":
      return { label: "Blocked", tone };
    case "unreachable":
      if (status.configured) return { label: "Unreachable", tone };
  }
  if (tone === "needed") return { label: "Not set", tone };
  return {
    label:
      status.effective_verification_status === "valid"
        ? "Verified"
        : "Configured",
    tone,
  };
}

/** The worst state wins: one key that needs attention is the card's state. */
export function credentialsTone(
  inputs: readonly CellSecretInputSpec[],
): CredentialsTone {
  const tones = inputs.map((input) => secretInputBadge(input).tone);
  if (tones.includes("error")) return "error";
  if (tones.includes("needed")) return "needed";
  if (tones.length > 0 && tones.every((tone) => tone === "configured")) {
    return "configured";
  }
  return "pending";
}

const TONE_WORDS: Record<CredentialsTone, string> = {
  configured: "configured",
  needed: "needs attention",
  error: "key error",
  pending: "status unavailable",
};

const DOT_STYLE = {
  configured: s.dotConfigured,
  needed: s.dotNeeded,
  error: s.dotError,
  pending: s.dotPending,
} as const;

const BADGE_STYLE = {
  configured: s.badgeConfigured,
  needed: s.badgeNeeded,
  error: s.badgeError,
  pending: s.badgePending,
} as const;

/** What the dialog's own subtitle says about the keys it holds. */
export function credentialsIntro(
  inputs: readonly CellSecretInputSpec[],
): string {
  const vaulted = inputs.filter((input) => input.vault).length;
  if (vaulted === 0) {
    return "Saved write-only for this node. A saved key cannot be read back.";
  }
  if (vaulted === inputs.length) {
    return "Choose whose key runs this node. A saved key is never shown again.";
  }
  return "Some of these keys come from the workspace vault and some are saved on this node. A saved key is never shown again.";
}

export type ApplySecret = (name: string, value: string) => Promise<boolean>;
export type RemoveSecret = (name: string) => Promise<boolean>;
/** Reports whether a key field holds typed text the server has never seen. */
export type ReportDraft = (name: string, dirty: boolean) => void;

function SecretInputRow({
  cardId,
  input,
  onApply,
  onRemove,
  onDraft,
}: {
  cardId: string;
  input: CellSecretInputSpec;
  onApply?: ApplySecret;
  onRemove?: RemoveSecret;
  onDraft?: ReportDraft;
}) {
  const [value, setValue] = React.useState("");
  const badge = secretInputBadge(input);
  const busy = input.state === "applying" || input.state === "removing";
  const canApply = input.ready && !busy && value.length > 0 && Boolean(onApply);
  const canRemove =
    input.ready && !busy && input.state === "configured" && Boolean(onRemove);
  const hint = !input.ready
    ? input.state === "stale"
      ? "Save the changed settings, then paste a new key."
      : "Save this node before adding a key."
    : input.state === "stale"
      ? "Paste a key for the current settings."
      : input.state === "error"
        ? (input.message ?? "The key could not be saved.")
        : (input.description ??
          "Write-only · a saved key cannot be read back.");
  const titleId = React.useId();

  React.useEffect(() => {
    onDraft?.(input.name, value.length > 0);
  }, [input.name, value, onDraft]);

  return (
    <form
      aria-labelledby={titleId}
      data-secret-input={input.name}
      {...stylex.props(s.input)}
      onSubmit={(event) => {
        event.preventDefault();
        if (!canApply || !onApply) return;
        void onApply(input.name, value).then((applied) => {
          if (applied) setValue("");
        });
      }}
    >
      <div {...stylex.props(s.inputHeader)}>
        <span id={titleId} {...stylex.props(s.inputTitle)}>
          {input.title}
        </span>
        <span
          role="status"
          data-secret-status={input.state}
          {...stylex.props(s.badge, BADGE_STYLE[badge.tone])}
        >
          {badge.label}
        </span>
      </div>
      <div {...stylex.props(s.control)}>
        <TextInput
          mono
          type="password"
          name={`${cardId}-${input.name}`}
          value={value}
          autoComplete="off"
          autoCapitalize="none"
          spellCheck={false}
          data-1p-ignore
          data-lpignore="true"
          data-bwignore
          aria-label={input.title}
          placeholder={
            input.state === "configured" ? "Replace key" : "Paste key"
          }
          disabled={!input.ready || busy}
          onChange={(event) => setValue(event.currentTarget.value)}
        />
        <Button type="submit" size="md" variant="soft" disabled={!canApply}>
          {input.state === "applying" ? (
            <LoaderCircle
              size={13}
              aria-hidden="true"
              {...stylex.props(s.spinner)}
            />
          ) : null}
          Apply
        </Button>
      </div>
      <div {...stylex.props(s.footer)}>
        <p
          {...stylex.props(
            s.hint,
            input.state === "error" && input.ready ? s.hintError : null,
          )}
        >
          {hint}
        </p>
        <Button
          type="button"
          size="sm"
          variant="danger"
          disabled={!canRemove}
          onClick={() => {
            if (!canRemove || !onRemove) return;
            void onRemove(input.name).then((removed) => {
              if (removed) setValue("");
            });
          }}
        >
          Remove
        </Button>
      </div>
    </form>
  );
}

/** The dialog's contents, apart from its frame, so a spike can draw them. */
export function CellCredentialsBody({
  cardId,
  inputs,
  onApply,
  onRemove,
  onDraft,
}: {
  cardId: string;
  inputs: readonly CellSecretInputSpec[];
  onApply?: ApplySecret;
  onRemove?: RemoveSecret;
  onDraft?: ReportDraft;
}) {
  return (
    <div {...stylex.props(s.inputs)}>
      {inputs.map((input) =>
        input.vault ? (
          <div
            key={`${input.name}:${input.revision}`}
            {...stylex.props(s.vaultSlot)}
          >
            <CellVaultCredential input={input} />
            {input.vault.canManageShared &&
              input.vault.status.effective_source === "inline_legacy" && (
                <details {...stylex.props(s.legacy)}>
                  <summary {...stylex.props(s.legacySummary)}>
                    Manage inline key
                  </summary>
                  <div {...stylex.props(s.legacyBody)}>
                    <SecretInputRow
                      cardId={cardId}
                      input={input}
                      onApply={onApply}
                      onRemove={onRemove}
                      onDraft={onDraft}
                    />
                  </div>
                </details>
              )}
          </div>
        ) : (
          <SecretInputRow
            key={`${input.name}:${input.revision}`}
            cardId={cardId}
            input={input}
            onApply={onApply}
            onRemove={onRemove}
            onDraft={onDraft}
          />
        ),
      )}
    </div>
  );
}

const stopPointer = (event: React.PointerEvent) => event.stopPropagation();

export function CellCredentialsDialog({
  cardId,
  cardTitle,
  inputs,
  onApply,
  onRemove,
  defaultOpen = false,
}: {
  cardId: string;
  cardTitle: string;
  inputs: readonly CellSecretInputSpec[];
  onApply?: ApplySecret;
  onRemove?: RemoveSecret;
  /** For a card rendered on its own, e.g. a test or a sandbox spike. */
  defaultOpen?: boolean;
}) {
  const [state, dispatch] = React.useReducer(
    credentialsDialogReducer,
    defaultOpen,
    credentialsDialogInitialState,
  );
  const reportDraft = React.useCallback<ReportDraft>(
    (name, dirty) => dispatch({ kind: "draft", name, dirty }),
    [],
  );
  if (inputs.length === 0) return null;
  const tone = credentialsTone(inputs);
  const name = `Credentials for ${cardTitle}`;

  return (
    <span onPointerDown={stopPointer} {...stylex.props(s.owner)}>
      <IconButton
        size="2xs"
        variant="ghost"
        label={`${name}: ${TONE_WORDS[tone]}`}
        title={`Credentials — ${TONE_WORDS[tone]}`}
        xstyle={s.trigger}
        data-credentials-trigger={tone}
        aria-haspopup="dialog"
        aria-expanded={state.open}
        onPointerDown={stopPointer}
        onClick={() => dispatch({ kind: "open" })}
      >
        <KeyRound size={11} aria-hidden="true" />
        <span aria-hidden="true" {...stylex.props(s.dot, DOT_STYLE[tone])} />
      </IconButton>
      <Dialog
        open={state.open}
        onOpenChange={(next) =>
          dispatch({ kind: next ? "open" : "requestClose" })
        }
      >
        <DialogContent
          size="form"
          data-credentials-dialog={cardId}
          // The popup is portalled out of the card's DOM but not out of its
          // React tree, so a press here would still reach the card's drag.
          onPointerDown={stopPointer}
        >
          <DialogHeader>
            <DialogTitle>Credentials · {cardTitle}</DialogTitle>
            <DialogDescription>{credentialsIntro(inputs)}</DialogDescription>
          </DialogHeader>
          <DialogBody>
            {state.discardAsked && (
              <div
                role="alertdialog"
                aria-label="Discard the key you typed?"
                data-credentials-discard="ask"
                {...stylex.props(s.discard)}
              >
                <p {...stylex.props(s.discardTitle)}>
                  You typed a key that was not saved.
                </p>
                <p {...stylex.props(s.discardBody)}>
                  A saved key is never shown again, so closing now loses what is
                  in the field.
                </p>
                <div {...stylex.props(s.discardActions)}>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() => dispatch({ kind: "keepEditing" })}
                  >
                    Keep editing
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="danger"
                    onClick={() => dispatch({ kind: "discard" })}
                  >
                    Discard and close
                  </Button>
                </div>
              </div>
            )}
            <CellCredentialsBody
              cardId={cardId}
              inputs={inputs}
              onApply={onApply}
              onRemove={onRemove}
              onDraft={reportDraft}
            />
          </DialogBody>
        </DialogContent>
      </Dialog>
    </span>
  );
}
