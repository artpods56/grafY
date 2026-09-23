"use client";

import { ArrowUpRight, Users, Workflow } from "lucide-react";
import Link from "next/link";

import {
  useWorkspaceContext,
  workspaceCanManageMembers,
  workspaceDisplayName,
} from "./WorkspaceLayout";
import { WorkspaceLibraryDialog } from "./WorkspaceLibraryDialog";
import { WorkspaceMembersDialog } from "./WorkspaceMembersDialog";

export function WorkspaceOverview() {
  const { workspace } = useWorkspaceContext();
  const canManageMembers = workspaceCanManageMembers(workspace);
  const label = workspaceDisplayName(workspace);

  return (
    <div className="grafy-workspace-overview">
      <header className="grafy-workspace-overview__header">
        <div>
          <p className="grafy-workspace-overview__eyebrow">
            {workspace.kind === "personal"
              ? "Personal settings"
              : "Team settings"}
          </p>
          <h1>{label}</h1>
          <p className="grafy-workspace-overview__copy">
            {workspace.kind === "personal"
              ? "This is the private location for your graphs."
              : `Manage access and shared resources for ${label}.`}
          </p>
        </div>
        <div className="grafy-workspace-overview__actions">
          {workspace.kind === "shared" && canManageMembers ? (
            <WorkspaceMembersDialog />
          ) : null}
          <WorkspaceLibraryDialog
            workspace={workspace}
            triggerLabel="Modules"
          />
          <Link
            className="grafy-workspace-button"
            href={`/workspaces/${encodeURIComponent(workspace.slug)}/graphs`}
          >
            Browse graphs <ArrowUpRight size={14} aria-hidden="true" />
          </Link>
        </div>
      </header>

      {workspace.kind === "shared" ? (
        <section
          className="grafy-workspace-overview__section"
          aria-labelledby="team-access-heading"
        >
          <div className="grafy-workspace-overview__section-heading">
            <div>
              <p className="grafy-workspace-overview__eyebrow">Access</p>
              <h2 id="team-access-heading">Team members</h2>
            </div>
            <Users size={18} aria-hidden="true" />
          </div>
          <p className="grafy-workspace-overview__copy">
            Graphs saved here are available according to this Team&apos;s
            access.
            {canManageMembers
              ? " Use Manage members to update access."
              : " Ask a Team owner when access needs to change."}
          </p>
        </section>
      ) : null}

      <section
        className="grafy-workspace-overview__section"
        aria-labelledby="graph-location-heading"
      >
        <div className="grafy-workspace-overview__section-heading">
          <div>
            <p className="grafy-workspace-overview__eyebrow">Graphs</p>
            <h2 id="graph-location-heading">{label}</h2>
          </div>
          <Workflow size={18} aria-hidden="true" />
        </div>
        <p className="grafy-workspace-overview__copy">
          Open the graph browser to find or create work in this location. The
          location keeps its graphs and related data together.
        </p>
      </section>
    </div>
  );
}
