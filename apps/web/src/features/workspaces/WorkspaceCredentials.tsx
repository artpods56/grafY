"use client";

import * as stylex from "@stylexjs/stylex";
import useSWR from "swr";

import { Button } from "@/components/ui/button";
import {
  CredentialForm,
  credentialStatusLabel,
  type CredentialProvider,
} from "@/features/credentials/CredentialForm";
import { useCredentialAction } from "@/features/credentials/useCredentialAction";
import { useNodeRegistry } from "@/hooks/use-api";
import {
  deleteCredential,
  listCredentials,
  reverifyCredential,
  type CredentialScope,
} from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";

const styles = stylex.create({
  layout: { display: "grid", gap: "12px" },
  rows: {
    display: "grid",
    gap: "8px",
    margin: 0,
    padding: 0,
    listStyle: "none",
  },
  row: {
    display: "flex",
    gap: "12px",
    alignItems: "center",
    justifyContent: "space-between",
    flexWrap: "wrap",
  },
  description: { display: "grid", gap: "2px" },
  meta: { color: tokens.colorSubtle, fontSize: tokens.fontSizeXs },
  actions: { display: "flex", gap: "6px" },
});

function CredentialList({
  workspaceId,
  scope,
  canManage,
  providers,
}: {
  workspaceId: string;
  scope: CredentialScope;
  canManage: boolean;
  providers: readonly CredentialProvider[];
}) {
  const location = scope === "shared" ? { scope, workspaceId } : { scope };
  const { data, error, isLoading, mutate } = useSWR(
    ["provider-credentials", scope, workspaceId],
    () => listCredentials(location),
  );
  const [state, dispatch] = useCredentialAction(
    async (operation: { kind: "verify" | "delete"; id: string }) => {
      if (operation.kind === "delete") {
        await deleteCredential(location, operation.id);
        await mutate();
        return;
      }
      const updated = await reverifyCredential(location, operation.id);
      await mutate();
      return (
        updated.verification_message ??
        credentialStatusLabel[updated.verification_status]
      );
    },
  );

  return (
    <div {...stylex.props(styles.layout)}>
      <h3>
        {scope === "personal"
          ? "Personal credentials"
          : "Shared workspace credentials"}
      </h3>
      {isLoading && <span role="status">Loading credentials…</span>}
      {error && <span role="alert">Credentials could not be loaded.</span>}
      {data?.length === 0 && <span>No credentials saved.</span>}
      {data && data.length > 0 && (
        <ul {...stylex.props(styles.rows)}>
          {data.map((row) => (
            <li key={row.id} {...stylex.props(styles.row)}>
              <div {...stylex.props(styles.description)}>
                <strong>{row.label}</strong>
                <span {...stylex.props(styles.meta)}>
                  {row.provider_kind.replaceAll("_", " ")} ·{" "}
                  {row.key_hint && `${row.key_hint} · `}
                  {row.usable
                    ? credentialStatusLabel[row.verification_status]
                    : "Unavailable"}
                  {row.verification_hint && ` · ${row.verification_hint}`}
                </span>
                {row.verification_message && (
                  <span {...stylex.props(styles.meta)}>
                    {row.verification_message}
                  </span>
                )}
              </div>
              {canManage && (
                <div {...stylex.props(styles.actions)}>
                  <Button
                    size="xs"
                    variant="soft"
                    disabled={
                      state.kind === "pending" ||
                      !row.usable ||
                      !row.supports_verification
                    }
                    aria-label={`Re-verify ${row.label}`}
                    onClick={() =>
                      dispatch({
                        kind: "start",
                        id: row.id,
                        operation: { kind: "verify", id: row.id },
                      })
                    }
                  >
                    Re-verify
                  </Button>
                  <Button
                    size="xs"
                    variant="danger"
                    disabled={state.kind === "pending"}
                    aria-label={`Delete ${row.label}`}
                    onClick={() =>
                      dispatch({
                        kind: "start",
                        id: row.id,
                        operation: { kind: "delete", id: row.id },
                      })
                    }
                  >
                    Delete
                  </Button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {state.kind === "failed" && <span role="alert">{state.message}</span>}
      {state.kind === "complete" && <span role="status">{state.message}</span>}
      {canManage && (
        <CredentialForm
          workspaceId={workspaceId}
          providers={providers}
          scopes={[scope]}
          onSaved={() => mutate()}
        />
      )}
    </div>
  );
}

export function WorkspaceCredentials({
  workspaceId,
  canManageShared,
  canViewShared,
}: {
  workspaceId: string;
  canManageShared: boolean;
  canViewShared: boolean;
}) {
  const { data: registry } = useNodeRegistry(workspaceId);
  const byKind = new Map<string, Set<string>>();
  for (const node of registry?.nodes ?? []) {
    for (const input of node.secret_inputs ?? []) {
      const fields = byKind.get(input.provider_kind) ?? new Set<string>();
      for (const field of input.config_dependencies) fields.add(field);
      byKind.set(input.provider_kind, fields);
    }
  }
  const providers = Array.from(byKind, ([kind, fields]) => ({
    kind,
    fields: [...fields],
  })).sort((left, right) => left.kind.localeCompare(right.kind));
  return (
    <section aria-label="Credentials" {...stylex.props(styles.layout)}>
      <h2>Credentials</h2>
      <CredentialList
        workspaceId={workspaceId}
        providers={providers}
        scope="personal"
        canManage
      />
      {canViewShared && (
        <CredentialList
          workspaceId={workspaceId}
          providers={providers}
          scope="shared"
          canManage={canManageShared}
        />
      )}
    </section>
  );
}
