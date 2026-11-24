"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  Blocks,
  Check,
  Clipboard,
  Clock3,
  KeyRound,
  SlidersHorizontal,
  Trash2,
  Users,
  Vault,
} from "lucide-react";
import useSWR from "swr";

import { Button, IconButton } from "@/components/ui/button";
import { Field, TextInput } from "@/components/ui/field";
import { Notice } from "@/components/ui/notice";
import { Select } from "@/components/ui/select";
import { phoneTouch } from "@/components/ui/touch-target";
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
type SettingsSectionId =
  "general" | "tool-packs" | "credentials" | "members" | "access-tokens";

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
  const workspacePillLabel = workspace.kind === "personal" ? "Personal" : label;

  const navItems = React.useMemo(
    () =>
      [
        {
          id: "general" as const,
          label: "General",
          icon: SlidersHorizontal,
        },
        {
          id: "tool-packs" as const,
          label: "Tool packs",
          icon: Blocks,
        },
        {
          id: "credentials" as const,
          label: "Provider credentials",
          icon: Vault,
        },
        ...(workspace.kind === "shared"
          ? [
              {
                id: "members" as const,
                label: "Members",
                icon: Users,
              },
            ]
          : []),
        {
          id: "access-tokens" as const,
          label: "Access tokens",
          icon: KeyRound,
        },
      ] as const,
    [workspace.kind],
  );

  const [activeSection, setActiveSection] =
    React.useState<SettingsSectionId>("general");
  const resolvedActiveSection = navItems.some(
    (item) => item.id === activeSection,
  )
    ? activeSection
    : "general";

  const scrollContainerRef = React.useRef<HTMLDivElement | null>(null);
  const scrollingTargetRef = React.useRef<SettingsSectionId | null>(null);
  const scrollTimerRef = React.useRef<number | null>(null);

  const scrollToSection = React.useCallback((id: SettingsSectionId) => {
    setActiveSection(id);
    scrollingTargetRef.current = id;
    if (scrollTimerRef.current !== null) {
      window.clearTimeout(scrollTimerRef.current);
    }
    scrollTimerRef.current = window.setTimeout(() => {
      scrollingTargetRef.current = null;
    }, 650);

    const target = document.getElementById(id);
    if (target && typeof target.scrollIntoView === "function") {
      const reducedMotion =
        typeof window.matchMedia === "function" &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      target.scrollIntoView({
        behavior: reducedMotion ? "auto" : "smooth",
        block: "start",
      });
    }
  }, []);

  React.useEffect(() => {
    return () => {
      if (scrollTimerRef.current !== null) {
        window.clearTimeout(scrollTimerRef.current);
      }
    };
  }, []);

  React.useEffect(() => {
    const root = scrollContainerRef.current;
    if (!root || typeof window === "undefined") return;

    const sectionIds = navItems.map((item) => item.id);
    const syncActiveSection = () => {
      if (scrollingTargetRef.current) return;
      const elements = sectionIds
        .map((id) => ({ id, element: document.getElementById(id) }))
        .filter(
          (entry): entry is { id: SettingsSectionId; element: HTMLElement } =>
            entry.element !== null,
        );
      if (elements.length === 0) return;

      if (
        root.scrollHeight > root.clientHeight &&
        root.scrollTop + root.clientHeight >= root.scrollHeight - 24
      ) {
        setActiveSection(elements[elements.length - 1]!.id);
        return;
      }

      const rootTop = root.getBoundingClientRect().top;
      let current = elements[0]!.id;
      for (const entry of elements) {
        const offsetTop = entry.element.getBoundingClientRect().top - rootTop;
        if (offsetTop <= 130) {
          current = entry.id;
        }
      }
      setActiveSection(current);
    };

    root.addEventListener("scroll", syncActiveSection, { passive: true });

    let observer: IntersectionObserver | null = null;
    if (typeof IntersectionObserver !== "undefined") {
      observer = new IntersectionObserver(
        () => {
          syncActiveSection();
        },
        {
          root,
          rootMargin: "-84px 0px -60% 0px",
          threshold: [0, 0.1],
        },
      );
      for (const id of sectionIds) {
        const element = document.getElementById(id);
        if (element) observer.observe(element);
      }
    }

    return () => {
      root.removeEventListener("scroll", syncActiveSection);
      observer?.disconnect();
    };
  }, [navItems]);

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
    <div ref={scrollContainerRef} {...stylex.props(settings.page)}>
      <header {...stylex.props(settings.topBar)}>
        <h1 {...stylex.props(settings.headerTitle)}>Settings</h1>
        <span {...stylex.props(settings.workspacePill)}>
          {workspacePillLabel}
        </span>
      </header>

      <div {...stylex.props(settings.body)}>
        <aside {...stylex.props(settings.subrail)}>
          <nav
            aria-label="Settings sections"
            {...stylex.props(settings.subrailNav)}
          >
            {navItems.map((item) => {
              const Icon = item.icon;
              const active = resolvedActiveSection === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  data-section-id={item.id}
                  data-active={active ? "true" : undefined}
                  aria-current={active ? "location" : undefined}
                  onClick={() => scrollToSection(item.id)}
                  {...stylex.props(
                    settings.subrailItem,
                    active && settings.subrailItemActive,
                  )}
                >
                  <Icon
                    size={15}
                    aria-hidden="true"
                    {...stylex.props(settings.subrailIcon)}
                  />
                  <span>{item.label}</span>
                </button>
              );
            })}
          </nav>
        </aside>

        <main {...stylex.props(settings.main)}>
          <div {...stylex.props(settings.content)}>
            <section
              id="general"
              {...stylex.props(settings.section, settings.sectionFirst)}
              aria-labelledby="workspace-details-heading"
            >
              <div {...stylex.props(settings.sectionHeading)}>
                <div>
                  <h2
                    id="workspace-details-heading"
                    {...stylex.props(settings.headingTitle)}
                  >
                    General
                  </h2>
                  <p {...stylex.props(settings.headingText)}>
                    The active location and permissions these settings apply to.
                  </p>
                </div>
                <SlidersHorizontal
                  size={18}
                  aria-hidden="true"
                  {...stylex.props(settings.headingIcon)}
                />
              </div>
              <dl {...stylex.props(settings.details)}>
                <div {...stylex.props(settings.detailsRow)}>
                  <div {...stylex.props(settings.detailsLabelGroup)}>
                    <dt {...stylex.props(settings.detailsTerm)}>Name</dt>
                    <p {...stylex.props(settings.detailsHint)}>
                      Shown in the workspace switcher and project lists.
                    </p>
                  </div>
                  <dd {...stylex.props(settings.detailsValue)}>{label}</dd>
                </div>
                <div {...stylex.props(settings.detailsRow)}>
                  <div {...stylex.props(settings.detailsLabelGroup)}>
                    <dt {...stylex.props(settings.detailsTerm)}>Type</dt>
                    <p {...stylex.props(settings.detailsHint)}>
                      Personal workspaces stay private; shared workspaces
                      collaborate with a team.
                    </p>
                  </div>
                  <dd {...stylex.props(settings.detailsBadge)}>
                    {workspace.kind === "personal" ? "Personal" : "Shared"}
                  </dd>
                </div>
                <div {...stylex.props(settings.detailsRow)}>
                  <div {...stylex.props(settings.detailsLabelGroup)}>
                    <dt {...stylex.props(settings.detailsTerm)}>Your role</dt>
                    <p {...stylex.props(settings.detailsHint)}>
                      Determines which settings and project actions you can
                      perform.
                    </p>
                  </div>
                  <dd {...stylex.props(settings.detailsBadge)}>
                    {workspace.role}
                  </dd>
                </div>
              </dl>
            </section>

            <WorkspacePacks key={workspace.id} workspace={workspace} />

            <WorkspaceCredentials
              workspaceId={workspace.id}
              canManageShared={workspace.capabilities.includes(
                "manage_secrets",
              )}
              canViewShared={workspace.capabilities.includes("view_project")}
            />

            {workspace.kind === "shared" ? (
              <section
                id="members"
                {...stylex.props(settings.section)}
                aria-labelledby="workspace-access-heading"
              >
                <div {...stylex.props(settings.sectionHeading)}>
                  <div>
                    <h2
                      id="workspace-access-heading"
                      {...stylex.props(settings.headingTitle)}
                    >
                      Members
                    </h2>
                    <p {...stylex.props(settings.headingText)}>
                      Control who can work in this workspace and what they can
                      do.
                    </p>
                  </div>
                  <Users
                    size={18}
                    aria-hidden="true"
                    {...stylex.props(settings.headingIcon)}
                  />
                </div>
                <div {...stylex.props(settings.sectionActionCard)}>
                  <div {...stylex.props(settings.sectionActionCopy)}>
                    <strong {...stylex.props(settings.sectionActionTitle)}>
                      Members and access
                    </strong>
                    <span {...stylex.props(settings.sectionActionText)}>
                      {canManageMembers
                        ? "Invite people, change roles, or remove access."
                        : "Only workspace owners can change member access."}
                    </span>
                  </div>
                  {canManageMembers ? <WorkspaceMembersDialog /> : null}
                </div>
              </section>
            ) : null}

            <section
              id="access-tokens"
              {...stylex.props(settings.section, settings.sectionLast)}
              aria-labelledby="workspace-token-heading"
            >
              <div {...stylex.props(settings.sectionHeading)}>
                <div>
                  <h2
                    id="workspace-token-heading"
                    {...stylex.props(settings.headingTitle)}
                  >
                    Access tokens
                  </h2>
                  <p {...stylex.props(settings.headingText)}>
                    Authenticate command-line and automated workflows without
                    using your browser session.
                  </p>
                </div>
                <KeyRound
                  size={18}
                  aria-hidden="true"
                  {...stylex.props(settings.headingIcon)}
                />
              </div>

              {selectedTokenPurpose ? (
                <div {...stylex.props(settings.tokenFormCard)}>
                  <form
                    {...stylex.props(settings.tokenForm)}
                    onSubmit={(event) => void createToken(event)}
                  >
                    <Field label="Label">
                      <TextInput
                        value={tokenLabel}
                        maxLength={160}
                        onChange={(event) =>
                          setTokenLabel(event.currentTarget.value)
                        }
                        xstyle={phoneTouch.on}
                      />
                    </Field>
                    <Field label="Purpose">
                      <Select
                        value={selectedTokenPurpose.id}
                        xstyle={phoneTouch.on}
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
                        xstyle={phoneTouch.on}
                        onChange={(event) => {
                          const value = event.currentTarget.value;
                          if (
                            value === "1" ||
                            value === "7" ||
                            value === "30"
                          ) {
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
                      size="md"
                      xstyle={[phoneTouch.on, settings.tokenFormButton]}
                      disabled={creating || tokenLabel.trim() === ""}
                    >
                      {creating ? "Creating…" : "Create token"}
                    </Button>
                  </form>
                </div>
              ) : (
                <p {...stylex.props(settings.muted)}>
                  Your role does not allow the supported automation workflows in
                  this workspace.
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
                    {createdToken.label} will not be shown again after you leave
                    this page.
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
                <div {...stylex.props(settings.tokenList)}>
                  {tokens.map((token) => {
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
                  })}
                </div>
              ) : (
                <p {...stylex.props(settings.muted)}>
                  No personal access tokens for this workspace.
                </p>
              )}
            </section>
          </div>
        </main>
      </div>
    </div>
  );
}
