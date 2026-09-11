"use client";

import * as React from "react";
import {
  ArrowUpRight,
  Clock3,
  Plus,
  RotateCcw,
  Search,
  Workflow,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { BrandLoader } from "@/components/brand";
import {
  useWorkspaceContext,
  workspaceDisplayName,
} from "@/features/workspaces/WorkspaceLayout";
import {
  filterGraphsByQuery,
  graphAgeLabel,
  graphCountLabel,
  sortGraphsByRecency,
} from "@/features/workspaces/WorkspaceGraphPanel";
import {
  NEW_GRAPH_ROUTE_ID,
  workbenchGraphPath,
} from "@/features/workbench/routes";
import { useSavedGraphs } from "@/hooks/use-api";
import type { SavedGraphSummary } from "@/lib/api";

type GraphBrowserView = "recent" | "all";

const RECENT_GRAPH_LIMIT = 8;

function GraphRow({
  graph,
  workspaceSlug,
  workspaceName,
}: {
  graph: SavedGraphSummary;
  workspaceSlug: string;
  workspaceName: string;
}) {
  return (
    <li>
      <Link
        href={workbenchGraphPath(workspaceSlug, graph.id)}
        className="grafy-graphs__row"
        aria-label={`Open ${graph.name} in ${workspaceName}`}
      >
        <span className="grafy-graphs__row-icon" aria-hidden="true">
          <Workflow size={16} />
        </span>
        <span className="grafy-graphs__row-title">{graph.name}</span>
        <span className="grafy-graphs__row-location">{workspaceName}</span>
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

export function WorkspaceGraphBrowser() {
  const router = useRouter();
  const { workspace } = useWorkspaceContext();
  const { data, error, isLoading, mutate } = useSavedGraphs(workspace.id);
  const [query, setQuery] = React.useState("");
  const [view, setView] = React.useState<GraphBrowserView>("recent");

  const workspaceName = workspaceDisplayName(workspace);
  const canCreate = workspace.capabilities.includes("create_graph");
  const graphs = React.useMemo(
    () =>
      filterGraphsByQuery(
        sortGraphsByRecency(data?.graphs ?? []),
        query,
      ),
    [data, query],
  );
  const visibleGraphs =
    view === "recent" ? graphs.slice(0, RECENT_GRAPH_LIMIT) : graphs;

  const startGraph = () => {
    if (!canCreate) return;
    router.push(workbenchGraphPath(workspace.slug, NEW_GRAPH_ROUTE_ID));
  };

  return (
    <div className="grafy-graphs">
      <main className="grafy-graphs__main">
        <header className="grafy-graphs__header">
          <div>
            <p className="grafy-graphs__eyebrow">{workspaceName}</p>
            <h1>Graphs</h1>
            <p className="grafy-graphs__intro">
              Find and open graphs in this workspace.
            </p>
          </div>
          <button
            type="button"
            className="grafy-workspace-button grafy-workspace-button--primary"
            disabled={!canCreate}
            title={
              canCreate
                ? undefined
                : "You do not have permission to create a graph in this workspace."
            }
            onClick={startGraph}
          >
            <Plus size={15} aria-hidden="true" />
            New graph
          </button>
        </header>

        <div className="grafy-graphs__toolbar grafy-graphs__toolbar--scoped">
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
          {data ? (
            <span className="grafy-graphs__count">
              {graphs.length} {graphs.length === 1 ? "graph" : "graphs"}
            </span>
          ) : null}
        </div>

        {!data && isLoading ? (
          <div className="grafy-graphs__loading" role="status">
            <BrandLoader size={36} label="Loading graphs" />
            <span>Loading graphs…</span>
          </div>
        ) : !data && error ? (
          <section className="grafy-graphs__state" role="alert">
            <Workflow size={22} aria-hidden="true" />
            <div>
              <h2>Graphs couldn&apos;t be loaded</h2>
              <p>Check your connection, then try again.</p>
            </div>
            <button
              type="button"
              className="grafy-workspace-button"
              onClick={() => void mutate()}
            >
              <RotateCcw size={14} aria-hidden="true" /> Retry
            </button>
          </section>
        ) : data?.graphs.length === 0 ? (
          <section className="grafy-graphs__state grafy-graphs__state--empty">
            <Workflow size={22} aria-hidden="true" />
            <div>
              <h2>No graphs yet</h2>
              <p>Create your first graph in {workspaceName}.</p>
            </div>
            {canCreate ? (
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
              <h2>No graphs match your search</h2>
              <p>Try another graph name.</p>
            </div>
            <button
              type="button"
              className="grafy-workspace-button"
              onClick={() => setQuery("")}
            >
              Clear search
            </button>
          </section>
        ) : (
          <ul
            className="grafy-graphs__list"
            aria-label={`${view === "recent" ? "Recent" : "All"} graphs`}
          >
            {visibleGraphs.map((graph) => (
              <GraphRow
                key={graph.id}
                graph={graph}
                workspaceSlug={workspace.slug}
                workspaceName={workspaceName}
              />
            ))}
          </ul>
        )}

        {data && error ? (
          <p className="grafy-graphs__partial" role="status">
            The latest graph list could not be refreshed.
            <button type="button" onClick={() => void mutate()}>
              Retry
            </button>
          </p>
        ) : null}
      </main>
    </div>
  );
}

export default WorkspaceGraphBrowser;
