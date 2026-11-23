"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  Check,
  Clipboard,
  Clock3,
  KeyRound,
  Trash2,
  Users,
  Workflow,
} from "lucide-react";
import useSWR from "swr";

import { Button, IconButton } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Select } from "@/components/ui/select";
import { Notice } from "@/components/ui/notice";
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
import { WorkspacePacks } from "./WorkspacePacks";
import { WorkspaceCredentials } from "./WorkspaceCredentials";
import { WorkspaceMembersDialog } from "./WorkspaceMembersDialog";
import { workspaceSettingsStyles as settings } from "./workspace-settings.styles";

type ExpiryDays = "1" | "7" | "30";
type TokenPurpose = "graph-automation" | "module-publishing";

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
      "view_project",
      "view_artifacts",
      "view_runs",
      "create_project",
      "edit_project",
      "checkpoint_project",
      "start_run",
      "cancel_run",
      "manage_secrets",
    ],
  },
  {
    id: "module-publishing",
    label: "Module publishing",
    defaultTokenLabel: "Module publishing",
    scopes: ["edit_project"],
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
    <main {...stylex.props(settings.main)}>
      <header {...stylex.props(settings.header)}>
        <p {...stylex.props(settings.eyebrow)}>Workspace</p>
        <h1 {...stylex.props(settings.headerTitle)}>Settings</h1>
        <p {...stylex.props(settings.headerText)}>
          Configuration and access for{" "}
          <strong {...stylex.props(settings.headerStrong)}>{label}</strong>.
        </p>
      </header>

      <section
        {...stylex.props(settings.section)}
        aria-labelledby="workspace-details-heading"
      >
        <div {...stylex.props(settings.sectionHeading)}>
          <div>
            <h2
              id="workspace-details-heading"
              {...stylex.props(settings.headingTitle)}
            >
              Workspace details
            </h2>
            <p {...stylex.props(settings.headingText)}>
              The active location these settings apply to.
            </p>
          </div>
          <Workflow
            size={18}
            aria-hidden="true"
            {...stylex.props(settings.headingIcon)}
          />
        </div>
        <dl {...stylex.props(settings.details)}>
          <div {...stylex.props(settings.detailsRow)}>
            <dt {...stylex.props(settings.detailsTerm)}>Name</dt>
            <dd {...stylex.props(settings.detailsValue)}>{label}</dd>
          </div>
          <div {...stylex.props(settings.detailsRow)}>
            <dt {...stylex.props(settings.detailsTerm)}>Type</dt>
            <dd {...stylex.props(settings.detailsValue)}>
              {workspace.kind === "personal" ? "Personal" : "Shared"}
            </dd>
          </div>
          <div {...stylex.props(settings.detailsRow)}>
            <dt {...stylex.props(settings.detailsTerm)}>Your role</dt>
            <dd {...stylex.props(settings.detailsValue)}>{workspace.role}</dd>
          </div>
        </dl>
      </section>

      {workspace.kind === "shared" ? (
        <section
          {...stylex.props(settings.section)}
          aria-labelledby="workspace-access-heading"
        >
          <div {...stylex.props(settings.sectionHeading)}>
            <div>
              <h2
                id="workspace-access-heading"
                {...stylex.props(settings.headingTitle)}
              >
                Members and access
              </h2>
              <p {...stylex.props(settings.headingText)}>
                Control who can work in this workspace and what they can do.
              </p>
            </div>
            <Users
              size={18}
              aria-hidden="true"
              {...stylex.props(settings.headingIcon)}
            />
          </div>
          <div {...stylex.props(settings.sectionAction)}>
            <span {...stylex.props(settings.sectionActionText)}>
              {canManageMembers
                ? "Invite people, change roles, or remove access."
                : "Only workspace owners can change member access."}
            </span>
            {canManageMembers ? <WorkspaceMembersDialog /> : null}
          </div>
        </section>
      ) : null}

      <section
        {...stylex.props(settings.section)}
        aria-labelledby="workspace-token-heading"
      >
        <div {...stylex.props(settings.sectionHeading)}>
          <div>
            <h2
              id="workspace-token-heading"
              {...stylex.props(settings.headingTitle)}
            >
              Personal access tokens
            </h2>
            <p {...stylex.props(settings.headingText)}>
              Authenticate command-line and agent workflows without using your
              browser session.
            </p>
          </div>
          <KeyRound
            size={18}
            aria-hidden="true"
            {...stylex.props(settings.headingIcon)}
          />
        </div>

        {selectedTokenPurpose ? (
          <form
            {...stylex.props(settings.tokenForm)}
            onSubmit={(event) => void createToken(event)}
          >
            <label {...stylex.props(settings.tokenFormLabel)}>
              Label
              <input
                {...stylex.props(settings.tokenInput)}
                value={tokenLabel}
                maxLength={160}
                onChange={(event) => setTokenLabel(event.currentTarget.value)}
              />
            </label>
            <Field label="Purpose">
              <Select
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
              </Select>
            </Field>
            <Field label="Expires in">
              <Select
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
              </Select>
            </Field>
            <Button
              type="submit"
              variant="primary"
              size="lg"
              xstyle={settings.tokenFormButton}
              disabled={creating || tokenLabel.trim() === ""}
            >
              {creating ? "Creating…" : "Create token"}
            </Button>
          </form>
        ) : (
          <p {...stylex.props(settings.muted)}>
            Your role does not allow the supported automation workflows in this
            workspace.
          </p>
        )}

        {createdToken ? (
          <Notice
            tone="neutral"
            xstyle={settings.tokenMessage}
            action={
              <IconButton
                label="Copy personal access token"
                title="Copy token"
                variant="soft"
                size="md"
                onClick={() => void copyToken()}
              >
                {copied ? (
                  <Check size={16} aria-hidden="true" />
                ) : (
                  <Clipboard size={16} aria-hidden="true" />
                )}
              </IconButton>
            }
          >
            <strong>Copy this token now</strong>{" "}
            <span>
              {createdToken.label} will not be shown again after you leave this
              page.
            </span>
            <code {...stylex.props(settings.tokenSecret)}>
              {createdToken.token}
            </code>
          </Notice>
        ) : null}

        {message ? (
          <Notice tone="danger" xstyle={settings.tokenMessage}>
            {message}
          </Notice>
        ) : null}

        <div {...stylex.props(settings.tokenList)}>
          {tokensLoading ? (
            <p {...stylex.props(settings.muted)}>Loading tokens…</p>
          ) : tokensError ? (
            <Notice
              tone="danger"
              xstyle={settings.tokenMessage}
              action={
                <Button
                  variant="secondary"
                  size="xs"
                  onClick={() => void mutateTokens()}
                >
                  Retry
                </Button>
              }
            >
              Tokens could not be loaded.
            </Notice>
          ) : tokens?.length ? (
            tokens.map((token) => {
              const status = tokenState(token, renderedAt);
              return (
                <div {...stylex.props(settings.tokenRow)} key={token.id}>
                  <div {...stylex.props(settings.tokenRowMain)}>
                    <div {...stylex.props(settings.tokenRowMainLine)}>
                      <strong {...stylex.props(settings.tokenRowLabel)}>
                        {token.label}
                      </strong>
                      <span
                        {...stylex.props(settings.tokenStatus)}
                        data-state={status.state}
                      >
                        {status.label}
                      </span>
                    </div>
                    <code {...stylex.props(settings.tokenRowPrefix)}>
                      {token.public_prefix}…
                    </code>
                  </div>
                  <div {...stylex.props(settings.tokenMeta)}>
                    <span {...stylex.props(settings.tokenMetaWhen)}>
                      <Clock3 size={13} aria-hidden="true" /> Expires{" "}
                      {formatTimestamp(token.expires_at)}
                    </span>
                    <span>{token.scopes.join(", ")}</span>
                  </div>
                  <IconButton
                    label={`Revoke ${token.label}`}
                    title="Revoke token"
                    variant="danger"
                    size="sm"
                    xstyle={settings.tokenRowAction}
                    disabled={
                      status.state !== "active" || revokingId === token.id
                    }
                    onClick={() => void revokeToken(token)}
                  >
                    <Trash2 size={15} aria-hidden="true" />
                  </IconButton>
                </div>
              );
            })
          ) : (
            <p {...stylex.props(settings.muted)}>
              No personal access tokens for this workspace.
            </p>
          )}
        </div>
      </section>
      <WorkspacePacks key={workspace.id} workspace={workspace} />
      <WorkspaceCredentials
        workspaceId={workspace.id}
        canManageShared={workspace.capabilities.includes("manage_secrets")}
        canViewShared={workspace.capabilities.includes("view_project")}
      />
    </main>
  );
}
