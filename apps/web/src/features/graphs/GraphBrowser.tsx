"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  ArrowUpRight,
  Plus,
  RotateCcw,
  Search,
  Users,
  Workflow,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { BrandLoader } from "@/components/brand";
import { Button, ButtonLink } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { GraphViewToggle } from "./GraphViewToggle";
import type { GraphBrowserView } from "./browser-filters";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useAuthSession } from "@/features/auth/AuthSessionBoundary";
import {
  WorkspaceRail,
  workspaceDisplayName,
} from "@/features/workspaces/WorkspaceLayout";
import {
  graphAgeLabel,
  graphCountLabel,
} from "@/features/workspaces/WorkspaceGraphPanel";
import {
  NEW_PROJECT_ROUTE_ID,
  workbenchProjectPath,
} from "@/features/workbench/routes";
import { tokens } from "@/lib/stylex/tokens.stylex";
import {
  type LocatedProject,
  useAllWorkspacesProjects,
  useWorkspaces,
} from "@/hooks/use-api";

const RECENT_GRAPH_LIMIT = 8;

const browserStyles = stylex.create({
  locationOptions: {
    display: "grid",
  },
  /**
   * A creation location as a row: icon, two lines of text, then the arrow. The
   * kit has no list-row button, so only this row geometry is owned here.
   */
  locationOption: {
    display: "grid",
    gridTemplateColumns: "30px minmax(0, 1fr) 18px",
    alignItems: "center",
    gap: "10px",
    width: "100%",
    height: "auto",
    paddingInline: "6px",
    paddingBlock: "12px",
    borderRadius: 0,
    textAlign: "start",
    whiteSpace: "normal",
    borderBottomColor: tokens.colorDivider,
  },
  locationOptionIcon: {
    display: "grid",
    placeItems: "center",
    width: "30px",
    height: "30px",
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorSurfaceRaised,
    color: tokens.colorSubtle,
  },
  locationOptionText: {
    display: "grid",
    gap: "2px",
    minWidth: 0,
  },
  locationOptionTitle: {
    fontSize: tokens.fontSizeMd,
    fontWeight: 600,
  },
  locationOptionSubtitle: {
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    fontWeight: 400,
  },
});

/**
 * The Recent/All choice lives in `GraphViewToggle`, shared with the workspace
 * browser, so the two surfaces cannot drift apart.
 */

function GraphRow({ graph }: { graph: LocatedProject }) {
  return (
    <li>
      <Link
        href={workbenchProjectPath(graph.location.slug, graph.id)}
        className="grafy-graphs__row"
        aria-label={`Open ${graph.name} in ${workspaceDisplayName(graph.location)}`}
      >
        <span className="grafy-graphs__row-icon" aria-hidden="true">
          <Workflow size={16} />
        </span>
        <span className="grafy-graphs__row-title">{graph.name}</span>
        <span className="grafy-graphs__row-location">
          {workspaceDisplayName(graph.location)}
        </span>
        <span className="grafy-graphs__row-meta">
          {graphAgeLabel(graph.updated_at)}
        </span>
        <span className="grafy-graphs__row-meta">{graphCountLabel(graph)}</span>
        <ArrowUpRight
          className="grafy-graphs__row-arrow"
          size={15}
          aria-hidden="true"
        />
      </Link>
    </li>
  );
}

export function GraphBrowser() {
  const router = useRouter();
  const { session, logout } = useAuthSession();
  const {
    data: workspaces,
    error: workspacesError,
    mutate: retryWorkspaces,
  } = useWorkspaces(session.user_id);
  const projectState = useAllWorkspacesProjects(workspaces);
  const [query, setQuery] = React.useState("");
  const [view, setView] = React.useState<GraphBrowserView>("recent");
  const [locationId, setLocationId] = React.useState("all");
  const [createOpen, setCreateOpen] = React.useState(false);

  const createLocations = React.useMemo(
    () =>
      (workspaces ?? []).filter((workspace) =>
        workspace.capabilities.includes("create_project"),
      ),
    [workspaces],
  );
  const effectiveLocationId =
    locationId === "all" ||
    workspaces?.some((workspace) => workspace.id === locationId)
      ? locationId
      : "all";
  const normalizedQuery = query.trim().toLowerCase();
  const filteredGraphs = React.useMemo(() => {
    const availableGraphs = projectState.projects ?? [];
    return availableGraphs.filter((graph) => {
      if (
        effectiveLocationId !== "all" &&
        graph.location.id !== effectiveLocationId
      ) {
        return false;
      }
      if (!normalizedQuery) return true;
      const haystack =
        `${graph.name} ${workspaceDisplayName(graph.location)}`.toLowerCase();
      return haystack.includes(normalizedQuery);
    });
  }, [effectiveLocationId, projectState.projects, normalizedQuery]);
  const visibleGraphs =
    view === "recent"
      ? filteredGraphs.slice(0, RECENT_GRAPH_LIMIT)
      : filteredGraphs;
  const totalGraphCount = projectState.projects?.length ?? 0;

  const startGraph = React.useCallback(() => {
    if (createLocations.length === 1) {
      const location = createLocations[0]!;
      router.push(workbenchProjectPath(location.slug, NEW_PROJECT_ROUTE_ID));
      return;
    }
    if (createLocations.length > 1) setCreateOpen(true);
  }, [createLocations, router]);

  const selectedLocation = workspaces?.find(
    (workspace) => workspace.id === effectiveLocationId,
  );

  return (
    <div className="grafy-graphs">
      {workspaces ? (
        <WorkspaceRail
          workspaces={workspaces}
          session={session}
          onLogout={logout}
          onNewGraph={startGraph}
        />
      ) : null}

      <main className="grafy-graphs__main">
        <header className="grafy-graphs__header">
          <div>
            <p className="grafy-graphs__eyebrow">Your work</p>
            <h1>Graphs</h1>
            <p className="grafy-graphs__intro">
              Find and open graphs across every location you can access.
            </p>
          </div>
          <Button
            variant="primary"
            size="lg"
            className="grafy-graphs__header-action"
            disabled={createLocations.length === 0}
            title={
              createLocations.length === 0
                ? "You do not have permission to create a graph in any location."
                : undefined
            }
            onClick={startGraph}
          >
            <Plus size={15} aria-hidden="true" />
            New graph
          </Button>
        </header>

        <div className="grafy-graphs__toolbar">
          <label className="grafy-graphs__search">
            <Search size={16} aria-hidden="true" />
            <input
              type="search"
              value={query}
              aria-label="Search graphs"
              placeholder="Search graphs"
              onChange={(event) => setQuery(event.currentTarget.value)}
            />
          </label>
          <label className="grafy-graphs__location-filter">
            <span>Location</span>
            <Select
              value={effectiveLocationId}
              aria-label="Filter by location"
              size="md"
              block={false}
              onChange={(event) => setLocationId(event.currentTarget.value)}
            >
              <option value="all">All locations</option>
              {(workspaces ?? []).map((workspace) => (
                <option key={workspace.id} value={workspace.id}>
                  {workspaceDisplayName(workspace)}
                </option>
              ))}
            </Select>
          </label>
        </div>

        <div className="grafy-graphs__view-bar">
          <GraphViewToggle value={view} onValueChange={setView} />
          {projectState.projects ? (
            <span className="grafy-graphs__count">
              {filteredGraphs.length}{" "}
              {filteredGraphs.length === 1 ? "graph" : "graphs"}
              {projectState.isRefreshing ? " · refreshing…" : ""}
            </span>
          ) : null}
        </div>

        {workspacesError ? (
          <section className="grafy-graphs__state" role="alert">
            <Workflow size={22} aria-hidden="true" />
            <div>
              <h2>Locations couldn&apos;t be loaded</h2>
              <p>Check your connection, then try again.</p>
            </div>
            <Button
              variant="secondary"
              size="lg"
              className="grafy-graphs__state-action"
              onClick={() => void retryWorkspaces()}
            >
              <RotateCcw size={14} aria-hidden="true" /> Retry
            </Button>
          </section>
        ) : !workspaces ||
          (projectState.error === null &&
            (projectState.isLoading || projectState.projects === null)) ? (
          <div className="grafy-graphs__loading" role="status">
            <BrandLoader size={36} label="Loading graphs" />
            <span>Loading graphs…</span>
          </div>
        ) : workspaces.length === 0 ? (
          <section className="grafy-graphs__state">
            <Users size={22} aria-hidden="true" />
            <div>
              <h2>No graph locations are available</h2>
              <p>Open Teams &amp; access to create or join a location.</p>
            </div>
            <ButtonLink
              href="/workspaces"
              variant="secondary"
              size="lg"
              className="grafy-graphs__state-action"
            >
              Teams &amp; access
            </ButtonLink>
          </section>
        ) : projectState.error ? (
          <section className="grafy-graphs__state" role="alert">
            <Workflow size={22} aria-hidden="true" />
            <div>
              <h2>Graphs couldn&apos;t be loaded</h2>
              <p>Check your connection, then try again.</p>
            </div>
            <Button
              variant="secondary"
              size="lg"
              className="grafy-graphs__state-action"
              onClick={() => void projectState.retry()}
            >
              <RotateCcw size={14} aria-hidden="true" /> Retry
            </Button>
          </section>
        ) : (
          <>
            {totalGraphCount === 0 ? (
              <section className="grafy-graphs__state grafy-graphs__state--empty">
                <Workflow size={22} aria-hidden="true" />
                <div>
                  <h2>No graphs yet</h2>
                  <p>Create your first graph to start building.</p>
                </div>
                {createLocations.length > 0 ? (
                  <Button
                    variant="secondary"
                    size="lg"
                    className="grafy-graphs__state-action"
                    onClick={startGraph}
                  >
                    <Plus size={14} aria-hidden="true" /> New graph
                  </Button>
                ) : null}
              </section>
            ) : visibleGraphs.length === 0 ? (
              <section className="grafy-graphs__state grafy-graphs__state--empty">
                <Search size={22} aria-hidden="true" />
                <div>
                  <h2>
                    {normalizedQuery
                      ? "No graphs match your search"
                      : `No graphs in ${selectedLocation ? workspaceDisplayName(selectedLocation) : "this location"}`}
                  </h2>
                  <p>
                    {normalizedQuery
                      ? "Try another name or clear the location filter."
                      : "Choose another location or create a graph here."}
                  </p>
                </div>
                {normalizedQuery ? (
                  <Button
                    variant="secondary"
                    size="lg"
                    className="grafy-graphs__state-action"
                    onClick={() => setQuery("")}
                  >
                    Clear search
                  </Button>
                ) : null}
              </section>
            ) : (
              <ul
                className="grafy-graphs__list"
                aria-label={`${view === "recent" ? "Recent" : "All"} graphs`}
              >
                {visibleGraphs.map((graph) => (
                  <GraphRow
                    key={`${graph.location.id}/${graph.id}`}
                    graph={graph}
                  />
                ))}
              </ul>
            )}
          </>
        )}
      </main>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent size="form">
          <DialogHeader>
            <DialogTitle>Choose a location</DialogTitle>
            <DialogDescription>
              Select where this graph should live. You can share it according to
              that location&apos;s access.
            </DialogDescription>
          </DialogHeader>
          <DialogBody>
            <div {...stylex.props(browserStyles.locationOptions)}>
              {createLocations.map((location) => (
                <Button
                  key={location.id}
                  variant="ghost"
                  size="md"
                  xstyle={browserStyles.locationOption}
                  onClick={() => {
                    setCreateOpen(false);
                    router.push(
                      workbenchProjectPath(location.slug, NEW_PROJECT_ROUTE_ID),
                    );
                  }}
                >
                  <span
                    {...stylex.props(browserStyles.locationOptionIcon)}
                    aria-hidden="true"
                  >
                    {location.kind === "personal" ? (
                      <Workflow size={16} />
                    ) : (
                      <Users size={16} />
                    )}
                  </span>
                  <span {...stylex.props(browserStyles.locationOptionText)}>
                    <strong
                      {...stylex.props(browserStyles.locationOptionTitle)}
                    >
                      {workspaceDisplayName(location)}
                    </strong>
                    <small
                      {...stylex.props(browserStyles.locationOptionSubtitle)}
                    >
                      {location.kind === "personal"
                        ? "Private to you"
                        : "Shared with this team"}
                    </small>
                  </span>
                  <ArrowUpRight size={15} aria-hidden="true" />
                </Button>
              ))}
            </div>
          </DialogBody>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default GraphBrowser;
