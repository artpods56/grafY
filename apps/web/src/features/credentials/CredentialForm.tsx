"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { FlaskConical, LoaderCircle, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Field, TextInput } from "@/components/ui/field";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Select } from "@/components/ui/select";
import {
  createCredential,
  credentialVerificationFailure,
  verifyCredential,
  type Credential,
  type CredentialLocation,
  type CredentialScope,
} from "@/lib/api";
import { useEffectReducer } from "@/lib/state/use-effect-reducer";
import { tokens } from "@/lib/stylex/tokens.stylex";

import { CredentialBadge, CredentialCallout } from "./CredentialBadge";
import {
  checkAllowsSaveAnyway,
  credentialFormReducer,
  type CredentialCandidate,
  type CredentialCheck,
} from "./credential-form-state";
import {
  credentialFieldLabel,
  credentialStatusLabel,
  credentialStatusTone,
  providerDisplayName,
} from "./credential-display";

export { credentialStatusLabel } from "./credential-display";

const spin = stylex.keyframes({
  from: { transform: "rotate(0deg)" },
  to: { transform: "rotate(360deg)" },
});

const styles = stylex.create({
  stack: { display: "grid", gap: "6px" },
  form: {
    display: "grid",
    boxSizing: "border-box",
    minWidth: 0,
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    backgroundColor: tokens.colorSurface,
  },
  formMd: { gap: "12px", padding: "14px", borderRadius: tokens.radiusLg },
  header: {
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "8px",
  },
  title: {
    margin: 0,
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeMd,
    fontWeight: 600,
  },
  scope: { display: "grid", gap: "3px" },
  helper: {
    margin: 0,
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.4,
  },
  fields: { display: "grid", gap: "8px" },
  /** Two columns where there is room: the full-page credential manager. */
  fieldsGrid: {
    gridTemplateColumns: {
      default: "minmax(0, 1fr)",
      "@media (min-width: 720px)": "repeat(2, minmax(0, 1fr))",
    },
    gap: "10px 12px",
  },
  /** One column: a narrow dialog, where a URL needs the whole line. */
  fieldsStack: { gridTemplateColumns: "minmax(0, 1fr)", gap: "10px" },
  actions: {
    display: "flex",
    alignItems: "center",
    flexWrap: "wrap",
    gap: "6px",
  },
  push: { marginInlineStart: "auto" },
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

export interface CredentialProvider {
  kind: string;
  fields: readonly string[];
  defaults?: Readonly<Record<string, string>>;
  /** Whether the provider can check a key; hides "Test key" when it cannot. */
  supportsVerification?: boolean;
}

const SCOPE_HELP: Record<CredentialScope, string> = {
  personal: "Only you can use this key.",
  shared: "Members who can run graphs in this workspace can use it.",
};

function credentialLocation(
  scope: CredentialScope,
  workspaceId: string,
): CredentialLocation {
  return scope === "shared" ? { scope, workspaceId } : { scope: "personal" };
}

/** The candidate key the form holds now, or nothing while it is incomplete. */
function readCandidate(
  form: HTMLFormElement,
  provider: CredentialProvider,
): (CredentialCandidate & { label: string }) | null {
  const data = new FormData(form);
  const label = data.get("label");
  const value = data.get("value");
  if (typeof label !== "string" || typeof value !== "string" || !value) {
    return null;
  }
  const config = Object.fromEntries(
    provider.fields.flatMap((field) => {
      const entry = data.get(field);
      return typeof entry === "string" && entry.trim()
        ? [[field, entry.trim()]]
        : [];
    }),
  );
  return { label, value, provider_kind: provider.kind, config };
}

function Spinner({ size }: { size: number }) {
  return (
    <LoaderCircle
      size={size}
      aria-hidden="true"
      {...stylex.props(styles.spinner)}
    />
  );
}

function CheckCallout({ check }: { check: CredentialCheck }) {
  if (check.kind === "error") {
    return (
      <CredentialCallout tone="danger" title="Test failed">
        {check.message}
      </CredentialCallout>
    );
  }
  const { status, message, account_hint } = check.verification;
  return (
    <CredentialCallout
      tone={credentialStatusTone(status)}
      title={credentialStatusLabel[status]}
    >
      {[message, account_hint].filter(Boolean).join(" · ")}
    </CredentialCallout>
  );
}

/**
 * Adds one provider key to the personal or the shared vault. "Test key" checks
 * the pasted key without saving it; "Verify & save" checks it and saves it,
 * and "Save anyway" keeps a key the provider could not be asked about.
 */
export function CredentialForm({
  workspaceId,
  providers,
  scopes,
  layout = "grid",
  keyLabel = "API key",
  onSaved,
}: {
  workspaceId: string;
  providers: readonly CredentialProvider[];
  scopes: readonly CredentialScope[];
  /** The field grid: `grid` for the full page, `stack` for a narrow dialog. */
  layout?: "grid" | "stack";
  /** The key field's label, e.g. the node's own name for its secret. */
  keyLabel?: string;
  onSaved: (saved: Credential) => Promise<unknown>;
}) {
  const [state, dispatch] = useEffectReducer(
    credentialFormReducer,
    { kind: "closed" },
    (effect, dispatch) => {
      if (effect.kind === "test") {
        void verifyCredential(effect.location, effect.candidate).then(
          (verification) => dispatch({ kind: "tested", verification }),
          (error: unknown) =>
            dispatch({
              kind: "test-failed",
              message: credentialVerificationFailure(error).message,
            }),
        );
        return;
      }
      void createCredential(effect.location, effect.body).then(
        (saved) => {
          dispatch({ kind: "resolve", saved });
          void onSaved(saved).catch(() => undefined);
        },
        (error: unknown) =>
          dispatch({ kind: "reject", ...credentialVerificationFailure(error) }),
      );
    },
    { flush: "sync" },
  );
  const [kind, setKind] = React.useState<string>();
  const [scope, setScope] = React.useState<CredentialScope>();
  const provider = providers.find((item) => item.kind === kind) ?? providers[0];
  const activeScope =
    scope && scopes.includes(scope) ? scope : (scopes[0] ?? "personal");
  const iconSize = 13;
  if (!provider || scopes.length === 0) return null;

  if (state.kind === "closed" || state.kind === "saved") {
    return (
      <div {...stylex.props(styles.stack)}>
        {state.kind === "saved" && (
          <CredentialCallout
            tone={credentialStatusTone(state.saved.verification_status)}
            title={`Saved “${state.saved.label}”`}
          >
            {state.saved.verification_message ??
              credentialStatusLabel[state.saved.verification_status]}
          </CredentialCallout>
        )}
        <Button
          type="button"
          size="sm"
          variant="dashed"
          block
          onClick={() => dispatch({ kind: "open" })}
        >
          <Plus size={iconSize} aria-hidden="true" />
          Add credential
        </Button>
      </div>
    );
  }

  const saving = state.kind === "saving";
  const testing = state.kind === "testing";
  const busy = saving || testing;
  const check = state.kind === "editing" ? state.check : undefined;
  const canSaveAnyway =
    (state.kind === "failed" && state.canSave) || checkAllowsSaveAnyway(check);
  const canTest = provider.supportsVerification !== false;

  return (
    <form
      aria-label="Add credential"
      data-credential-form={state.kind}
      {...stylex.props(styles.form, styles.formMd)}
      onChange={(event) => {
        const target = event.target;
        dispatch({
          kind: "edit",
          field: target instanceof HTMLInputElement ? target.name : "",
        });
      }}
      onSubmit={(event) => {
        event.preventDefault();
        if (busy) return;
        const candidate = readCandidate(event.currentTarget, provider);
        if (!candidate) return;
        const save_if_unverified =
          event.nativeEvent instanceof SubmitEvent &&
          event.nativeEvent.submitter?.getAttribute("value") === "save-anyway";
        dispatch({
          kind: "submit",
          location: credentialLocation(activeScope, workspaceId),
          body: {
            provider_kind: candidate.provider_kind,
            label: candidate.label,
            value: candidate.value,
            verify: true,
            verify_config: candidate.config,
            save_if_unverified,
          },
        });
      }}
    >
      <div {...stylex.props(styles.header)}>
        <h4 {...stylex.props(styles.title)}>New credential</h4>
        {providers.length === 1 && (
          <CredentialBadge tone="outline">
            {providerDisplayName(provider.kind)}
          </CredentialBadge>
        )}
      </div>
      {scopes.length > 1 && (
        <div {...stylex.props(styles.scope)}>
          <SegmentedControl
            size="md"
            aria-label="Credential scope"
            value={activeScope}
            disabled={busy}
            options={scopes.map((option) => ({
              value: option,
              label: option === "personal" ? "Personal" : "Shared",
            }))}
            onValueChange={setScope}
          />
          <p {...stylex.props(styles.helper)}>{SCOPE_HELP[activeScope]}</p>
        </div>
      )}
      <div
        {...stylex.props(
          styles.fields,
          layout === "stack" ? styles.fieldsStack : styles.fieldsGrid,
        )}
      >
        {providers.length > 1 && (
          <Field label="Provider">
            <Select
              value={provider.kind}
              disabled={busy}
              onChange={(event) => setKind(event.currentTarget.value)}
            >
              {providers.map(({ kind: option }) => (
                <option key={option} value={option}>
                  {providerDisplayName(option)}
                </option>
              ))}
            </Select>
          </Field>
        )}
        <Field label="Label">
          <TextInput
            name="label"
            placeholder="e.g. Team gateway"
            maxLength={160}
            disabled={busy}
            required
          />
        </Field>
        <Field label={keyLabel}>
          <TextInput
            name="value"
            placeholder="Paste key"
            type="password"
            mono
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            data-1p-ignore
            data-lpignore="true"
            data-bwignore
            disabled={busy}
            required
          />
        </Field>
        {provider.fields.map((field) => (
          <Field
            key={`${provider.kind}:${field}`}
            label={credentialFieldLabel(field)}
          >
            <TextInput
              name={field}
              type="url"
              mono
              placeholder="https://…"
              defaultValue={provider.defaults?.[field]}
              disabled={busy}
              required={field !== "base_url"}
            />
          </Field>
        ))}
      </div>
      {check && <CheckCallout check={check} />}
      {state.kind === "failed" && (
        <CredentialCallout
          tone={state.canSave ? "warning" : "danger"}
          title={state.canSave ? "Not verified" : "Not saved"}
        >
          {state.message}
        </CredentialCallout>
      )}
      <div {...stylex.props(styles.actions)}>
        <Button type="submit" size="sm" variant="primary" disabled={busy}>
          {saving ? <Spinner size={iconSize} /> : null}
          {saving ? "Verifying…" : "Verify & save"}
        </Button>
        {canSaveAnyway && (
          <Button
            type="submit"
            value="save-anyway"
            size="sm"
            variant="secondary"
            disabled={busy}
          >
            Save anyway
          </Button>
        )}
        {canTest && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={(event) => {
              const form = event.currentTarget.form;
              if (!form) return;
              // Testing needs the key and its settings, not a label.
              for (const element of form.elements) {
                if (
                  element instanceof HTMLInputElement &&
                  element.name !== "label" &&
                  !element.reportValidity()
                ) {
                  return;
                }
              }
              const candidate = readCandidate(form, provider);
              if (!candidate) return;
              dispatch({
                kind: "test",
                location: credentialLocation(activeScope, workspaceId),
                candidate: {
                  provider_kind: candidate.provider_kind,
                  value: candidate.value,
                  config: candidate.config,
                },
              });
            }}
          >
            {testing ? (
              <Spinner size={iconSize} />
            ) : (
              <FlaskConical size={iconSize} aria-hidden="true" />
            )}
            {testing ? "Testing…" : "Test key"}
          </Button>
        )}
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={busy}
          xstyle={styles.push}
          onClick={() => dispatch({ kind: "close" })}
        >
          Cancel
        </Button>
      </div>
    </form>
  );
}
