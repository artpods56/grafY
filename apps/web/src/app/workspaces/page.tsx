"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  ArrowUpRight,
  Plus,
  Search,
  Share2,
  Users,
  Workflow,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { BrandLoader } from "@/components/brand";
import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";
import { useAuthSession } from "@/features/auth/AuthSessionBoundary";
import {
  WorkspaceRail,
  workspaceDisplayName,
} from "@/features/workspaces/WorkspaceLayout";
import { useWorkspaces } from "@/hooks/use-api";
import { createWorkspace } from "@/lib/api";
import type { Workspace } from "@/lib/api";
import { ApiError } from "@/lib/api/client";

import { workspacesPageStyles as styles } from "./page.styles";

function slugFromName(name: string): string {
  const slug = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  return slug || "shared-workspace";
}

function LocationRow({ workspace }: { workspace: Workspace }) {
  return (
    <Link
      className={stylex.props(styles.row).className}
      href={`/workspaces/${encodeURIComponent(workspace.slug)}`}
      aria-label={`Open settings for ${workspaceDisplayName(workspace)}`}
    >
      <span
        className={stylex.props(styles.rowIcon).className}
        aria-hidden="true"
      >
        {workspace.kind === "personal" ? (
          <Workflow size={16} />
        ) : (
          <Users size={16} />
        )}
      </span>
      <span className={stylex.props(styles.rowCopy).className}>
        <strong className={stylex.props(styles.rowName).className}>
          {workspaceDisplayName(workspace)}
        </strong>
        <small className={stylex.props(styles.rowHint).className}>
          {workspace.kind === "personal"
            ? "Your private project location"
            : "A project location shared with this team"}
        </small>
      </span>
      <span className={stylex.props(styles.rowOpen).className}>Settings</span>
      <ArrowUpRight size={15} aria-hidden="true" />
    </Link>
  );
}

function LocationSection({
  title,
  workspaces,
}: {
  title: string;
  workspaces: readonly Workspace[];
}) {
  if (workspaces.length === 0) return null;
  return (
    <section
      className={stylex.props(styles.section).className}
      aria-label={title}
    >
      <div className={stylex.props(styles.sectionHeading).className}>
        <h2 className={stylex.props(styles.sectionTitle).className}>{title}</h2>
        <span className={stylex.props(styles.sectionMeta).className}>
          {workspaces.length}{" "}
          {workspaces.length === 1 ? "location" : "locations"}
        </span>
      </div>
      <div className={stylex.props(styles.list).className}>
        {workspaces.map((workspace) => (
          <LocationRow key={workspace.id} workspace={workspace} />
        ))}
      </div>
    </section>
  );
}

export default function WorkspacesPage() {
  const router = useRouter();
  const { session, logout } = useAuthSession();
  const { data: workspaces, error, mutate } = useWorkspaces(session.user_id);
  const [query, setQuery] = React.useState("");
  const [name, setName] = React.useState("");
  const [createOpen, setCreateOpen] = React.useState(false);
  const [joinOpen, setJoinOpen] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [message, setMessage] = React.useState<string | null>(null);

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedName = name.trim();
    if (!normalizedName) return;
    setBusy(true);
    setMessage(null);
    try {
      const workspace = await createWorkspace({
        name: normalizedName,
        slug: slugFromName(normalizedName),
      });
      await mutate(
        (current) => (current ? [...current, workspace] : [workspace]),
        { revalidate: false },
      );
      setName("");
      setCreateOpen(false);
      router.push(`/workspaces/${encodeURIComponent(workspace.slug)}`);
    } catch (caught) {
      setMessage(
        caught instanceof ApiError && caught.status === 409
          ? "A team with that name already exists."
          : "The team could not be created.",
      );
    } finally {
      setBusy(false);
    }
  };

  const normalizedQuery = query.trim().toLowerCase();
  const filtered = React.useMemo(
    () =>
      [...(workspaces ?? [])]
        .filter((workspace) =>
          workspaceDisplayName(workspace)
            .toLowerCase()
            .includes(normalizedQuery),
        )
        .sort((left, right) =>
          workspaceDisplayName(left).localeCompare(workspaceDisplayName(right)),
        ),
    [normalizedQuery, workspaces],
  );
  const personal = filtered.filter(
    (workspace) => workspace.kind === "personal",
  );
  const teams = filtered.filter((workspace) => workspace.kind === "shared");

  return (
    <div className={stylex.props(styles.directory).className}>
      {workspaces ? (
        <WorkspaceRail
          workspaces={workspaces}
          session={session}
          onLogout={logout}
        />
      ) : null}
      <main className={stylex.props(styles.main).className}>
        <header className={stylex.props(styles.header).className}>
          <div>
            <p
              className={
                stylex.props(styles.eyebrow, styles.headerText).className
              }
            >
              Administration
            </p>
            <h1 className={stylex.props(styles.headerTitle).className}>
              Workspace directory
            </h1>
            <p className={stylex.props(styles.headerText).className}>
              Manage the locations that own your graphs and control who can work
              with them.
            </p>
          </div>
          <div className={stylex.props(styles.actions).className}>
            <Button
              variant="primary"
              size="lg"
              xstyle={styles.actionItem}
              onClick={() => {
                setCreateOpen((current) => !current);
                setJoinOpen(false);
              }}
            >
              <Plus size={14} aria-hidden="true" /> Create team
            </Button>
            <Button
              variant="secondary"
              size="lg"
              xstyle={styles.actionItem}
              onClick={() => {
                setJoinOpen((current) => !current);
                setCreateOpen(false);
              }}
            >
              <Share2 size={14} aria-hidden="true" /> Join a team
            </Button>
          </div>
        </header>

        {createOpen ? (
          <form
            className={stylex.props(styles.createForm).className}
            onSubmit={(event) => void submit(event)}
          >
            <label className={stylex.props(styles.createLabel).className}>
              Team name
              <input
                className={stylex.props(styles.createInput).className}
                value={name}
                onChange={(event) => setName(event.currentTarget.value)}
                placeholder="Planning"
                autoFocus
              />
            </label>
            <Button
              type="submit"
              variant="primary"
              size="lg"
              disabled={busy || name.trim() === ""}
            >
              {busy ? "Creating…" : "Create team"}
            </Button>
            {message ? <Notice tone="danger">{message}</Notice> : null}
          </form>
        ) : null}

        {joinOpen ? (
          <div
            className={stylex.props(styles.joinForm).className}
            role="region"
            aria-label="Join a team"
          >
            <p className={stylex.props(styles.joinText).className}>
              Ask a team owner to add you. The team will appear here as soon as
              access is granted.
            </p>
          </div>
        ) : null}

        <div className={stylex.props(styles.toolbar).className}>
          <label className={stylex.props(styles.search).className}>
            <Search size={15} aria-hidden="true" />
            <input
              className={stylex.props(styles.searchInput).className}
              type="search"
              value={query}
              onChange={(event) => setQuery(event.currentTarget.value)}
              placeholder="Search teams"
              aria-label="Search teams and project locations"
            />
          </label>
        </div>

        {error ? (
          <Notice
            tone="danger"
            action={
              <Button
                variant="secondary"
                size="xs"
                onClick={() => void mutate()}
              >
                Retry
              </Button>
            }
          >
            Teams and access couldn&apos;t be loaded.
          </Notice>
        ) : !workspaces ? (
          <div className={stylex.props(styles.loading).className}>
            <BrandLoader size={40} label="Loading teams and access" />
            <span>Loading teams &amp; access…</span>
          </div>
        ) : filtered.length === 0 ? (
          <div className={stylex.props(styles.empty).className}>
            <p>
              {normalizedQuery
                ? "No teams or locations match that search."
                : "No project locations are available to this account."}
            </p>
            {normalizedQuery ? (
              <Button
                variant="secondary"
                size="lg"
                onClick={() => setQuery("")}
              >
                Clear search
              </Button>
            ) : null}
          </div>
        ) : (
          <>
            <LocationSection title="My projects" workspaces={personal} />
            <LocationSection title="Teams" workspaces={teams} />
          </>
        )}

        <aside
          className={stylex.props(styles.edu).className}
          aria-label="About project locations"
        >
          <div>
            <h2 className={stylex.props(styles.eduTitle).className}>
              How locations work
            </h2>
            <p className={stylex.props(styles.eduText).className}>
              My projects is private to you. A Team location shares its projects
              with that Team while keeping access and project data together.
            </p>
          </div>
          <span
            className={stylex.props(styles.eduMark).className}
            aria-hidden="true"
          />
        </aside>
      </main>
    </div>
  );
}
