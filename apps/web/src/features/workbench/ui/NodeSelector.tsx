"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { ArrowLeft, Search } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import type { NodeRegistry, NodeSpec, Port } from "@/lib/api";
import { FINE_POINTER_QUERY, useMediaQuery } from "@/hooks/use-media-query";
import { tokens } from "@/lib/stylex/tokens.stylex";
import {
  buildCatalogFilters,
  buildSourceFilters,
  catalogNodeKey,
  catalogNodesForFilter,
  catalogNodeSpecs,
  filterAndSearchCatalogNodes,
  INPUT_NODES_FILTER,
  moduleReleaseSpecs,
  nodesCompatibleWithPort,
  sourceFilterId,
  type CatalogFilter,
} from "../model/node-catalog";
import {
  INSPECTOR_TITLE_ID,
  NodeInspector,
} from "./node-selector/NodeInspector";
import {
  CompatibilityNote,
  NodeResultList,
  RESULTS_ID,
  resultOptionId,
  type NodeResultGroup,
} from "./node-selector/NodeResultList";
import { NodeSourceBar } from "./node-selector/NodeSourceBar";

const MODULE_PLUGIN_SLUG = "graph.module";
/** Below this the picker shows the list or one node's details, not both. */
const PHONE_LAYOUT_QUERY = "(max-width: 720px)";
/** How far PageUp and PageDown move through the results. */
const PAGE_STEP = 6;

/** A port-scoped Add node invocation using the same routes as canvas wiring. */
export type NodeSelectorCompatibilityContext =
  | {
      direction: "upstream";
      port: Port & { readonly direction: "input" };
    }
  | {
      direction: "downstream";
      port: Port & { readonly direction: "output" };
    };

export interface NodeSelectorProps {
  open: boolean;
  registry: NodeRegistry;
  activeGraphId: string | null;
  /** Limits results to nodes that can connect to the invoking port. */
  compatibility?: NodeSelectorCompatibilityContext;
  /** User-facing reason the registry could not be loaded. */
  errorMessage?: string | null;
  loading?: boolean;
  /** Keeps inspection available while disabling graph mutation for viewers. */
  canInsert?: boolean;
  insertDisabledReason?: string;
  /** Controlled-dialog opener, forwarded to Base UI's finalFocus contract. */
  returnFocusRef?: React.RefObject<HTMLElement | null>;
  onOpenChange: (open: boolean) => void;
  onAddNode: (spec: NodeSpec) => void;
  onRetry?: () => void;
  onOpenGraph?: (graphId: string) => void;
  onOpenWorkspaceLibrary?: () => void;
}

/**
 * The Add node picker: a command palette over the node catalog. Typing filters
 * and ranks, the arrows move through the results without leaving the search,
 * Enter adds the highlighted node. Beside the list, the highlighted node is
 * shown as it will sit on the canvas, with what it can be wired to.
 */
export function NodeSelector({
  open,
  onOpenChange,
  returnFocusRef,
  ...browser
}: NodeSelectorProps) {
  const finePointer = useMediaQuery(FINE_POINTER_QUERY);
  const dialogRef = React.useRef<HTMLDivElement>(null);
  const searchRef = React.useRef<HTMLInputElement>(null);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        ref={dialogRef}
        size="catalog"
        aria-labelledby="node-selector-title"
        aria-describedby="node-selector-description"
        initialFocus={finePointer ? searchRef : dialogRef}
        finalFocus={returnFocusRef}
      >
        {/* Mounted with the dialog, so every opening starts from a clean search. */}
        <NodeBrowser
          {...browser}
          searchRef={searchRef}
          finePointer={finePointer}
        />
      </DialogContent>
    </Dialog>
  );
}

function NodeBrowser({
  registry,
  activeGraphId,
  compatibility,
  errorMessage = null,
  loading = false,
  canInsert = true,
  insertDisabledReason = "You do not have permission to edit this graph.",
  onAddNode,
  onRetry,
  onOpenGraph,
  onOpenWorkspaceLibrary,
  searchRef,
  finePointer,
}: Omit<NodeSelectorProps, "open" | "onOpenChange" | "returnFocusRef"> & {
  searchRef: React.RefObject<HTMLInputElement | null>;
  finePointer: boolean;
}) {
  const phoneLayout = useMediaQuery(PHONE_LAYOUT_QUERY);
  const [query, setQuery] = React.useState("");
  const [activeSourceId, setActiveSourceId] = React.useState<string>("all");
  const [artifactFilterId, setArtifactFilterId] = React.useState<string | null>(
    null,
  );
  const [inputNodesOnly, setInputNodesOnly] = React.useState(false);
  const [activeKey, setActiveKey] = React.useState<string | null>(null);
  const [chosenRelease, setChosenRelease] = React.useState<{
    moduleKey: string;
    releaseKey: string;
  } | null>(null);
  const [nodeDetailsOpen, setNodeDetailsOpen] = React.useState(false);
  const [phoneDetailsOpen, setPhoneDetailsOpen] = React.useState(false);
  const options = React.useRef(new Map<string, HTMLElement>());
  const backRef = React.useRef<HTMLButtonElement>(null);
  /** A row to focus once it renders: the phone layout's return to the list. */
  const pendingOptionFocus = React.useRef<string | null>(null);
  const showingDetailsOnly = phoneLayout && phoneDetailsOpen;

  // --- The catalog, narrowed by port, source, refinements and search ---------

  const sourceFilters = React.useMemo(
    () => buildSourceFilters(registry),
    [registry],
  );
  const artifactOptions = React.useMemo(
    () =>
      buildCatalogFilters(registry).filter(
        (filter) => filter.kind === "artifact",
      ),
    [registry],
  );
  const activeSource =
    sourceFilters.find((filter) => filter.id === activeSourceId) ??
    sourceFilters[0]!;
  const refinements = React.useMemo((): CatalogFilter[] => {
    const artifact = artifactOptions.find(
      (filter) => filter.id === artifactFilterId,
    );
    return [
      ...(artifact ? [artifact] : []),
      ...(inputNodesOnly ? [INPUT_NODES_FILTER] : []),
    ];
  }, [artifactFilterId, artifactOptions, inputNodesOnly]);

  const catalogNodes = React.useMemo(
    () => catalogNodeSpecs(registry, activeGraphId),
    [activeGraphId, registry],
  );
  const reachableNodes = React.useMemo(
    () =>
      compatibility
        ? nodesCompatibleWithPort(catalogNodes, compatibility, registry)
        : catalogNodes,
    [catalogNodes, compatibility, registry],
  );
  const catalogRegistry = React.useMemo(
    () => ({ ...registry, nodes: catalogNodes }),
    [catalogNodes, registry],
  );
  const sourceCounts = React.useMemo(
    () =>
      new Map(
        sourceFilters.map((filter) => [
          filter.id,
          filterAndSearchCatalogNodes(
            reachableNodes,
            [filter, ...refinements],
            "",
            registry,
          ).length,
        ]),
      ),
    [reachableNodes, refinements, registry, sourceFilters],
  );
  const searching = query.trim() !== "";
  const foundNodes = React.useMemo(
    () =>
      loading || errorMessage
        ? []
        : filterAndSearchCatalogNodes(
            reachableNodes,
            [activeSource, ...refinements],
            query,
            registry,
          ),
    [
      activeSource,
      errorMessage,
      loading,
      query,
      reachableNodes,
      refinements,
      registry,
    ],
  );
  // Browsing everything reads by source; a search reads by relevance.
  const groups = React.useMemo(
    (): NodeResultGroup[] =>
      activeSource.kind === "all" && !searching
        ? groupBySource(foundNodes, sourceFilters)
        : [{ key: "results", title: null, nodes: foundNodes }],
    [activeSource.kind, foundNodes, searching, sourceFilters],
  );
  const orderedNodes = React.useMemo(
    () => groups.flatMap((group) => group.nodes),
    [groups],
  );

  // --- The highlighted node, and the release of it a Module call would pin ---

  const listedSpec =
    orderedNodes.find((spec) => catalogNodeKey(spec) === activeKey) ??
    orderedNodes[0] ??
    null;
  const listedKey = listedSpec ? catalogNodeKey(listedSpec) : null;
  const moduleKey =
    listedSpec?.module_id ?? listedSpec?.module_graph_id ?? null;
  const moduleReleases = React.useMemo(
    () =>
      listedSpec?.plugin_slug === MODULE_PLUGIN_SLUG
        ? moduleReleaseSpecs(
            registry,
            listedSpec.module_id,
            listedSpec.module_graph_id,
          )
        : [],
    [listedSpec, registry],
  );
  const selectedSpec = React.useMemo(() => {
    if (!listedSpec || listedSpec.plugin_slug !== MODULE_PLUGIN_SLUG) {
      return listedSpec;
    }
    const releaseKey =
      moduleKey && chosenRelease?.moduleKey === moduleKey
        ? chosenRelease.releaseKey
        : null;
    return (
      moduleReleases.find((spec) => catalogNodeKey(spec) === releaseKey) ??
      moduleReleases.find((spec) => spec.catalog_visible !== false) ??
      moduleReleases[0] ??
      listedSpec
    );
  }, [chosenRelease, listedSpec, moduleKey, moduleReleases]);

  // --- Moving, choosing, adding ----------------------------------------------

  const registerOption = React.useCallback(
    (key: string) => (element: HTMLElement | null) => {
      if (element) options.current.set(key, element);
      else options.current.delete(key);
    },
    [],
  );

  React.useEffect(() => {
    if (listedKey === null) return;
    options.current.get(listedKey)?.scrollIntoView?.({ block: "nearest" });
  }, [listedKey]);

  React.useEffect(() => {
    if (showingDetailsOnly) {
      pendingOptionFocus.current = null;
      backRef.current?.focus();
      return;
    }
    const key = pendingOptionFocus.current;
    if (key === null) return;
    pendingOptionFocus.current = null;
    options.current.get(key)?.focus();
  }, [showingDetailsOnly]);

  /** Moves the highlight; `focusRow` also moves focus there (list-focused keys). */
  function moveActive(target: number, focusRow: boolean): void {
    if (!orderedNodes.length) return;
    const index = Math.max(0, Math.min(target, orderedNodes.length - 1));
    const key = catalogNodeKey(orderedNodes[index]!);
    setActiveKey(key);
    if (focusRow) options.current.get(key)?.focus();
  }

  function activeIndex(): number {
    return listedKey === null
      ? -1
      : orderedNodes.findIndex((spec) => catalogNodeKey(spec) === listedKey);
  }

  /** Arrow keys, paging and Enter, from the search field or from a row. */
  function navigate(
    event: React.KeyboardEvent<HTMLElement>,
    focusRow: boolean,
  ): boolean {
    const index = activeIndex();
    const moves: Record<string, number> = {
      ArrowDown: index + 1,
      ArrowUp: index - 1,
      PageDown: index + PAGE_STEP,
      PageUp: index - PAGE_STEP,
    };
    if (focusRow) {
      moves.Home = 0;
      moves.End = orderedNodes.length - 1;
    }
    const target = moves[event.key];
    if (target !== undefined) {
      event.preventDefault();
      moveActive(target, focusRow);
      return true;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      if (selectedSpec) insertNode(selectedSpec);
      return true;
    }
    return false;
  }

  function insertNode(spec: NodeSpec): void {
    if (!canInsert || spec.runnable === false) return;
    if (
      spec.publication_state === "deprecated" &&
      !window.confirm(
        `Insert deprecated Module “${spec.title}”? New inserts are discouraged. Existing pinned calls keep working.`,
      )
    ) {
      return;
    }
    onAddNode(spec);
  }

  function changeQuery(next: string): void {
    setQuery(next);
    setActiveKey(null);
  }

  function selectSource(id: string): void {
    setActiveSourceId(id);
    setActiveKey(null);
  }

  function resetSearchAndFilters(): void {
    setQuery("");
    setActiveSourceId("all");
    setArtifactFilterId(null);
    setInputNodesOnly(false);
    setActiveKey(null);
  }

  /** Shows a node from "Works with": its own source, nothing filtering it out. */
  function inspectCatalogNode(spec: NodeSpec): void {
    resetSearchAndFilters();
    setActiveSourceId(
      spec.plugin_slug === MODULE_PLUGIN_SLUG
        ? "workspace-library"
        : sourceFilterId(spec.plugin_slug),
    );
    setActiveKey(catalogNodeKey(spec));
    setChosenRelease(null);
  }

  // --- What the list says -----------------------------------------------------

  const listTitle =
    activeSource.id === "all"
      ? "All nodes"
      : activeSource.id === "workspace-library"
        ? "Workspace library"
        : `${activeSource.title} nodes`;
  const status = loading
    ? "Loading nodes…"
    : errorMessage
      ? "Nodes could not be loaded."
      : foundNodes.length === 0
        ? "No nodes found."
        : `${foundNodes.length} ${foundNodes.length === 1 ? "node" : "nodes"}.`;
  const narrowed =
    searching ||
    activeSourceId !== "all" ||
    artifactFilterId !== null ||
    inputNodesOnly;
  const showingModules = activeSourceId === "workspace-library";
  const editedModule = activeGraphId
    ? registry.nodes.find(
        (spec) =>
          spec.module_graph_id === activeGraphId &&
          spec.catalog_visible !== false,
      )
    : undefined;

  return (
    <>
      <div
        {...stylex.props(s.header, showingDetailsOnly && s.headerPhoneDetails)}
      >
        <div {...stylex.props(s.visuallyHidden)}>
          <DialogTitle id="node-selector-title">Add node</DialogTitle>
          <DialogDescription
            id="node-selector-description"
            {...stylex.props(s.visuallyHidden)}
          >
            Choose what to add to your workflow.
          </DialogDescription>
        </div>
        <label {...stylex.props(s.search, showingDetailsOnly && s.hidden)}>
          <Search
            size={15}
            aria-hidden="true"
            {...stylex.props(s.searchIcon)}
          />
          <input
            ref={searchRef}
            aria-label="Search nodes"
            aria-autocomplete="list"
            aria-controls={RESULTS_ID}
            aria-activedescendant={
              listedSpec ? resultOptionId(listedSpec) : undefined
            }
            value={query}
            placeholder="Search nodes, types, settings…"
            autoComplete="off"
            spellCheck={false}
            onChange={(event) => changeQuery(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape" && query !== "") {
                // The first Escape clears the search; the next closes.
                event.preventDefault();
                event.stopPropagation();
                changeQuery("");
                return;
              }
              navigate(event, false);
            }}
            {...stylex.props(s.searchInput)}
          />
        </label>
      </div>

      {showingDetailsOnly ? null : (
        <>
          <NodeSourceBar
            sources={sourceFilters}
            counts={sourceCounts}
            activeSourceId={activeSourceId}
            artifactOptions={artifactOptions}
            artifactFilterId={artifactFilterId}
            inputNodesOnly={inputNodesOnly}
            onSelectSource={selectSource}
            onArtifactFilterChange={(id) => {
              setArtifactFilterId(id);
              setActiveKey(null);
            }}
            onInputNodesOnlyChange={(next) => {
              setInputNodesOnly(next);
              setActiveKey(null);
            }}
          />
          {compatibility ? (
            <CompatibilityNote
              direction={compatibility.direction}
              portTitle={compatibility.port.title ?? compatibility.port.name}
            />
          ) : null}
        </>
      )}

      <div {...stylex.props(s.layout, showingDetailsOnly && s.detailsLayout)}>
        <NodeResultList
          label={listTitle}
          status={status}
          errorMessage={errorMessage}
          loading={loading}
          groups={groups}
          activeKey={listedKey}
          hidden={showingDetailsOnly}
          keepSearchFocus={finePointer}
          empty={
            <>
              <span>
                {compatibility
                  ? "No nodes match this port and the current search or filter."
                  : showingModules
                    ? "No published Modules match the current search."
                    : "No nodes match the current search or filter."}
              </span>
              {narrowed ? (
                <button
                  type="button"
                  onClick={resetSearchAndFilters}
                  {...stylex.props(s.textButton)}
                >
                  Reset search and filter
                </button>
              ) : null}
            </>
          }
          footer={
            showingModules && !loading && !errorMessage ? (
              <ModuleNotes
                editedModule={editedModule}
                empty={foundNodes.length === 0 && !searching}
                forPort={Boolean(compatibility)}
                onOpenWorkspaceLibrary={onOpenWorkspaceLibrary}
              />
            ) : null
          }
          registerOption={registerOption}
          onActivate={setActiveKey}
          onChoose={(key) => {
            setActiveKey(key);
            setPhoneDetailsOpen(true);
          }}
          onInsert={insertNode}
          onRetry={onRetry}
          onKeyDown={(event) => {
            if (
              event.target instanceof HTMLElement &&
              event.target.getAttribute("role") === "option"
            ) {
              navigate(event, true);
            }
          }}
        />

        <aside
          aria-label="Node information"
          aria-labelledby={selectedSpec ? INSPECTOR_TITLE_ID : undefined}
          {...stylex.props(
            s.inspector,
            phoneLayout && !phoneDetailsOpen && s.hidden,
          )}
        >
          {selectedSpec ? (
            <NodeInspector
              key={catalogNodeKey(selectedSpec)}
              spec={selectedSpec}
              registry={registry}
              catalogRegistry={catalogRegistry}
              moduleReleases={moduleReleases}
              detailsOpen={nodeDetailsOpen}
              canInsert={canInsert}
              insertDisabledReason={insertDisabledReason}
              showEnterHint={finePointer}
              leading={
                showingDetailsOnly ? (
                  <button
                    ref={backRef}
                    type="button"
                    onClick={() => {
                      pendingOptionFocus.current = listedKey;
                      setPhoneDetailsOpen(false);
                    }}
                    {...stylex.props(s.backButton)}
                  >
                    <ArrowLeft size={16} aria-hidden="true" /> Back to results
                  </button>
                ) : null
              }
              onDetailsOpenChange={setNodeDetailsOpen}
              onSelectRelease={(releaseKey) => {
                if (moduleKey) setChosenRelease({ moduleKey, releaseKey });
              }}
              onInspect={inspectCatalogNode}
              onInsert={() => insertNode(selectedSpec)}
              onOpenGraph={onOpenGraph}
            />
          ) : (
            <div {...stylex.props(s.empty)}>
              {loading
                ? "Loading node details…"
                : errorMessage
                  ? "Node details are unavailable until the list loads."
                  : "Select a node to inspect its contract."}
            </div>
          )}
        </aside>
      </div>
    </>
  );
}

/**
 * Splits nodes into the sources the rail lists, in the rail's order. Anything
 * no source claims still shows, under Other, rather than vanishing.
 */
function groupBySource(
  nodes: readonly NodeSpec[],
  sources: readonly CatalogFilter[],
): NodeResultGroup[] {
  const claimed = new Set<string>();
  const groups: NodeResultGroup[] = [];
  for (const source of sources) {
    if (source.kind === "all") continue;
    const members = catalogNodesForFilter(nodes, source).filter(
      (spec) => !claimed.has(catalogNodeKey(spec)),
    );
    if (!members.length) continue;
    for (const spec of members) claimed.add(catalogNodeKey(spec));
    groups.push({ key: source.id, title: source.title, nodes: members });
  }
  const rest = nodes.filter((spec) => !claimed.has(catalogNodeKey(spec)));
  if (rest.length) groups.push({ key: "other", title: "Other", nodes: rest });
  return groups;
}

function ModuleNotes({
  editedModule,
  empty,
  forPort,
  onOpenWorkspaceLibrary,
}: {
  editedModule: NodeSpec | undefined;
  empty: boolean;
  forPort: boolean;
  onOpenWorkspaceLibrary?: () => void;
}) {
  if (!editedModule && !empty) return null;
  return (
    <div aria-label="Workspace library notes" {...stylex.props(s.moduleNotes)}>
      {editedModule ? (
        <p {...stylex.props(s.note)}>
          “{editedModule.title}” is hidden here because it is the graph
          currently being edited.
        </p>
      ) : null}
      {empty ? (
        <p {...stylex.props(s.note)}>
          {forPort
            ? "No published Modules in this workspace can connect to this port."
            : "No published Modules in this workspace yet. Open a source graph, declare Module Input/Output boundaries, then Publish release."}
          {onOpenWorkspaceLibrary ? (
            <>
              {" "}
              <button
                type="button"
                onClick={onOpenWorkspaceLibrary}
                {...stylex.props(s.textButton)}
              >
                Open workspace library
              </button>
            </>
          ) : null}
        </p>
      ) : null}
    </div>
  );
}

const s = stylex.create({
  /** The search is the header; the dialog's close button sits at its end. */
  header: {
    flexShrink: 0,
    padding: {
      default: "12px 56px 10px 12px",
      "@media (max-width: 720px)": "12px 60px 10px 12px",
    },
  },
  headerPhoneDetails: { display: "none" },
  search: {
    position: "relative",
    minWidth: 0,
    height: { default: "42px", "@media (pointer: coarse)": "46px" },
    display: "flex",
    alignItems: "center",
    gap: "10px",
    paddingInline: "13px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: {
      default: tokens.colorBorder,
      ":focus-within": tokens.colorBorderStrong,
    },
    borderRadius: "10px",
    backgroundColor: {
      default: tokens.colorSurfaceSunken,
      ":focus-within": tokens.colorBg,
    },
    color: tokens.colorSubtle,
    cursor: "text",
    transitionProperty: "border-color, background-color",
    transitionDuration: "120ms",
  },
  searchIcon: { flexShrink: 0 },
  searchInput: {
    minWidth: 0,
    flex: 1,
    height: "100%",
    padding: 0,
    borderWidth: 0,
    backgroundColor: "transparent",
    color: tokens.colorText,
    fontFamily: "inherit",
    fontSize: "14px",
    outline: "none",
    "::placeholder": { color: tokens.colorSubtle },
  },
  hidden: { display: "none" },
  layout: {
    minHeight: 0,
    flex: 1,
    display: "grid",
    overflow: "hidden",
    overscrollBehaviorY: "contain",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
    paddingBottom: {
      default: 0,
      "@media (max-width: 720px)": "env(safe-area-inset-bottom, 0px)",
    },
    gridTemplateColumns: {
      default: "minmax(0, 1fr) 380px",
      "@media (max-width: 1024px)": "minmax(0, 1fr) minmax(0, 1fr)",
      "@media (max-width: 720px)": "1fr",
    },
    gridTemplateRows: "minmax(0, 1fr)",
    gridTemplateAreas: {
      default: '"nodes inspector"',
      "@media (max-width: 720px)": '"nodes"',
    },
  },
  detailsLayout: {
    borderTopWidth: 0,
    gridTemplateColumns: "minmax(0, 1fr)",
    gridTemplateAreas: '"inspector"',
  },
  inspector: {
    gridArea: "inspector",
    minWidth: 0,
    minHeight: 0,
    display: "flex",
    flexDirection: "column",
    borderLeftWidth: { default: 1, "@media (max-width: 720px)": 0 },
    borderLeftStyle: "solid",
    borderLeftColor: tokens.colorDivider,
    backgroundColor: tokens.colorSurface,
  },
  backButton: {
    minHeight: "40px",
    display: "inline-flex",
    alignItems: "center",
    alignSelf: "flex-start",
    flexShrink: 0,
    gap: "6px",
    margin: "8px 8px 0",
    paddingInline: "10px 14px",
    borderWidth: 0,
    borderRadius: "8px",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: tokens.colorText,
    fontFamily: "inherit",
    fontSize: tokens.fontSizeSm,
    cursor: "pointer",
    outlineColor: tokens.colorBorderStrong,
    outlineStyle: "solid",
    outlineOffset: "0",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
  },

  empty: {
    minHeight: "160px",
    display: "grid",
    placeItems: "center",
    padding: "24px",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeSm,
    textAlign: "center",
  },
  moduleNotes: {
    display: "grid",
    gap: "8px",
    padding: "12px 14px 16px",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorBorder,
    backgroundColor: tokens.colorSurfaceMuted,
  },
  note: {
    margin: 0,
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
  textButton: {
    minHeight: "29px",
    paddingInline: "10px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorderStrong,
    borderRadius: "5px",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: tokens.colorMuted,
    cursor: "pointer",
    fontSize: tokens.fontSizeXs,
    fontWeight: 700,
  },
  visuallyHidden: {
    position: "absolute",
    width: "1px",
    height: "1px",
    padding: 0,
    margin: "-1px",
    overflow: "hidden",
    clip: "rect(0, 0, 0, 0)",
    whiteSpace: "nowrap",
    borderWidth: 0,
  },
});
