"use client";

import * as stylex from "@stylexjs/stylex";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import {
  CredentialForm,
  credentialStatusLabel,
} from "@/features/credentials/CredentialForm";
import { useCredentialAction } from "@/features/credentials/useCredentialAction";
import { reverifyCredential, type NodeCredentialStatus } from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";
import type { NodeCredentialSelection } from "../../authoring/node-secrets";
import type { CellSecretInputSpec } from "../cell-contracts";

const styles = stylex.create({
  input: { display: "grid", gap: "6px" },
  header: {
    display: "flex",
    alignItems: "center",
    gap: "5px",
    flexWrap: "wrap",
  },
  label: { color: tokens.colorText, fontWeight: 600, marginInlineEnd: "auto" },
  badge: {
    borderRadius: tokens.radiusSm,
    paddingBlock: "2px",
    paddingInline: "5px",
    backgroundColor: tokens.colorSurfaceRaised,
    color: tokens.colorText,
    fontSize: tokens.fontSizeXs,
  },
  field: { display: "grid", gap: "3px", fontSize: tokens.fontSizeXs },
  note: { color: tokens.colorSubtle, margin: 0, fontSize: tokens.fontSizeXs },
});

const sourceLabel: Record<NodeCredentialStatus["effective_source"], string> = {
  personal_credential: "Personal",
  shared_credential: "Shared",
  deployment_default: "Server default",
  inline_legacy: "Inline key",
  none: "Not set",
};

type Operation =
  { kind: "verify" } | { kind: "select"; selection: NodeCredentialSelection };

export function CellVaultCredential({ input }: { input: CellSecretInputSpec }) {
  const vault = input.vault;
  const [state, dispatch] = useCredentialAction(
    async (operation: Operation) => {
      if (!vault) return;
      if (operation.kind === "select") {
        await vault.select(operation.selection);
        return;
      }
      const selected = vault.credentials.find(
        (credential) => credential.id === vault.status.effective_credential_id,
      );
      if (
        selected &&
        (selected.scope === "personal" || vault.canManageShared)
      ) {
        const location =
          selected.scope === "shared"
            ? { scope: selected.scope, workspaceId: vault.workspaceId }
            : { scope: selected.scope };
        const result = await reverifyCredential(location, selected.id);
        await vault.refresh();
        return (
          result.verification_message ??
          credentialStatusLabel[result.verification_status]
        );
      }
      return (await vault.verify()).message;
    },
  );
  if (!vault) return null;
  const { status, credentials } = vault;
  const busy = state.kind === "pending";
  const unavailable = !input.ready || busy;
  const shared = credentials.filter(
    (credential) => credential.scope === "shared",
  );
  const sharedValue =
    status.shared_binding_mode === "credential"
      ? `credential:${status.shared_credential_id ?? "missing"}`
      : status.shared_binding_mode;
  const personalValue =
    status.personal_override_mode === "credential"
      ? `credential:${status.personal_credential_id ?? "missing"}`
      : status.personal_override_mode;

  function change(selection: NodeCredentialSelection) {
    dispatch({
      kind: "start",
      id: selection.scope,
      operation: { kind: "select", selection },
    });
  }

  return (
    <section aria-label={input.title} {...stylex.props(styles.input)}>
      <div {...stylex.props(styles.header)}>
        <span {...stylex.props(styles.label)}>{input.title}</span>
        <span {...stylex.props(styles.badge)}>
          {input.ready
            ? sourceLabel[status.effective_source]
            : "Settings changed"}
        </span>
        {input.ready && status.effective_verification_status && (
          <span {...stylex.props(styles.badge)}>
            {credentialStatusLabel[status.effective_verification_status]}
          </span>
        )}
      </div>
      {status.effective_credential_label && input.ready && (
        <p {...stylex.props(styles.note)}>
          {status.effective_credential_label}
        </p>
      )}
      {status.shared_credential_missing && (
        <p role="status" {...stylex.props(styles.note)}>
          The shared credential was removed or is unavailable.
        </p>
      )}
      {!input.ready && (
        <p {...stylex.props(styles.note)}>
          Save the node settings to change its credential.
        </p>
      )}
      {(state.kind === "failed" || state.kind === "complete") && (
        <p
          role={state.kind === "failed" ? "alert" : "status"}
          {...stylex.props(styles.note)}
        >
          {state.message}
        </p>
      )}
      {vault.canSelectPersonal && (
        <label {...stylex.props(styles.field)}>
          My selection
          <Select
            aria-label={`${input.title} personal selection`}
            size="dense"
            value={personalValue}
            disabled={unavailable}
            onChange={(event) => {
              const value = event.currentTarget.value;
              if (
                value === "none" ||
                value === "shared" ||
                value === "deployment_default"
              ) {
                void change({ scope: "personal", binding: { mode: value } });
              } else if (value.startsWith("credential:")) {
                void change({
                  scope: "personal",
                  binding: {
                    mode: "credential",
                    credential_id: value.slice(11),
                  },
                });
              }
            }}
          >
            <option value="none">Use graph setting</option>
            {personalValue === "shared" && (
              <option value="shared">Use shared binding</option>
            )}
            <option
              value="deployment_default"
              disabled={!status.deployment_default_available}
            >
              Server default
            </option>
            {personalValue === "credential:missing" && (
              <option value={personalValue} disabled>
                Selected key unavailable
              </option>
            )}
            {credentials.map((credential) => (
              <option
                key={credential.id}
                value={`credential:${credential.id}`}
                disabled={!credential.usable}
              >
                {credential.scope === "personal" ? "Personal" : "Shared"} ·{" "}
                {credential.label}
              </option>
            ))}
          </Select>
        </label>
      )}
      {vault.canEditShared && (
        <label {...stylex.props(styles.field)}>
          Graph binding
          <Select
            aria-label={`${input.title} graph binding`}
            size="dense"
            value={sharedValue}
            disabled={unavailable}
            onChange={(event) => {
              const value = event.currentTarget.value;
              if (
                value === "none" ||
                value === "personal" ||
                value === "deployment_default"
              ) {
                void change({ scope: "shared", binding: { mode: value } });
              } else if (value.startsWith("credential:")) {
                void change({
                  scope: "shared",
                  binding: {
                    mode: "credential",
                    credential_id: value.slice(11),
                  },
                });
              }
            }}
          >
            <option value="none">No graph binding</option>
            <option value="personal">Require personal</option>
            <option
              value="deployment_default"
              disabled={!status.deployment_default_available}
            >
              Server default
            </option>
            {sharedValue === "credential:missing" && (
              <option value={sharedValue} disabled>
                Shared key unavailable
              </option>
            )}
            {shared.map((credential) => (
              <option
                key={credential.id}
                value={`credential:${credential.id}`}
                disabled={!credential.usable}
              >
                Shared · {credential.label}
              </option>
            ))}
          </Select>
        </label>
      )}
      {vault.canSelectPersonal &&
        status.configured &&
        status.supports_verification && (
          <Button
            type="button"
            size="xs"
            variant="soft"
            disabled={unavailable}
            onClick={() =>
              dispatch({
                kind: "start",
                id: "verify",
                operation: { kind: "verify" },
              })
            }
          >
            {state.kind === "pending" && state.id === "verify"
              ? "Verifying…"
              : "Re-verify"}
          </Button>
        )}
      {input.ready && vault.canSelectPersonal && (
        <CredentialForm
          dense
          workspaceId={vault.workspaceId}
          providers={[vault.provider]}
          scopes={vault.canManageShared ? ["personal", "shared"] : ["personal"]}
          onSaved={vault.refresh}
        />
      )}
    </section>
  );
}
