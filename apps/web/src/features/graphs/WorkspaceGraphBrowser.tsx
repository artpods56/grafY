"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { ArrowUpRight, Plus, RotateCcw, Search, Workflow } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { BrandLoader } from "@/components/brand";
import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";
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
  NEW_PROJECT_ROUTE_ID,
  workbenchProjectPath,
} from "@/features/workbench/routes";
import {
  useProjectSummaryRefresh,
  useWorkspacePacks,
  useWorkspaceProjects,
} from "@/hooks/use-api";
import {
  createStarterProject,
  type SavedGraphSummary,
  type StarterId,
} from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";

import { GraphViewToggle } from "./GraphViewToggle";
import { useGraphBrowserFilters } from "./use-graph-browser-filters";

const RECENT_GRAPH_LIMIT = 8;

const browserStyles = stylex.create({
  /** Keeps the strip's own spacing around the list; Notice carries none. */
  partialNotice: {
    margin: "16px 0 4px",
  },
  recipes: {
    display: "grid",
    gap: "10px",
    margin: "4px 0 18px",
  },
  recipeHeading: {
    margin: 0,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
    fontWeight: 560,
  },
  recipeRow: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
    gap: "10px",
  },
  recipe: {
    display: "grid",
    gap: "4px",
    padding: "12px 14px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusMd,
    backgroundColor: {
      default:
        "light-dark(color-mix(in srgb, white 88%, transparent), color-mix(in srgb, white 8%, transparent))",
      ":hover:not(:disabled)": tokens.colorHover,
    },
    color: tokens.colorText,
    fontFamily: "inherit",
    fontSize: tokens.fontSizeSm,
    textAlign: "start",
    cursor: {
      default: "pointer",
      ":disabled": "default",
    },
  },
  recipeTitle: {
    fontWeight: 560,
  },
  recipePath: {
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
  },
});

const RECIPES: readonly {
  id: StarterId;
  title: string;
  path: string;
}[] = [
  {
    id: "transcribe_page",
    title: "Transcribe a scanned page",
    path: "Scan or PDF → Document OCR → Text",
  },
  {
    id: "extract_table",
    title: "Extract a table from a scan",
    path: "Scan → Document OCR → Spreadsheet table",
  },
];

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
        href={workbenchProjectPath(workspaceSlug, graph.id)}
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

/**
 * The search text and the Recent/All choice live in the address, so a reload,
 * a shared link, or Back lands on the same list. See
 * {@link useGraphBrowserFilters} for how the field and the address stay in step
 * with typing.
 *
 * The filter state comes from `useSearchParams`, so the browser sits behind a
 * Suspense boundary: the shell renders before the address is known.
 */
export function WorkspaceGraphBrowser() {
  return (
    <React.Suspense fallback={<GraphBrowserLoadingShell />}>
      <WorkspaceGraphBrowserContent />
    </React.Suspense>
  );
}

function WorkspaceGraphBrowserContent() {
  const router = useRouter();
  const { workspace } = useWorkspaceContext();
  const { data, error, isLoading, mutate } = useWorkspaceProjects(workspace.id);
  const { data: packs } = useWorkspacePacks(workspace.id);
  const refreshProjects = useProjectSummaryRefresh();
  const { query, view, setQuery, setView, searchFieldRef } =
    useGraphBrowserFilters();
  const [startingRecipe, setStartingRecipe] = React.useState<StarterId | null>(
    null,
  );
  const [recipeError, setRecipeError] = React.useState<string | null>(null);

  const workspaceName = workspaceDisplayName(workspace);
  const canCreate = workspace.capabilities.includes("create_project");
  const documentOcrReady =
    packs?.some((pack) => pack.slug === "document_ocr" && pack.subscribed) ??
    false;
  const graphs = React.useMemo(
    () => filterGraphsByQuery(sortGraphsByRecency(data?.projects ?? []), query),
    [data, query],
  );
  const visibleGraphs =
    view === "recent" ? graphs.slice(0, RECENT_GRAPH_LIMIT) : graphs;

  const startGraph = () => {
    if (!canCreate) return;
    router.push(workbenchProjectPath(workspace.slug, NEW_PROJECT_ROUTE_ID));
  };

  const openRecipe = (starterId: StarterId) => {
    if (!canCreate || startingRecipe) return;
    setRecipeError(null);
    setStartingRecipe(starterId);
    void createStarterProject(workspace.id, starterId)
      .then(async (project) => {
        await refreshProjects(workspace.id);
        router.push(workbenchProjectPath(workspace.slug, project.id));
      })
      .catch((caught: unknown) => {
        setRecipeError(
          caught instanceof Error
            ? caught.message
            : "The project could not be started.",
        );
        setStartingRecipe(null);
      });
  };

  return (
    <div className="grafy-graphs">
      <main className="grafy-graphs__main">
        <header className="grafy-graphs__header">
          <div>
            <p className="grafy-graphs__eyebrow">{workspaceName}</p>
            <h1>Projects</h1>
            <p className="grafy-graphs__intro">
              Open or start a project in this workspace.
            </p>
          </div>
          <Button
            variant="primary"
            size="lg"
            className="grafy-graphs__header-action"
            disabled={!canCreate}
            title={
              canCreate
                ? undefined
                : "You do not have permission to create a project in this workspace."
            }
            onClick={startGraph}
          >
            <Plus size={15} aria-hidden="true" />
            New project
          </Button>
        </header>

        {canCreate && documentOcrReady ? (
          <section
            aria-label="Start from a recipe"
            {...stylex.props(browserStyles.recipes)}
          >
            <h2 {...stylex.props(browserStyles.recipeHeading)}>
              Start from a recipe
            </h2>
            <div {...stylex.props(browserStyles.recipeRow)}>
              {RECIPES.map((recipe) => (
                <button
                  key={recipe.id}
                  type="button"
                  disabled={startingRecipe !== null}
                  {...stylex.props(browserStyles.recipe)}
                  onClick={() => openRecipe(recipe.id)}
                >
                  <span {...stylex.props(browserStyles.recipeTitle)}>
                    {recipe.title}
                  </span>
                  <span {...stylex.props(browserStyles.recipePath)}>
                    {recipe.path}
                  </span>
                </button>
              ))}
            </div>
            {recipeError ? (
              <Notice tone="danger" variant="inline">
                {recipeError}
              </Notice>
            ) : null}
          </section>
        ) : null}

        <div className="grafy-graphs__toolbar grafy-graphs__toolbar--scoped">
          <label className="grafy-graphs__search">
            <Search size={16} aria-hidden="true" />
            <input
              ref={searchFieldRef}
              type="search"
              defaultValue={query}
              aria-label="Search projects"
              placeholder="Search projects"
              onChange={(event) => setQuery(event.currentTarget.value)}
            />
          </label>
        </div>

        <div className="grafy-graphs__view-bar">
          <GraphViewToggle value={view} onValueChange={setView} />
          {data ? (
            <span className="grafy-graphs__count">
              {graphs.length} {graphs.length === 1 ? "project" : "projects"}
            </span>
          ) : null}
        </div>

        {!data && isLoading ? (
          <GraphBrowserLoadingBlock label="Loading projects" />
        ) : !data && error ? (
          <section className="grafy-graphs__state" role="alert">
            <Workflow size={22} aria-hidden="true" />
            <div>
              <h2>Projects couldn&apos;t be loaded</h2>
              <p>Check your connection, then try again.</p>
            </div>
            <Button
              variant="secondary"
              size="lg"
              className="grafy-graphs__state-action"
              onClick={() => void mutate()}
            >
              <RotateCcw size={14} aria-hidden="true" /> Retry
            </Button>
          </section>
        ) : data?.projects.length === 0 ? (
          <section className="grafy-graphs__state grafy-graphs__state--empty">
            <Workflow size={22} aria-hidden="true" />
            <div>
              <h2>No projects yet</h2>
              <p>Create your first project in {workspaceName}.</p>
            </div>
            {canCreate ? (
              <Button
                variant="secondary"
                size="lg"
                className="grafy-graphs__state-action"
                onClick={startGraph}
              >
                <Plus size={14} aria-hidden="true" /> New project
              </Button>
            ) : null}
          </section>
        ) : visibleGraphs.length === 0 ? (
          <section className="grafy-graphs__state grafy-graphs__state--empty">
            <Search size={22} aria-hidden="true" />
            <div>
              <h2>No projects match your search</h2>
              <p>Try another project name.</p>
            </div>
            <Button
              variant="secondary"
              size="lg"
              className="grafy-graphs__state-action"
              onClick={() => setQuery("")}
            >
              Clear search
            </Button>
          </section>
        ) : (
          <ul
            className="grafy-graphs__list"
            aria-label={`${view === "recent" ? "Recent" : "All"} projects`}
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
          <Notice
            tone="neutral"
            variant="inline"
            xstyle={browserStyles.partialNotice}
            action={
              <Button size="xs" variant="ghost" onClick={() => void mutate()}>
                Retry
              </Button>
            }
          >
            The latest project list could not be refreshed.
          </Notice>
        ) : null}
      </main>
    </div>
  );
}

/** The list's own loading state, and the shell shown while the address settles. */
function GraphBrowserLoadingBlock({ label }: { label: string }) {
  return (
    <div className="grafy-graphs__loading" role="status">
      <BrandLoader size={36} label={label} />
      <span>{label}…</span>
    </div>
  );
}

function GraphBrowserLoadingShell() {
  return (
    <div className="grafy-graphs">
      <main className="grafy-graphs__main">
        <GraphBrowserLoadingBlock label="Loading projects" />
      </main>
    </div>
  );
}
