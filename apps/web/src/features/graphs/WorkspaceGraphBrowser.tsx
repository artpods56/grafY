"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  ArrowUpRight,
  FileText,
  Plus,
  RotateCcw,
  Search,
  Table2,
  Workflow,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { BrandLoader } from "@/components/brand";
import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";
import { phoneTouch } from "@/components/ui/touch-target";
import {
  useWorkspaceContext,
  workspaceDisplayName,
} from "@/features/workspaces/WorkspaceLayout";
import {
  filterGraphsByQuery,
  graphAgeLabel,
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

import { GraphViewToggle } from "./GraphViewToggle";
import { browserStyles } from "./WorkspaceGraphBrowser.styles";
import { useGraphBrowserFilters } from "./use-graph-browser-filters";

const RECENT_GRAPH_LIMIT = 8;

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

function recipeIcon(id: StarterId) {
  if (id === "extract_table") {
    return <Table2 size={16} aria-hidden="true" />;
  }
  return <FileText size={16} aria-hidden="true" />;
}

function projectStepLabel(count: number): string {
  return `${count} ${count === 1 ? "step" : "steps"}`;
}

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
    <li {...stylex.props(browserStyles.listItem)}>
      {/* The marker is what lets `rowArrow` answer this row's own hover. */}
      <Link
        href={workbenchProjectPath(workspaceSlug, graph.id)}
        aria-label={`Open ${graph.name} in ${workspaceName}`}
        {...stylex.props(browserStyles.row, stylex.defaultMarker())}
      >
        <span {...stylex.props(browserStyles.rowIcon)} aria-hidden="true">
          <Workflow size={15} />
        </span>
        <span
          {...stylex.props(browserStyles.rowTruncate, browserStyles.rowTitle)}
        >
          {graph.name}
        </span>
        <span
          {...stylex.props(browserStyles.rowTruncate, browserStyles.rowMeta)}
        >
          {projectStepLabel(graph.node_count)}
        </span>
        <span
          {...stylex.props(browserStyles.rowTruncate, browserStyles.rowAge)}
        >
          {graphAgeLabel(graph.updated_at)}
        </span>
        <ArrowUpRight
          size={15}
          aria-hidden="true"
          {...stylex.props(browserStyles.rowArrow)}
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
  const workspaceBadgeLabel =
    workspace.kind === "personal" ? "Personal" : workspaceName;
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
    <div {...stylex.props(browserStyles.root)}>
      <header {...stylex.props(browserStyles.topBar)}>
        <div {...stylex.props(browserStyles.topBarInner)}>
          <div {...stylex.props(browserStyles.topBarTitleGroup)}>
            <h1 {...stylex.props(browserStyles.pageTitle)}>Projects</h1>
            <span {...stylex.props(browserStyles.workspaceBadge)}>
              {workspaceBadgeLabel}
            </span>
          </div>
          <div {...stylex.props(browserStyles.topBarActions)}>
            <label {...stylex.props(browserStyles.search)}>
              <Search size={14} aria-hidden="true" />
              <input
                ref={searchFieldRef}
                type="search"
                defaultValue={query}
                aria-label="Search projects"
                placeholder="Search projects…"
                {...stylex.props(browserStyles.searchInput)}
                onChange={(event) => setQuery(event.currentTarget.value)}
              />
            </label>
            <Button
              variant="primary"
              size="md"
              xstyle={[phoneTouch.on, browserStyles.headerAction]}
              disabled={!canCreate}
              title={
                canCreate
                  ? undefined
                  : "You do not have permission to create a project in this workspace."
              }
              onClick={startGraph}
            >
              <Plus size={14} aria-hidden="true" />
              New project
            </Button>
          </div>
        </div>
      </header>

      <main {...stylex.props(browserStyles.main)}>
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
                  <span
                    {...stylex.props(browserStyles.recipeIcon)}
                    aria-hidden="true"
                  >
                    {recipeIcon(recipe.id)}
                  </span>
                  <span {...stylex.props(browserStyles.recipeBody)}>
                    <span {...stylex.props(browserStyles.recipeTitle)}>
                      {recipe.title}
                    </span>
                    <span {...stylex.props(browserStyles.recipePath)}>
                      {recipe.path}
                    </span>
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

        <section
          aria-label="Workspace projects"
          {...stylex.props(browserStyles.card)}
        >
          <div {...stylex.props(browserStyles.viewBar)}>
            <GraphViewToggle value={view} onValueChange={setView} />
            {data ? (
              <span {...stylex.props(browserStyles.count)}>
                {graphs.length} {graphs.length === 1 ? "project" : "projects"}
              </span>
            ) : null}
          </div>

          {!data && isLoading ? (
            <GraphBrowserLoadingBlock label="Loading projects" />
          ) : !data && error ? (
            <section role="alert" {...stylex.props(browserStyles.state)}>
              <span
                {...stylex.props(browserStyles.stateIcon)}
                aria-hidden="true"
              >
                <Workflow size={16} />
              </span>
              <div>
                <h2 {...stylex.props(browserStyles.stateTitle)}>
                  Projects couldn&apos;t be loaded
                </h2>
                <p {...stylex.props(browserStyles.stateBody)}>
                  Check your connection, then try again.
                </p>
              </div>
              <Button
                variant="secondary"
                size="md"
                xstyle={[phoneTouch.on, browserStyles.stateAction]}
                onClick={() => void mutate()}
              >
                <RotateCcw size={14} aria-hidden="true" /> Retry
              </Button>
            </section>
          ) : data?.projects.length === 0 ? (
            <section
              {...stylex.props(browserStyles.state, browserStyles.stateEmpty)}
            >
              <span
                {...stylex.props(browserStyles.stateIcon)}
                aria-hidden="true"
              >
                <Workflow size={16} />
              </span>
              <div>
                <h2 {...stylex.props(browserStyles.stateTitle)}>
                  No projects yet
                </h2>
                <p {...stylex.props(browserStyles.stateBody)}>
                  Create your first project in {workspaceName}.
                </p>
              </div>
              {canCreate ? (
                <Button
                  variant="secondary"
                  size="md"
                  xstyle={[phoneTouch.on, browserStyles.stateAction]}
                  onClick={startGraph}
                >
                  <Plus size={14} aria-hidden="true" /> New project
                </Button>
              ) : null}
            </section>
          ) : visibleGraphs.length === 0 ? (
            <section
              {...stylex.props(browserStyles.state, browserStyles.stateEmpty)}
            >
              <span
                {...stylex.props(browserStyles.stateIcon)}
                aria-hidden="true"
              >
                <Search size={16} />
              </span>
              <div>
                <h2 {...stylex.props(browserStyles.stateTitle)}>
                  No projects match your search
                </h2>
                <p {...stylex.props(browserStyles.stateBody)}>
                  Try another project name.
                </p>
              </div>
              <Button
                variant="secondary"
                size="md"
                xstyle={[phoneTouch.on, browserStyles.stateAction]}
                onClick={() => setQuery("")}
              >
                Clear search
              </Button>
            </section>
          ) : (
            <ul
              aria-label={`${view === "recent" ? "Recent" : "All"} projects`}
              {...stylex.props(browserStyles.list)}
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
        </section>

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
    <div role="status" {...stylex.props(browserStyles.loading)}>
      <BrandLoader size={36} label={label} />
      <span>{label}…</span>
    </div>
  );
}

function GraphBrowserLoadingShell() {
  return (
    <div {...stylex.props(browserStyles.root)}>
      <header {...stylex.props(browserStyles.topBar)}>
        <div {...stylex.props(browserStyles.topBarInner)}>
          <div {...stylex.props(browserStyles.topBarTitleGroup)}>
            <h1 {...stylex.props(browserStyles.pageTitle)}>Projects</h1>
          </div>
        </div>
      </header>
      <main {...stylex.props(browserStyles.main)}>
        <section {...stylex.props(browserStyles.card)}>
          <GraphBrowserLoadingBlock label="Loading projects" />
        </section>
      </main>
    </div>
  );
}
