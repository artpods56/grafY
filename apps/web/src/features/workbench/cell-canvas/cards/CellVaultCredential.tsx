"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  CircleDashed,
  KeyRound,
  LoaderCircle,
  RefreshCw,
  Server,
  User,
  Users,
} from "lucide-react";

import { IconButton } from "@/components/ui/button";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Select } from "@/components/ui/select";
import {
  CredentialBadge,
  CredentialCallout,
  VerificationBadge,
} from "@/features/credentials/CredentialBadge";
import { CredentialForm } from "@/features/credentials/CredentialForm";
import {
  credentialFieldLabel,
  credentialSourceDescription,
  credentialSourceLabel,
  credentialStatusLabel,
  providerDisplayName,
  type CredentialSource,
} from "@/features/credentials/credential-display";
import { useCredentialAction } from "@/features/credentials/useCredentialAction";
import {
  reverifyCredential,
  type Credential,
  type NodeCredentialStatus,
} from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";
import type { NodeCredentialSelection } from "../../authoring/node-secrets";
import type { CellSecretInputSpec } from "../cell-contracts";

const spin = stylex.keyframes({
  from: { transform: "rotate(0deg)" },
  to: { transform: "rotate(360deg)" },
});

const styles = stylex.create({
  slot: { display: "grid", gap: "12px", minWidth: 0 },
  header: {
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "10px",
  },
  title: {
    minWidth: 0,
    overflow: "hidden",
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeMd,
    fontWeight: 600,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  /** The key that runs this node now: the answer the dialog leads with. */
  summary: {
    minWidth: 0,
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) auto",
    alignItems: "center",
    columnGap: "8px",
    rowGap: "5px",
    padding: "10px 10px 10px 12px",
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorHover,
    boxShadow: `inset 0 0 0 1px ${tokens.colorDivider}`,
  },
  summaryMain: {
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    gap: "8px",
  },
  summaryLabel: {
    minWidth: 0,
    overflow: "hidden",
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeMd,
    fontWeight: 600,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  summaryLabelEmpty: { color: tokens.colorMuted, fontWeight: 500 },
  summaryAside: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
  },
  summaryDetail: {
    gridColumn: "1 / -1",
    minWidth: 0,
    margin: 0,
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
  /** The config the stored key is bound to, read-only above the picker. */
  binding: {
    margin: 0,
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
    overflowWrap: "anywhere",
  },
  hint: {
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    letterSpacing: "0.02em",
  },
  picker: { display: "grid", gap: "8px", minWidth: 0 },
  scopeLabel: {
    margin: 0,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    fontWeight: 600,
  },
  helper: {
    margin: 0,
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
  note: {
    margin: 0,
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
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

const SOURCE_ICON: Record<CredentialSource, typeof User> = {
  personal_credential: User,
  shared_credential: Users,
  deployment_default: Server,
  inline_legacy: KeyRound,
  none: CircleDashed,
};

type PickerScope = "personal" | "shared";

const SCOPE_TAB: Record<PickerScope, string> = {
  personal: "My run",
  shared: "Graph default",
};

const SCOPE_HELP: Record<PickerScope, string> = {
  personal: "Overrides only your runs.",
  shared: "Default for everyone who runs this graph.",
};

type Operation =
  | { kind: "verify" }
  | { kind: "select"; selection: NodeCredentialSelection }
  | { kind: "adopt"; credential: Credential };

/** An option's words: its label, its key's last characters, and a warning. */
function credentialOption(credential: Credential): string {
  const parts = [credential.label];
  if (credential.key_hint) parts.push(credential.key_hint);
  if (!credential.usable) parts.push("unavailable");
  else if (
    credential.verification_status === "invalid" ||
    credential.verification_status === "egress_blocked"
  ) {
    parts.push(credentialStatusLabel[credential.verification_status]);
  }
  return parts.join(" · ");
}

function bindingValue(
  mode: string,
  credentialId: string | null | undefined,
): string {
  return mode === "credential"
    ? `credential:${credentialId ?? "missing"}`
    : mode;
}

function summaryLabel(status: NodeCredentialStatus): string | null {
  if (status.effective_credential_label)
    return status.effective_credential_label;
  switch (status.effective_source) {
    case "deployment_default":
      return "Server's own key";
    case "inline_legacy":
      return "Key saved on this node";
    case "none":
      return null;
    default:
      return "Selected key";
  }
}

/**
 * One vault-backed key of a node: which key runs it now and whose it is, the
 * picker for the person's own runs or the graph's default, and an inline form
 * that adds a key and selects it in one go.
 */
export function CellVaultCredential({ input }: { input: CellSecretInputSpec }) {
  const vault = input.vault;
  const [tab, setTab] = React.useState<PickerScope>(
    vault && !vault.canSelectPersonal ? "shared" : "personal",
  );
  const [state, dispatch] = useCredentialAction(
    async (operation: Operation) => {
      if (!vault) return;
      if (operation.kind === "select") {
        await vault.select(operation.selection);
        return;
      }
      if (operation.kind === "adopt") {
        const { credential } = operation;
        // A new Shared key becomes the graph's default when this person may
        // set it, and their own override steps aside so the card runs it.
        if (credential.scope === "shared" && vault.canEditShared) {
          await vault.select({
            scope: "shared",
            binding: { mode: "credential", credential_id: credential.id },
          });
          if (
            vault.canSelectPersonal &&
            vault.status.personal_override_mode !== "none"
          ) {
            await vault.select({
              scope: "personal",
              binding: { mode: "none" },
            });
          }
        } else if (vault.canSelectPersonal) {
          await vault.select({
            scope: "personal",
            binding: { mode: "credential", credential_id: credential.id },
          });
        }
        await vault.refresh();
        return `Now using “${credential.label}”.`;
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
  const verifying = busy && state.id === "verify";
  const effective = credentials.find(
    (credential) => credential.id === status.effective_credential_id,
  );
  const personal = credentials.filter(
    (credential) => credential.scope === "personal",
  );
  const shared = credentials.filter(
    (credential) => credential.scope === "shared",
  );
  const sharedValue = bindingValue(
    status.shared_binding_mode,
    status.shared_credential_id,
  );
  const personalValue = bindingValue(
    status.personal_override_mode,
    status.personal_credential_id,
  );
  const scopes: PickerScope[] = [
    ...(vault.canSelectPersonal ? (["personal"] as const) : []),
    ...(vault.canEditShared ? (["shared"] as const) : []),
  ];
  const activeTab = scopes.includes(tab) ? tab : scopes[0];
  const source = status.effective_source;
  const SourceIcon = SOURCE_ICON[source];
  const label = input.ready ? summaryLabel(status) : null;
  const canReverify =
    input.ready &&
    vault.canSelectPersonal &&
    status.configured &&
    status.supports_verification;
  const graphDefault =
    status.shared_binding_mode === "credential"
      ? status.shared_credential_label
      : status.shared_binding_mode === "deployment_default"
        ? "server"
        : status.shared_binding_mode === "personal"
          ? "your own key"
          : null;

  const boundFields = Object.entries(vault.provider.defaults ?? {}).filter(
    ([, value]) => value.trim().length > 0,
  );

  function change(selection: NodeCredentialSelection) {
    dispatch({
      kind: "start",
      id: selection.scope,
      operation: { kind: "select", selection },
    });
  }

  return (
    <section
      aria-label={input.title}
      data-vault-credential={input.name}
      {...stylex.props(styles.slot)}
    >
      <div {...stylex.props(styles.header)}>
        <span {...stylex.props(styles.title)}>{input.title}</span>
        <CredentialBadge tone="outline">
          {providerDisplayName(vault.provider.kind)}
        </CredentialBadge>
      </div>
      {boundFields.length > 0 && (
        <p data-credential-bindings="true" {...stylex.props(styles.binding)}>
          {boundFields.map(([field, value], index) => (
            <React.Fragment key={field}>
              {index > 0 ? " · " : null}
              {credentialFieldLabel(field)}:{" "}
              <span {...stylex.props(styles.hint)}>{value}</span>
            </React.Fragment>
          ))}
        </p>
      )}

      <div data-credential-source={source} {...stylex.props(styles.summary)}>
        <div {...stylex.props(styles.summaryMain)}>
          <CredentialBadge
            tone="outline"
            title={credentialSourceDescription[source]}
            icon={<SourceIcon size={11} aria-hidden="true" />}
          >
            {input.ready ? credentialSourceLabel[source] : "Settings changed"}
          </CredentialBadge>
          <span
            title={label ?? undefined}
            {...stylex.props(
              styles.summaryLabel,
              label ? null : styles.summaryLabelEmpty,
            )}
          >
            {label ?? (input.ready ? "No key selected" : "Save node first")}
          </span>
        </div>
        <div {...stylex.props(styles.summaryAside)}>
          {input.ready && status.effective_verification_status && (
            <VerificationBadge status={status.effective_verification_status} />
          )}
          {canReverify && (
            <IconButton
              label={`Re-verify ${input.title}`}
              title="Re-verify with the provider"
              size="sm"
              variant="ghost"
              disabled={unavailable}
              onClick={() =>
                dispatch({
                  kind: "start",
                  id: "verify",
                  operation: { kind: "verify" },
                })
              }
            >
              {verifying ? (
                <LoaderCircle
                  size={14}
                  aria-hidden="true"
                  {...stylex.props(styles.spinner)}
                />
              ) : (
                <RefreshCw size={14} aria-hidden="true" />
              )}
            </IconButton>
          )}
        </div>
        <p {...stylex.props(styles.summaryDetail)}>
          {!input.ready ? (
            "Save the node settings to change its credential."
          ) : effective?.key_hint ? (
            <>
              <span {...stylex.props(styles.hint)}>{effective.key_hint}</span>
              {" · "}
              {credentialSourceDescription[source]}
            </>
          ) : (
            credentialSourceDescription[source]
          )}
        </p>
      </div>

      {status.shared_credential_missing && (
        <CredentialCallout tone="danger" title="Shared key missing">
          The graph&apos;s shared key was removed or is unavailable.
        </CredentialCallout>
      )}
      {state.kind === "failed" && (
        <CredentialCallout tone="danger" title="Failed">
          {state.message}
        </CredentialCallout>
      )}
      {state.kind === "complete" && (
        <p role="status" {...stylex.props(styles.note)}>
          {state.message}
        </p>
      )}

      {activeTab && (
        <div {...stylex.props(styles.picker)}>
          {scopes.length > 1 ? (
            <SegmentedControl
              size="md"
              aria-label={`${input.title} selection scope`}
              value={activeTab}
              options={scopes.map((scope) => ({
                value: scope,
                label: SCOPE_TAB[scope],
              }))}
              onValueChange={setTab}
            />
          ) : (
            <p {...stylex.props(styles.scopeLabel)}>{SCOPE_TAB[activeTab]}</p>
          )}
          {activeTab === "personal" ? (
            <Select
              aria-label={`${input.title} personal selection`}
              value={personalValue}
              disabled={unavailable}
              onChange={(event) => {
                const value = event.currentTarget.value;
                if (
                  value === "none" ||
                  value === "shared" ||
                  value === "deployment_default"
                ) {
                  change({ scope: "personal", binding: { mode: value } });
                } else if (value.startsWith("credential:")) {
                  change({
                    scope: "personal",
                    binding: {
                      mode: "credential",
                      credential_id: value.slice(11),
                    },
                  });
                }
              }}
            >
              <optgroup label="Default">
                <option value="none">
                  {graphDefault
                    ? `Use graph default · ${graphDefault}`
                    : "Use graph default"}
                </option>
                {personalValue === "shared" && (
                  <option value="shared">Use shared binding</option>
                )}
                <option
                  value="deployment_default"
                  disabled={!status.deployment_default_available}
                >
                  Server default
                  {status.deployment_default_available ? "" : " · unavailable"}
                </option>
              </optgroup>
              {personalValue === "credential:missing" && (
                <option value={personalValue} disabled>
                  Selected key unavailable
                </option>
              )}
              {personal.length > 0 && (
                <optgroup label="Personal (only you)">
                  {personal.map((credential) => (
                    <option
                      key={credential.id}
                      value={`credential:${credential.id}`}
                      disabled={!credential.usable}
                    >
                      {credentialOption(credential)}
                    </option>
                  ))}
                </optgroup>
              )}
              {shared.length > 0 && (
                <optgroup label="Shared (workspace)">
                  {shared.map((credential) => (
                    <option
                      key={credential.id}
                      value={`credential:${credential.id}`}
                      disabled={!credential.usable}
                    >
                      {credentialOption(credential)}
                    </option>
                  ))}
                </optgroup>
              )}
            </Select>
          ) : (
            <Select
              aria-label={`${input.title} graph binding`}
              value={sharedValue}
              disabled={unavailable}
              onChange={(event) => {
                const value = event.currentTarget.value;
                if (
                  value === "none" ||
                  value === "personal" ||
                  value === "deployment_default"
                ) {
                  change({ scope: "shared", binding: { mode: value } });
                } else if (value.startsWith("credential:")) {
                  change({
                    scope: "shared",
                    binding: {
                      mode: "credential",
                      credential_id: value.slice(11),
                    },
                  });
                }
              }}
            >
              <optgroup label="Default">
                <option value="none">No graph default</option>
                <option value="personal">Each person&apos;s own key</option>
                <option
                  value="deployment_default"
                  disabled={!status.deployment_default_available}
                >
                  Server default
                  {status.deployment_default_available ? "" : " · unavailable"}
                </option>
              </optgroup>
              {sharedValue === "credential:missing" && (
                <option value={sharedValue} disabled>
                  Shared key unavailable
                </option>
              )}
              {shared.length > 0 && (
                <optgroup label="Shared (workspace)">
                  {shared.map((credential) => (
                    <option
                      key={credential.id}
                      value={`credential:${credential.id}`}
                      disabled={!credential.usable}
                    >
                      {credentialOption(credential)}
                    </option>
                  ))}
                </optgroup>
              )}
            </Select>
          )}
          <p {...stylex.props(styles.helper)}>{SCOPE_HELP[activeTab]}</p>
        </div>
      )}

      {input.ready && vault.canSelectPersonal && (
        <CredentialForm
          layout="stack"
          workspaceId={vault.workspaceId}
          keyLabel={input.title}
          providers={[
            {
              ...vault.provider,
              supportsVerification: status.supports_verification,
            },
          ]}
          scopes={vault.canManageShared ? ["personal", "shared"] : ["personal"]}
          onSaved={async (credential) => {
            dispatch({
              kind: "start",
              id: "adopt",
              operation: { kind: "adopt", credential },
            });
          }}
        />
      )}
    </section>
  );
}
