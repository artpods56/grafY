"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";

import type {
  Credential,
  CredentialVerification,
  NodeCredentialStatus,
} from "@/lib/api";
import {
  CellCredentialsBody,
  CellCredentialsDialog,
  credentialsIntro,
} from "@/features/workbench/cell-canvas/cards/CellCredentialsDialog";
import type { CellSecretInputSpec } from "@/features/workbench/cell-canvas/cell-contracts";
import type { WorkflowNodeSecretState } from "@/features/workbench/authoring/node-secrets";
import { tokens } from "@/lib/stylex/tokens.stylex";

import { SandboxShell } from "../../SandboxShell";

/**
 * Every face of a node's credentials dialog, in one place.
 *
 * The Canvas lab can only reach the inline case, and only with an unsaved node,
 * so the states that need a saved node or a Workspace credential vault cannot
 * be seen there. This draws the product's own dialog body with fixture specs,
 * beside a card whose key button opens the real modal.
 */

const s = stylex.create({
  stage: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "flex-start",
    gap: "24px",
    minHeight: "420px",
  },
  plate: {
    width: "300px",
    minHeight: "150px",
    padding: "12px",
    borderRadius: tokens.radiusLg,
    backgroundColor: tokens.colorSurface,
    boxShadow: `0 0 0 1px ${tokens.colorBorder}, 0 18px 40px rgba(0,0,0,0.35)`,
  },
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "flex-end",
    gap: "6px",
  },
  title: {
    marginRight: "auto",
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeSm,
    fontWeight: 600,
  },
  frame: {
    boxSizing: "border-box",
    width: "min(520px, 100%)",
    display: "grid",
    gap: "12px",
    padding: "16px",
    borderRadius: tokens.radiusLg,
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    backgroundColor: tokens.colorSurface,
  },
  frameTitle: {
    margin: 0,
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeMd,
    fontWeight: 600,
  },
  frameNote: {
    margin: 0,
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
});

const sharedKey: Credential = {
  id: "vault-key",
  scope: "shared",
  provider_kind: "openai_compatible",
  label: "Team gateway",
  key_hint: "••••1234",
  usable: true,
  supports_verification: true,
  verification_status: "valid",
  verification_message: "Verified OpenAI-compatible key.",
  verification_hint: null,
  verified_at: "2026-09-01T10:00:00Z",
  created_at: "2026-09-01T10:00:00Z",
  updated_at: "2026-09-01T10:00:00Z",
};

const personalKey: Credential = {
  ...sharedKey,
  id: "personal-key",
  scope: "personal",
  label: "My laptop key",
  key_hint: "••••9876",
};

const baseStatus: NodeCredentialStatus = {
  node_id: "ask-model",
  name: "api_key",
  configured: true,
  provider_kind: "openai_compatible",
  supports_verification: true,
  effective_source: "shared_credential",
  effective_credential_id: sharedKey.id,
  effective_credential_label: sharedKey.label,
  effective_verification_status: "valid",
  shared_binding_mode: "credential",
  shared_credential_id: sharedKey.id,
  shared_credential_label: sharedKey.label,
  shared_credential_missing: false,
  personal_override_mode: "none",
  personal_credential_id: null,
  deployment_default_available: false,
};

const never = async () => {};

function vault(
  status: Partial<NodeCredentialStatus>,
  over: Partial<NonNullable<CellSecretInputSpec["vault"]>> = {},
): NonNullable<CellSecretInputSpec["vault"]> {
  return {
    workspaceId: "workspace",
    canEditShared: true,
    canSelectPersonal: true,
    canManageShared: false,
    credentials: [sharedKey, personalKey],
    provider: {
      kind: "openai_compatible",
      fields: ["base_url"],
      defaults: { base_url: "https://api.openai.com/v1" },
    },
    select: never,
    verify: async (): Promise<CredentialVerification> => ({
      status: "valid",
      message: "Verified.",
      account_hint: null,
    }),
    refresh: never,
    ...over,
    status: { ...baseStatus, ...status },
  };
}

function inline(state: WorkflowNodeSecretState): CellSecretInputSpec {
  return {
    name: "api_key",
    title: "API key",
    description: "Write-only key for the provider behind this node.",
    state,
    ready: true,
    revision: "rev-1",
  };
}

interface Variant {
  id: string;
  label: string;
  caption: string;
  /** What the key's own status says before anyone touches this fixture. */
  initial: WorkflowNodeSecretState;
  inputs: (state: WorkflowNodeSecretState) => readonly CellSecretInputSpec[];
}

const VARIANTS: readonly Variant[] = [
  {
    id: "needed",
    label: "Inline · not set",
    caption:
      "A node-owned key with nothing saved yet. The header dot is amber: the card says it needs a key at rest.",
    initial: "unconfigured",
    inputs: () => [inline("unconfigured")],
  },
  {
    id: "configured",
    label: "Inline · configured",
    caption:
      "A saved key is never read back. The input becomes “Replace key” and Remove unlocks.",
    initial: "configured",
    inputs: (state) => [inline(state)],
  },
  {
    id: "stale",
    label: "Inline · stale",
    caption:
      "The settings the key is bound to changed, so the old key no longer applies to this node.",
    initial: "stale",
    inputs: () => [inline("stale")],
  },
  {
    id: "error",
    label: "Inline · error",
    caption:
      "The provider refused the pasted key. Its message replaces the hint.",
    initial: "error",
    inputs: () => [
      {
        ...inline("error"),
        message: "The provider returned 401 for that key.",
      },
    ],
  },
  {
    id: "vault-shared",
    label: "Vault · shared key",
    caption:
      "A provider-shaped node in a Workspace with a shared key: the dialog leads with the key that actually runs the node, names the endpoint it is bound to, then the personal override.",
    initial: "configured",
    inputs: () => [{ ...inline("configured"), vault: vault({}) }],
  },
  {
    id: "vault-invalid",
    label: "Vault · invalid key",
    caption:
      "A key the provider refused is an error on the card, not merely “not set”.",
    initial: "configured",
    inputs: () => [
      {
        ...inline("configured"),
        vault: vault({
          effective_verification_status: "invalid",
          effective_source: "personal_credential",
          effective_credential_id: personalKey.id,
          effective_credential_label: personalKey.label,
          personal_override_mode: "credential",
          personal_credential_id: personalKey.id,
        }),
      },
    ],
  },
  {
    id: "vault-missing",
    label: "Vault · shared key gone",
    caption:
      "The graph points at a shared key that was revoked, so the node cannot run until someone picks another.",
    initial: "configured",
    inputs: () => [
      {
        ...inline("configured"),
        vault: vault({
          configured: false,
          effective_verification_status: null,
          effective_source: "shared_credential",
          effective_credential_id: null,
          effective_credential_label: null,
          shared_credential_missing: true,
        }),
      },
    ],
  },
  {
    id: "vault-manage",
    label: "Vault · manage shared",
    caption:
      "With permission to manage the shared key, the dialog also offers the legacy inline key behind a disclosure.",
    initial: "configured",
    inputs: () => [
      {
        ...inline("configured"),
        vault: vault(
          { effective_source: "inline_legacy", effective_credential_id: null },
          { canManageShared: true },
        ),
      },
    ],
  },
  {
    id: "vault-multi",
    label: "Vault · two secrets",
    caption:
      "ocr.export_label_studio declares two keys. Both stack in one dialog, each naming its own endpoint.",
    initial: "configured",
    inputs: () => [
      {
        ...inline("configured"),
        name: "label_studio_token",
        title: "Label Studio API token",
        vault: vault(
          {
            name: "label_studio_token",
            provider_kind: "label_studio",
            shared_credential_label: "Labelling service",
          },
          {
            provider: {
              kind: "label_studio",
              fields: ["label_studio_url"],
              defaults: { label_studio_url: "https://label.example.internal" },
            },
          },
        ),
      },
      {
        ...inline("configured"),
        name: "s3_secret_key",
        title: "MinIO / S3 secret access key",
        vault: vault(
          {
            name: "s3_secret_key",
            provider_kind: "s3",
            supports_verification: false,
            effective_verification_status: null,
            effective_source: "personal_credential",
            effective_credential_id: personalKey.id,
            effective_credential_label: "Bucket writer",
            personal_override_mode: "credential",
            personal_credential_id: personalKey.id,
          },
          {
            provider: { kind: "s3", fields: [] },
          },
        ),
      },
    ],
  },
];

export function CredentialsSpike() {
  const [variant, setVariant] = React.useState<string>(VARIANTS[0]!.id);
  const current = VARIANTS.find((item) => item.id === variant) ?? VARIANTS[0]!;
  const [state, setState] = React.useState<WorkflowNodeSecretState>(
    current.initial,
  );

  const pick = (id: string) => {
    const next = VARIANTS.find((item) => item.id === id);
    setVariant(id);
    setState(next?.initial ?? "unconfigured");
  };

  const inputs = current.inputs(state);
  const apply = async () => {
    setState("applying");
    window.setTimeout(() => setState("configured"), 700);
    return true;
  };
  const remove = async () => {
    setState("removing");
    window.setTimeout(() => setState("unconfigured"), 700);
    return true;
  };

  return (
    <SandboxShell
      title="Node credentials dialog"
      note={current.caption}
      variants={VARIANTS.map(({ id, label }) => ({ id, label }))}
      activeVariant={current.id}
      onVariant={pick}
    >
      <div {...stylex.props(s.stage)}>
        <div {...stylex.props(s.plate)}>
          <div {...stylex.props(s.header)}>
            <span {...stylex.props(s.title)}>Ask a model</span>
            <CellCredentialsDialog
              key={current.id}
              cardId="ask-model"
              cardTitle="Ask a model"
              inputs={inputs}
              onApply={apply}
              onRemove={remove}
            />
          </div>
        </div>
        <div {...stylex.props(s.frame)}>
          <h2 {...stylex.props(s.frameTitle)}>Credentials · Ask a model</h2>
          <p {...stylex.props(s.frameNote)}>{credentialsIntro(inputs)}</p>
          <CellCredentialsBody
            cardId="ask-model"
            inputs={inputs}
            onApply={apply}
            onRemove={remove}
          />
        </div>
      </div>
    </SandboxShell>
  );
}
