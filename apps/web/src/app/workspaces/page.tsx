"use client";

import * as React from "react";
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
import { useAuthSession } from "@/features/auth/AuthSessionBoundary";
import {
  WorkspaceRail,
  workspaceDisplayName,
} from "@/features/workspaces/WorkspaceLayout";
import { useWorkspaces } from "@/hooks/use-api";
import { createWorkspace } from "@/lib/api";
import type { Workspace } from "@/lib/api";
import { ApiError } from "@/lib/api/client";

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
      className="grafy-workspace-list__row"
      href={`/workspaces/${encodeURIComponent(workspace.slug)}`}
      aria-label={`Open settings for ${workspaceDisplayName(workspace)}`}
    >
      <span className="grafy-workspace-list__icon" aria-hidden="true">
        {workspace.kind === "personal" ? (
          <Workflow size={16} />
        ) : (
          <Users size={16} />
        )}
      </span>
      <span className="grafy-workspace-list__copy">
        <strong>{workspaceDisplayName(workspace)}</strong>
        <small>
          {workspace.kind === "personal"
            ? "Your private graph location"
            : "A graph location shared with this team"}
        </small>
      </span>
      <span className="grafy-workspace-list__open">Settings</span>
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
    <section className="grafy-workspace-section" aria-label={title}>
      <div className="grafy-workspace-section__heading">
        <h2>{title}</h2>
        <span className="grafy-workspace-section__meta">
          {workspaces.length}{" "}
          {workspaces.length === 1 ? "location" : "locations"}
        </span>
      </div>
      <div className="grafy-workspace-list">
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
    <div className="grafy-workspace-directory">
      {workspaces ? (
        <WorkspaceRail
          workspaces={workspaces}
          session={session}
          onLogout={logout}
        />
      ) : null}
      <main className="grafy-workspace-directory__main">
        <header className="grafy-workspace-directory__header">
          <div>
            <p className="grafy-workspace-overview__eyebrow">Administration</p>
            <h1>Workspace directory</h1>
            <p>
              Manage the locations that own your graphs and control who can work
              with them.
            </p>
          </div>
          <div className="grafy-workspace-directory__actions">
            <button
              type="button"
              className="grafy-workspace-button grafy-workspace-button--primary"
              onClick={() => {
                setCreateOpen((current) => !current);
                setJoinOpen(false);
              }}
            >
              <Plus size={14} aria-hidden="true" /> Create team
            </button>
            <button
              type="button"
              className="grafy-workspace-button"
              onClick={() => {
                setJoinOpen((current) => !current);
                setCreateOpen(false);
              }}
            >
              <Share2 size={14} aria-hidden="true" /> Join a team
            </button>
          </div>
        </header>

        {createOpen ? (
          <form
            className="grafy-workspace-create"
            onSubmit={(event) => void submit(event)}
          >
            <label>
              Team name
              <input
                value={name}
                onChange={(event) => setName(event.currentTarget.value)}
                placeholder="Planning"
                autoFocus
              />
            </label>
            <button
              type="submit"
              className="grafy-workspace-button grafy-workspace-button--primary"
              disabled={busy || name.trim() === ""}
            >
              {busy ? "Creating…" : "Create team"}
            </button>
            {message ? (
              <span className="grafy-member-message" role="status">
                {message}
              </span>
            ) : null}
          </form>
        ) : null}

        {joinOpen ? (
          <div
            className="grafy-workspace-join"
            role="region"
            aria-label="Join a team"
          >
            <p>
              Ask a team owner to add you. The team will appear here as soon as
              access is granted.
            </p>
          </div>
        ) : null}

        <div className="grafy-workspace-toolbar">
          <label className="grafy-workspace-search">
            <Search size={15} aria-hidden="true" />
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.currentTarget.value)}
              placeholder="Search teams"
              aria-label="Search teams and graph locations"
            />
          </label>
        </div>

        {error ? (
          <div className="grafy-workspace-empty" role="alert">
            <p>Teams and access couldn&apos;t be loaded.</p>
            <button
              type="button"
              className="grafy-workspace-button"
              onClick={() => void mutate()}
            >
              Retry
            </button>
          </div>
        ) : !workspaces ? (
          <div className="grafy-workspace-directory__loading">
            <BrandLoader size={40} label="Loading teams and access" />
            <span>Loading teams &amp; access…</span>
          </div>
        ) : filtered.length === 0 ? (
          <div className="grafy-workspace-empty">
            <p>
              {normalizedQuery
                ? "No teams or locations match that search."
                : "No graph locations are available to this account."}
            </p>
            {normalizedQuery ? (
              <button
                type="button"
                className="grafy-workspace-button"
                onClick={() => setQuery("")}
              >
                Clear search
              </button>
            ) : null}
          </div>
        ) : (
          <>
            <LocationSection title="My graphs" workspaces={personal} />
            <LocationSection title="Teams" workspaces={teams} />
          </>
        )}

        <aside
          className="grafy-workspace-edu"
          aria-label="About graph locations"
        >
          <div>
            <h2>How locations work</h2>
            <p>
              My graphs is private to you. A Team location shares its graphs
              with that Team while keeping access and graph data together.
            </p>
          </div>
          <span className="grafy-workspace-edu__mark" aria-hidden="true" />
        </aside>
      </main>
    </div>
  );
}
