"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Button } from "@/components/ui/button";
import { TextInput } from "@/components/ui/field";
import { Select } from "@/components/ui/select";
import {
  createCredential,
  credentialVerificationFailure,
  type CredentialScope,
  type CredentialVerificationStatus,
} from "@/lib/api";
import { useEffectReducer } from "@/lib/state/use-effect-reducer";
import { credentialFormReducer } from "./credential-form-state";

const styles = stylex.create({
  form: { display: "grid", gap: "6px" },
  actions: { display: "flex", gap: "6px", flexWrap: "wrap" },
});

export interface CredentialProvider {
  kind: string;
  fields: readonly string[];
  defaults?: Readonly<Record<string, string>>;
}

export const credentialStatusLabel: Record<
  CredentialVerificationStatus,
  string
> = {
  valid: "Verified",
  invalid: "Invalid",
  unverified: "Unverified",
  unreachable: "Unreachable",
  egress_blocked: "Blocked by egress policy",
  unsupported: "Verification unsupported",
};

export function CredentialForm({
  workspaceId,
  providers,
  scopes,
  dense = false,
  onSaved,
}: {
  workspaceId: string;
  providers: readonly CredentialProvider[];
  scopes: readonly CredentialScope[];
  dense?: boolean;
  onSaved: () => Promise<unknown>;
}) {
  const [state, dispatch] = useEffectReducer(
    credentialFormReducer,
    { kind: "closed" },
    (effect, dispatch) => {
      void createCredential(effect.location, effect.body).then(
        (saved) => {
          dispatch({
            kind: "resolve",
            message:
              saved.verification_message ??
              credentialStatusLabel[saved.verification_status],
          });
          void onSaved().catch(() => undefined);
        },
        (error: unknown) =>
          dispatch({ kind: "reject", ...credentialVerificationFailure(error) }),
      );
    },
    { flush: "sync" },
  );
  const [kind, setKind] = React.useState<string>();
  const provider = providers.find((item) => item.kind === kind) ?? providers[0];
  const size = dense ? "dense" : "md";
  if (!provider || scopes.length === 0) return null;
  if (state.kind === "closed" || state.kind === "saved") {
    return (
      <div {...stylex.props(styles.form)}>
        {state.kind === "saved" && <span role="status">{state.message}</span>}
        <Button
          type="button"
          size="xs"
          variant="soft"
          onClick={() => dispatch({ kind: "open" })}
        >
          + Add credential
        </Button>
      </div>
    );
  }

  const busy = state.kind === "saving";
  return (
    <form
      aria-label="Add credential"
      {...stylex.props(styles.form)}
      onChange={() => {
        if (state.kind === "failed") dispatch({ kind: "edit" });
      }}
      onSubmit={(event) => {
        event.preventDefault();
        if (busy) return;
        const form = new FormData(event.currentTarget);
        const label = form.get("label");
        const value = form.get("value");
        if (typeof label !== "string" || typeof value !== "string") return;
        const scope = form.get("scope") === "shared" ? "shared" : scopes[0];
        const location =
          scope === "shared"
            ? { scope, workspaceId }
            : { scope: "personal" as const };
        const verify_config = Object.fromEntries(
          provider.fields.flatMap((field) => {
            const entry = form.get(field);
            return typeof entry === "string" && entry.trim()
              ? [[field, entry.trim()]]
              : [];
          }),
        );
        const save_if_unverified =
          event.nativeEvent instanceof SubmitEvent &&
          event.nativeEvent.submitter?.getAttribute("value") === "save-anyway";
        dispatch({
          kind: "submit",
          location,
          body: {
            provider_kind: provider.kind,
            label,
            value,
            verify: true,
            verify_config,
            save_if_unverified,
          },
        });
      }}
    >
      {scopes.length > 1 && (
        <Select
          aria-label="Credential scope"
          name="scope"
          defaultValue="personal"
          disabled={busy}
          size={size}
        >
          <option value="personal">Personal</option>
          <option value="shared">Shared</option>
        </Select>
      )}
      {providers.length > 1 && (
        <Select
          aria-label="Provider"
          value={provider.kind}
          size={size}
          disabled={busy}
          onChange={(event) => setKind(event.currentTarget.value)}
        >
          {providers.map(({ kind: option }) => (
            <option key={option} value={option}>
              {option.replaceAll("_", " ")}
            </option>
          ))}
        </Select>
      )}
      <TextInput
        name="label"
        aria-label="Credential label"
        placeholder="Label"
        maxLength={160}
        size={size}
        disabled={busy}
        required
      />
      <TextInput
        name="value"
        aria-label="Credential key"
        placeholder="Key"
        type="password"
        size={size}
        autoComplete="off"
        spellCheck={false}
        disabled={busy}
        required
      />
      {provider.fields.map((field) => (
        <TextInput
          key={`${provider.kind}:${field}`}
          name={field}
          size={size}
          type="url"
          aria-label={field.replaceAll("_", " ")}
          placeholder={field.replaceAll("_", " ")}
          defaultValue={provider.defaults?.[field]}
          disabled={busy}
          required={field !== "base_url"}
        />
      ))}
      {state.kind === "failed" && <span role="alert">{state.message}</span>}
      <div {...stylex.props(styles.actions)}>
        <Button type="submit" size="xs" variant="soft" disabled={busy}>
          {busy ? "Verifying…" : "Verify & save"}
        </Button>
        {state.kind === "failed" && state.canSave && (
          <Button type="submit" value="save-anyway" size="xs" variant="soft">
            Save anyway
          </Button>
        )}
        <Button
          type="button"
          size="xs"
          variant="ghost"
          disabled={busy}
          onClick={() => dispatch({ kind: "close" })}
        >
          Cancel
        </Button>
      </div>
    </form>
  );
}
