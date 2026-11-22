"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Popover } from "@base-ui/react/popover";
import { KeyRound, LoaderCircle } from "lucide-react";

import { Button, IconButton } from "@/components/ui/button";
import { TextInput } from "@/components/ui/field";
import { overlay } from "@/lib/stylex/overlay.stylex";
import { tokens } from "@/lib/stylex/tokens.stylex";

import { CellVaultCredential } from "./CellVaultCredential";
import type { CellSecretInputSpec } from "../cell-contracts";

/**
 * A node's write-only keys, behind one key button in its card's header
 * instead of three rows each at the bottom of the config band.
 *
 * The button's dot says the worst state among the keys, so a card that still
 * needs one says so at rest. The popover lists every key with its status and
 * a write-only input: a saved key is never read back, only replaced or
 * removed.
 */

const spin = stylex.keyframes({
  from: { transform: "rotate(0deg)" },
  to: { transform: "rotate(360deg)" },
});

const s = stylex.create({
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
  positioner: { zIndex: 90 },
  popup: {
    boxSizing: "border-box",
    width: "min(280px, calc(100vw - 24px))",
    maxHeight: "calc(100dvh - 32px)",
    display: "grid",
    gap: "10px",
    overflowY: "auto",
    padding: "10px 11px 11px",
    // The canvas's frosted plates, lifted: a little more opaque than a card
    // so a key never reads through to the grid under it.
    backgroundColor: `color-mix(in oklab, ${tokens.colorSurface} 92%, transparent)`,
    backdropFilter: "blur(14px) saturate(1.4)",
    outline: "none",
  },
  header: { display: "grid", gap: "2px" },
  title: {
    margin: 0,
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeXs,
    fontWeight: 600,
  },
  subtitle: {
    margin: 0,
    color: tokens.colorSubtle,
    fontSize: "9px",
    lineHeight: 1.4,
  },
  inputs: { display: "grid", gap: "10px" },
  input: {
    display: "grid",
    gap: "4px",
    margin: 0,
    paddingTop: "8px",
    borderTopWidth: "1px",
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
  },
  inputHeader: {
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "8px",
  },
  inputTitle: {
    minWidth: 0,
    overflow: "hidden",
    color: tokens.colorText,
    fontSize: "9px",
    fontWeight: 600,
    textOverflow: "ellipsis",
    textTransform: "capitalize",
    whiteSpace: "nowrap",
  },
  badge: {
    flexShrink: 0,
    display: "inline-flex",
    alignItems: "center",
    height: "15px",
    paddingInline: "6px",
    borderRadius: "9999px",
    fontSize: "8.5px",
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
    gap: "5px",
  },
  footer: {
    minHeight: "18px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "8px",
  },
  hint: {
    minWidth: 0,
    margin: 0,
    color: tokens.colorSubtle,
    fontSize: "9px",
    lineHeight: 1.35,
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
  needed: "key needed",
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

export type ApplySecret = (name: string, value: string) => Promise<boolean>;
export type RemoveSecret = (name: string) => Promise<boolean>;

function SecretInputRow({
  cardId,
  input,
  onApply,
  onRemove,
}: {
  cardId: string;
  input: CellSecretInputSpec;
  onApply?: ApplySecret;
  onRemove?: RemoveSecret;
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
          size="dense"
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
        <Button type="submit" size="xs" variant="soft" disabled={!canApply}>
          {input.state === "applying" ? (
            <LoaderCircle
              size={11}
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
          size="xs"
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

const stopPointer = (event: React.PointerEvent) => event.stopPropagation();

export function CellCredentialsPopover({
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
  const [open, setOpen] = React.useState(defaultOpen);
  if (inputs.length === 0) return null;
  const tone = credentialsTone(inputs);
  const name = `Credentials for ${cardTitle}`;
  const popup = stylex.props(overlay.popup, s.popup);

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger
        data-credentials-trigger={tone}
        onPointerDown={stopPointer}
        render={
          <IconButton
            size="2xs"
            variant="ghost"
            label={`${name}: ${TONE_WORDS[tone]}`}
            title={`Credentials — ${TONE_WORDS[tone]}`}
            xstyle={s.trigger}
          />
        }
      >
        <KeyRound size={11} aria-hidden="true" />
        <span aria-hidden="true" {...stylex.props(s.dot, DOT_STYLE[tone])} />
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
            aria-label={name}
            data-credentials-popover={cardId}
            // The popup is portalled out of the card's DOM but not out of its
            // React tree, so a press here would still reach the card's drag.
            onPointerDown={stopPointer}
            className={popup.className}
            style={popup.style}
          >
            <header {...stylex.props(s.header)}>
              <h3 {...stylex.props(s.title)}>Credentials</h3>
              {inputs.every((input) => !input.vault) && (
                <p {...stylex.props(s.subtitle)}>
                  Saved write-only for this node. A saved key cannot be read
                  back.
                </p>
              )}
            </header>
            <div {...stylex.props(s.inputs)}>
              {inputs.map((input) =>
                input.vault ? (
                  <React.Fragment key={`${input.name}:${input.revision}`}>
                    <CellVaultCredential input={input} />
                    {input.vault.canManageShared &&
                      input.vault.status.effective_source ===
                        "inline_legacy" && (
                        <details>
                          <summary>Manage inline key</summary>
                          <SecretInputRow
                            cardId={cardId}
                            input={input}
                            onApply={onApply}
                            onRemove={onRemove}
                          />
                        </details>
                      )}
                  </React.Fragment>
                ) : (
                  <SecretInputRow
                    key={`${input.name}:${input.revision}`}
                    cardId={cardId}
                    input={input}
                    onApply={onApply}
                    onRemove={onRemove}
                  />
                ),
              )}
            </div>
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
  );
}
