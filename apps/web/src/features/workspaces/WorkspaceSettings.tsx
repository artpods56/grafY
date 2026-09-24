"use client";

import * as React from "react";
import {
  Check,
  Clipboard,
  Clock3,
  KeyRound,
  Library,
  Trash2,
  Users,
  Workflow,
} from "lucide-react";
import useSWR from "swr";

import {
  createPersonalAccessToken,
  listPersonalAccessTokens,
  revokePersonalAccessToken,
  type PersonalAccessToken,
  type PersonalAccessTokenCreateRequest,
} from "@/lib/api";
import { ApiError } from "@/lib/api/client";
import {
  useWorkspaceContext,
  workspaceCanManageMembers,
  workspaceDisplayName,
} from "./WorkspaceLayout";
import { WorkspaceLibraryDialog } from "./WorkspaceLibraryDialog";
import { WorkspaceMembersDialog } from "./WorkspaceMembersDialog";

type ExpiryDays = "1" | "7" | "30";
type TokenPurpose = "graph-automation" | "plugin-publishing";

type TokenPurposeOption = {
  id: TokenPurpose;
  label: string;
  defaultTokenLabel: string;
  scopes: PersonalAccessTokenCreateRequest["scopes"];
};

const tokenPurposeOptions = [
  {
    id: "graph-automation",
    label: "Graph automation",
    defaultTokenLabel: "Graph automation",
    scopes: [
      "view_graph",
      "view_artifacts",
      "view_materializations",
      "view_history",
      "view_execution",
      "create_graph",
      "edit_graph",
      "checkpoint_graph",
      "execute_graph",
      "cancel_execution",
      "manage_secrets",
    ],
  },
  {
    id: "plugin-publishing",
    label: "Plugin publishing",
    defaultTokenLabel: "Plugin publishing",
    scopes: ["publish_plugin"],
  },
] satisfies readonly TokenPurposeOption[];

const dayInMilliseconds = 24 * 60 * 60 * 1_000;
const dateFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

function formatTimestamp(value: string): string {
  return dateFormatter.format(new Date(value));
}

function tokenState(
  token: PersonalAccessToken,
  now: number,
): { label: string; state: "active" | "expired" | "revoked" } {
  if (token.revoked_at) return { label: "Revoked", state: "revoked" };
  if (Date.parse(token.expires_at) <= now) {
    return { label: "Expired", state: "expired" };
  }
  return { label: "Active", state: "active" };
}

export function WorkspaceSettings() {
  const { workspace } = useWorkspaceContext();
  const canManageMembers = workspaceCanManageMembers(workspace);
  const label = workspaceDisplayName(workspace);
  const availableTokenPurposes = tokenPurposeOptions.filter((purpose) =>
    purpose.scopes.every((scope) => workspace.capabilities.includes(scope)),
  );
  const {
    data: tokens,
    error: tokensError,
    isLoading: tokensLoading,
    mutate: mutateTokens,
  } = useSWR(["personal-access-tokens", workspace.id], ([, workspaceId]) =>
    listPersonalAccessTokens(workspaceId),
  );
  const [tokenPurpose, setTokenPurpose] = React.useState<TokenPurpose>(
    () => availableTokenPurposes[0]?.id ?? "graph-automation",
  );
  const selectedTokenPurpose =
    availableTokenPurposes.find((purpose) => purpose.id === tokenPurpose) ??
    availableTokenPurposes[0] ??
    null;
  const [tokenLabel, setTokenLabel] = React.useState(
    () => availableTokenPurposes[0]?.defaultTokenLabel ?? "",
  );
  const [expiryDays, setExpiryDays] = React.useState<ExpiryDays>("7");
  const [creating, setCreating] = React.useState(false);
  const [revokingId, setRevokingId] = React.useState<string | null>(null);
  const [message, setMessage] = React.useState<string | null>(null);
  const [createdToken, setCreatedToken] = React.useState<{
    label: string;
    token: string;
  } | null>(null);
  const [copied, setCopied] = React.useState(false);
  const [renderedAt] = React.useState(Date.now);

  const createToken = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedLabel = tokenLabel.trim();
    if (!normalizedLabel || !selectedTokenPurpose) return;
    setCreating(true);
    setMessage(null);
    setCreatedToken(null);
    setCopied(false);
    try {
      const created = await createPersonalAccessToken(workspace.id, {
        label: normalizedLabel,
        scopes: selectedTokenPurpose.scopes,
        expires_at: new Date(
          Date.now() + Number(expiryDays) * dayInMilliseconds,
        ).toISOString(),
      });
      setCreatedToken({ label: created.label, token: created.token });
      await mutateTokens(
        (current) => (current ? [created, ...current] : [created]),
        { revalidate: false },
      );
    } catch (error) {
      setMessage(
        error instanceof ApiError && error.status === 422
          ? error.detail
          : "The token could not be created.",
      );
    } finally {
      setCreating(false);
    }
  };

  const copyToken = async () => {
    if (!createdToken) return;
    try {
      await navigator.clipboard.writeText(createdToken.token);
      setCopied(true);
    } catch {
      setMessage("The token could not be copied. Select it and copy manually.");
    }
  };

  const revokeToken = async (token: PersonalAccessToken) => {
    if (
      !window.confirm(
        `Revoke “${token.label}”? Anything using this token will stop working.`,
      )
    ) {
      return;
    }
    setRevokingId(token.id);
    setMessage(null);
    try {
      await revokePersonalAccessToken(workspace.id, token.id);
      await mutateTokens();
    } catch {
      setMessage("The token could not be revoked.");
    } finally {
      setRevokingId(null);
    }
  };

  return (
    <main className="grafy-workspace-settings">
      <header className="grafy-workspace-settings__header">
        <p className="grafy-workspace-overview__eyebrow">Workspace</p>
        <h1>Settings</h1>
        <p>
          Configuration and access for <strong>{label}</strong>.
        </p>
      </header>

      <section
        className="grafy-workspace-settings__section"
        aria-labelledby="workspace-details-heading"
      >
        <div className="grafy-workspace-settings__section-heading">
          <div>
            <h2 id="workspace-details-heading">Workspace details</h2>
            <p>The active location these settings apply to.</p>
          </div>
          <Workflow size={18} aria-hidden="true" />
        </div>
        <dl className="grafy-workspace-settings__details">
          <div>
            <dt>Name</dt>
            <dd>{label}</dd>
          </div>
          <div>
            <dt>Type</dt>
            <dd>{workspace.kind === "personal" ? "Personal" : "Shared"}</dd>
          </div>
          <div>
            <dt>Your role</dt>
            <dd>{workspace.role}</dd>
          </div>
        </dl>
      </section>

      {workspace.kind === "shared" ? (
        <section
          className="grafy-workspace-settings__section"
          aria-labelledby="workspace-access-heading"
        >
          <div className="grafy-workspace-settings__section-heading">
            <div>
              <h2 id="workspace-access-heading">Members and access</h2>
              <p>
                Control who can work in this workspace and what they can do.
              </p>
            </div>
            <Users size={18} aria-hidden="true" />
          </div>
          <div className="grafy-workspace-settings__section-action">
            <span>
              {canManageMembers
                ? "Invite people, change roles, or remove access."
                : "Only workspace owners can change member access."}
            </span>
            {canManageMembers ? <WorkspaceMembersDialog /> : null}
          </div>
        </section>
      ) : null}

      <section
        className="grafy-workspace-settings__section"
        aria-labelledby="workspace-token-heading"
      >
        <div className="grafy-workspace-settings__section-heading">
          <div>
            <h2 id="workspace-token-heading">Personal access tokens</h2>
            <p>
              Authenticate command-line and agent workflows without using your
              browser session.
            </p>
          </div>
          <KeyRound size={18} aria-hidden="true" />
        </div>

        {selectedTokenPurpose ? (
          <form
            className="grafy-workspace-settings__token-form"
            onSubmit={(event) => void createToken(event)}
          >
            <label>
              Label
              <input
                value={tokenLabel}
                maxLength={160}
                onChange={(event) => setTokenLabel(event.currentTarget.value)}
              />
            </label>
            <label>
              Purpose
              <select
                value={selectedTokenPurpose.id}
                onChange={(event) => {
                  const purpose = availableTokenPurposes.find(
                    (option) => option.id === event.currentTarget.value,
                  );
                  if (!purpose) return;
                  setTokenPurpose(purpose.id);
                  setTokenLabel(purpose.defaultTokenLabel);
                }}
              >
                {availableTokenPurposes.map((purpose) => (
                  <option key={purpose.id} value={purpose.id}>
                    {purpose.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Expires in
              <select
                value={expiryDays}
                onChange={(event) => {
                  const value = event.currentTarget.value;
                  if (value === "1" || value === "7" || value === "30") {
                    setExpiryDays(value);
                  }
                }}
              >
                <option value="1">1 day</option>
                <option value="7">7 days</option>
                <option value="30">30 days</option>
              </select>
            </label>
            <button
              type="submit"
              className="grafy-workspace-button grafy-workspace-button--primary"
              disabled={creating || tokenLabel.trim() === ""}
            >
              {creating ? "Creating…" : "Create token"}
            </button>
          </form>
        ) : (
          <p className="grafy-workspace-settings__muted">
            Your role does not allow the supported automation workflows in this
            workspace.
          </p>
        )}

        {createdToken ? (
          <div
            className="grafy-workspace-settings__created-token"
            role="status"
          >
            <div>
              <strong>Copy this token now</strong>
              <span>
                {createdToken.label} will not be shown again after you leave
                this page.
              </span>
            </div>
            <div className="grafy-workspace-settings__token-secret">
              <code>{createdToken.token}</code>
              <button
                type="button"
                className="grafy-workspace-settings__icon-button"
                aria-label="Copy personal access token"
                title="Copy token"
                onClick={() => void copyToken()}
              >
                {copied ? (
                  <Check size={16} aria-hidden="true" />
                ) : (
                  <Clipboard size={16} aria-hidden="true" />
                )}
              </button>
            </div>
          </div>
        ) : null}

        {message ? (
          <p className="grafy-member-message" role="status">
            {message}
          </p>
        ) : null}

        <div className="grafy-workspace-settings__token-list">
          {tokensLoading ? (
            <p className="grafy-workspace-settings__muted">Loading tokens…</p>
          ) : tokensError ? (
            <div
              className="grafy-workspace-settings__inline-error"
              role="alert"
            >
              <span>Tokens could not be loaded.</span>
              <button
                type="button"
                className="grafy-workspace-button"
                onClick={() => void mutateTokens()}
              >
                Retry
              </button>
            </div>
          ) : tokens?.length ? (
            tokens.map((token) => {
              const status = tokenState(token, renderedAt);
              return (
                <div
                  className="grafy-workspace-settings__token-row"
                  key={token.id}
                >
                  <div className="grafy-workspace-settings__token-row-main">
                    <div>
                      <strong>{token.label}</strong>
                      <span
                        className="grafy-workspace-settings__token-status"
                        data-state={status.state}
                      >
                        {status.label}
                      </span>
                    </div>
                    <code>{token.public_prefix}…</code>
                  </div>
                  <div className="grafy-workspace-settings__token-meta">
                    <span>
                      <Clock3 size={13} aria-hidden="true" /> Expires{" "}
                      {formatTimestamp(token.expires_at)}
                    </span>
                    <span>{token.scopes.join(", ")}</span>
                  </div>
                  <button
                    type="button"
                    className="grafy-workspace-settings__icon-button grafy-workspace-settings__icon-button--danger"
                    aria-label={`Revoke ${token.label}`}
                    title="Revoke token"
                    disabled={
                      status.state !== "active" || revokingId === token.id
                    }
                    onClick={() => void revokeToken(token)}
                  >
                    <Trash2 size={15} aria-hidden="true" />
                  </button>
                </div>
              );
            })
          ) : (
            <p className="grafy-workspace-settings__muted">
              No personal access tokens for this workspace.
            </p>
          )}
        </div>
      </section>

      <section
        className="grafy-workspace-settings__section"
        aria-labelledby="workspace-library-heading"
      >
        <div className="grafy-workspace-settings__section-heading">
          <div>
            <h2 id="workspace-library-heading">Module library</h2>
            <p>Review reusable graph modules available in this workspace.</p>
          </div>
          <Library size={18} aria-hidden="true" />
        </div>
        <div className="grafy-workspace-settings__section-action">
          <span>Manage modules published for this workspace.</span>
          <WorkspaceLibraryDialog
            workspace={workspace}
            triggerLabel="Open library"
          />
        </div>
      </section>
    </main>
  );
}
