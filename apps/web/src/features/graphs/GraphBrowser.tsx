"use client";

import * as React from "react";
import {
  ArrowUpRight,
  Clock3,
  Plus,
  RotateCcw,
  Search,
  Users,
  Workflow,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { BrandLoader } from "@/components/brand";
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
import { graphAgeLabel, graphCountLabel } from "@/features/workspaces/WorkspaceGraphPanel";
import {
  NEW_GRAPH_ROUTE_ID,
  workbenchGraphPath,
} from "@/features/workbench/routes";
import {
  type LocatedGraph,
  useAllWorkspacesGraphs,
  useWorkspaces,
} from "@/hooks/use-api";

type GraphBrowserView = "recent" | "all";

const RECENT_GRAPH_LIMIT = 8;

function GraphRow({ graph }: { graph: LocatedGraph }) {
  return (
    <li>
      <Link
        href={workbenchGraphPath(graph.location.slug, graph.id)}
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
  const graphState = useAllWorkspacesGraphs(workspaces);
  const [query, setQuery] = React.useState("");
  const [view, setView] = React.useState<GraphBrowserView>("recent");
  const [locationId, setLocationId] = React.useState("all");
  const [createOpen, setCreateOpen] = React.useState(false);

  const createLocations = React.useMemo(
    () =>
      (workspaces ?? []).filter((workspace) =>
        workspace.capabilities.includes("create_graph"),
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
    const availableGraphs = graphState.graphs ?? [];
    return availableGraphs.filter((graph) => {
      if (
        effectiveLocationId !== "all" &&
        graph.location.id !== effectiveLocationId
      ) {
        return false;
      }
      if (!normalizedQuery) return true;
      const haystack = `${graph.name} ${workspaceDisplayName(graph.location)}`.toLowerCase();
      return haystack.includes(normalizedQuery);
    });
  }, [effectiveLocationId, graphState.graphs, normalizedQuery]);
  const visibleGraphs =
    view === "recent"
      ? filteredGraphs.slice(0, RECENT_GRAPH_LIMIT)
      : filteredGraphs;
  const totalGraphCount = graphState.graphs?.length ?? 0;

  const startGraph = React.useCallback(() => {
    if (createLocations.length === 1) {
      const location = createLocations[0]!;
      router.push(workbenchGraphPath(location.slug, NEW_GRAPH_ROUTE_ID));
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
          <button
            type="button"
            className="grafy-workspace-button grafy-workspace-button--primary"
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
          </button>
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
            <select
              value={effectiveLocationId}
              aria-label="Filter by location"
              onChange={(event) => setLocationId(event.currentTarget.value)}
            >
              <option value="all">All locations</option>
              {(workspaces ?? []).map((workspace) => (
                <option key={workspace.id} value={workspace.id}>
                  {workspaceDisplayName(workspace)}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="grafy-graphs__view-bar">
          <div className="grafy-graphs__tabs" aria-label="Graph views">
            <button
              type="button"
              className={view === "recent" ? "is-active" : ""}
              aria-pressed={view === "recent"}
              onClick={() => setView("recent")}
            >
              <Clock3 size={14} aria-hidden="true" />
              Recent
            </button>
            <button
              type="button"
              className={view === "all" ? "is-active" : ""}
              aria-pressed={view === "all"}
              onClick={() => setView("all")}
            >
              <Workflow size={14} aria-hidden="true" />
              All
            </button>
          </div>
          {graphState.graphs ? (
            <span className="grafy-graphs__count">
              {filteredGraphs.length}{" "}
              {filteredGraphs.length === 1 ? "graph" : "graphs"}
              {graphState.isRefreshing ? " · refreshing…" : ""}
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
            <button
              type="button"
              className="grafy-workspace-button"
              onClick={() => void retryWorkspaces()}
            >
              <RotateCcw size={14} aria-hidden="true" /> Retry
            </button>
          </section>
        ) : !workspaces ||
          (graphState.error === null &&
            (graphState.isLoading || graphState.graphs === null)) ? (
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
            <Link className="grafy-workspace-button" href="/workspaces">
              Teams &amp; access
            </Link>
          </section>
        ) : graphState.error ? (
          <section className="grafy-graphs__state" role="alert">
            <Workflow size={22} aria-hidden="true" />
            <div>
              <h2>Graphs couldn&apos;t be loaded</h2>
              <p>Check your connection, then try again.</p>
            </div>
            <button
              type="button"
              className="grafy-workspace-button"
              onClick={() => void graphState.retry()}
            >
              <RotateCcw size={14} aria-hidden="true" /> Retry
            </button>
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
                  <button
                    type="button"
                    className="grafy-workspace-button"
                    onClick={startGraph}
                  >
                    <Plus size={14} aria-hidden="true" /> New graph
                  </button>
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
                  <button
                    type="button"
                    className="grafy-workspace-button"
                    onClick={() => setQuery("")}
                  >
                    Clear search
                  </button>
                ) : null}
              </section>
            ) : (
              <ul className="grafy-graphs__list" aria-label={`${view === "recent" ? "Recent" : "All"} graphs`}>
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
            <div className="grafy-graphs__location-options">
              {createLocations.map((location) => (
                <button
                  key={location.id}
                  type="button"
                  onClick={() => {
                    setCreateOpen(false);
                    router.push(
                      workbenchGraphPath(location.slug, NEW_GRAPH_ROUTE_ID),
                    );
                  }}
                >
                  <span aria-hidden="true">
                    {location.kind === "personal" ? (
                      <Workflow size={16} />
                    ) : (
                      <Users size={16} />
                    )}
                  </span>
                  <span>
                    <strong>{workspaceDisplayName(location)}</strong>
                    <small>
                      {location.kind === "personal"
                        ? "Private to you"
                        : "Shared with this team"}
                    </small>
                  </span>
                  <ArrowUpRight size={15} aria-hidden="true" />
                </button>
              ))}
            </div>
          </DialogBody>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default GraphBrowser;
