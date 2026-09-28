"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  ArrowLeft,
  Cable,
  ExternalLink,
  Plus,
  Search,
  Settings2,
  Workflow,
} from "lucide-react";

import { schemaFields } from "../canvas/config-schema";
import { artifactTypeColor } from "../canvas/nodes.css";
import {
  artifactTitleFor,
  CatalogNodePreview,
  fieldTypeLabel,
  portKey,
} from "./CatalogNodePreview";
import { portArtifactType } from "../canvas/types";
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
  catalogNodeSpecs,
  filterAndSearchCatalogNodes,
  INPUT_NODES_FILTER,
  moduleReleaseSpecs,
  nodesCompatibleWithPort,
  sourceFilterId,
} from "../model/node-catalog";
import { fieldConstraintLabel } from "./node-selector/catalog-labels";
import {
  compatibleNodesForPort,
  MODULE_PLUGIN_SLUG,
  nodeKey,
  pluginFor,
} from "./node-selector/compatibility";
import { PortList } from "./node-selector/PortList";
import { SourceFilterIcon } from "./node-selector/SourceFilterIcon";
import { WorksWithSection } from "./node-selector/WorksWithSection";
import { styles as s } from "./node-selector/styles";

const MOBILE_NODE_SELECTOR_QUERY = "(max-width: 720px)";

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

export function NodeSelector({
  open,
  registry,
  activeGraphId,
  compatibility,
  errorMessage = null,
  loading = false,
  canInsert = true,
  insertDisabledReason = "You do not have permission to edit this graph.",
  returnFocusRef: providedReturnFocusRef,
  onOpenChange,
  onAddNode,
  onRetry,
  onOpenGraph,
  onOpenWorkspaceLibrary,
}: NodeSelectorProps) {
  const mobileNodeSelector = useMediaQuery(MOBILE_NODE_SELECTOR_QUERY);
  const finePointer = useMediaQuery(FINE_POINTER_QUERY);
  const [query, setQuery] = React.useState("");
  const [activeSourceId, setActiveSourceId] = React.useState<string>("all");
  const [artifactFilterId, setArtifactFilterId] = React.useState<string | null>(
    null,
  );
  const [inputNodesOnly, setInputNodesOnly] = React.useState(false);
  const [selectedNodeKey, setSelectedNodeKey] = React.useState<string | null>(
    null,
  );
  const [selectedRelease, setSelectedRelease] = React.useState<{
    moduleKey: string;
    releaseKey: string;
  } | null>(null);
  const [technicalDetailsOpen, setTechnicalDetailsOpen] = React.useState(false);
  const [detailsOpen, setDetailsOpen] = React.useState(false);
  const [filtersOpen, setFiltersOpen] = React.useState(false);
  const [compatibilityPortSelection, setCompatibilityPortSelection] =
    React.useState<{ specKey: string; portKey: string } | null>(null);
  const resultRefs = React.useRef(new Map<string, HTMLButtonElement>());
  const filterRefs = React.useRef(new Map<string, HTMLButtonElement>());
  const dialogRef = React.useRef<HTMLDivElement>(null);
  const searchRef = React.useRef<HTMLInputElement>(null);
  const backRef = React.useRef<HTMLButtonElement>(null);
  const pendingResultFocusKey = React.useRef<string | null>(null);
  const wasOpen = React.useRef(false);

  const catalogFilters = React.useMemo(
    () => buildCatalogFilters(registry),
    [registry],
  );
  const sourceFilters = React.useMemo(
    () => buildSourceFilters(registry),
    [registry],
  );
  const artifactOptions = React.useMemo(
    () => catalogFilters.filter((filter) => filter.kind === "artifact"),
    [catalogFilters],
  );
  const activeSourceFilter =
    sourceFilters.find((filter) => filter.id === activeSourceId) ??
    sourceFilters[0]!;
  const activeArtifactFilter =
    artifactOptions.find((filter) => filter.id === artifactFilterId) ?? null;
  const refinementFilters = React.useMemo(
    () => [
      ...(activeArtifactFilter ? [activeArtifactFilter] : []),
      ...(inputNodesOnly ? [INPUT_NODES_FILTER] : []),
    ],
    [activeArtifactFilter, inputNodesOnly],
  );

  const catalogNodes = React.useMemo(
    () => catalogNodeSpecs(registry, activeGraphId),
    [activeGraphId, registry],
  );
  const compatibleCatalogNodes = React.useMemo(
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
  const showingModules = activeSourceId === "workspace-library";
  const activeEditingModule = React.useMemo(
    () =>
      activeGraphId
        ? (registry.nodes.find(
            (spec) =>
              spec.module_graph_id === activeGraphId &&
              spec.catalog_visible !== false,
          ) ?? null)
        : null,
    [activeGraphId, registry.nodes],
  );

  React.useEffect(() => {
    if (open && !wasOpen.current) {
      setQuery("");
      setActiveSourceId("all");
      setArtifactFilterId(null);
      setInputNodesOnly(false);
      setSelectedNodeKey(null);
      setSelectedRelease(null);
      setTechnicalDetailsOpen(false);
      setDetailsOpen(false);
      setFiltersOpen(false);
      setCompatibilityPortSelection(null);
    }
    wasOpen.current = open;
  }, [open]);

  const normalizedQuery = query.trim().toLowerCase();
  const filteredNodes = React.useMemo(() => {
    if (loading || errorMessage) return [];
    return filterAndSearchCatalogNodes(
      compatibleCatalogNodes,
      [activeSourceFilter, ...refinementFilters],
      query,
      registry,
    );
  }, [
    activeSourceFilter,
    compatibleCatalogNodes,
    errorMessage,
    loading,
    query,
    refinementFilters,
    registry,
  ]);
  const listedSpec =
    filteredNodes.find((spec) => nodeKey(spec) === selectedNodeKey) ??
    filteredNodes[0] ??
    null;
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
    if (!listedSpec) return null;
    if (listedSpec.plugin_slug !== MODULE_PLUGIN_SLUG) return listedSpec;
    const moduleKey = listedSpec.module_id ?? listedSpec.module_graph_id;
    const selectedReleaseKey =
      moduleKey && selectedRelease?.moduleKey === moduleKey
        ? selectedRelease.releaseKey
        : null;
    return (
      moduleReleases.find((spec) => nodeKey(spec) === selectedReleaseKey) ??
      moduleReleases.find((spec) => spec.catalog_visible !== false) ??
      moduleReleases[0] ??
      listedSpec
    );
  }, [listedSpec, moduleReleases, selectedRelease]);
  const selectedSpecKey = selectedSpec ? nodeKey(selectedSpec) : null;
  const selectedFields = selectedSpec
    ? schemaFields(selectedSpec.config_schema)
    : [];
  const compatibilityPorts = selectedSpec
    ? [...selectedSpec.inputs, ...selectedSpec.outputs]
    : [];
  const compatibilityPortKey =
    compatibilityPortSelection?.specKey === selectedSpecKey
      ? compatibilityPortSelection.portKey
      : null;
  const activeCompatibilityPort =
    compatibilityPorts.find((port) => portKey(port) === compatibilityPortKey) ??
    compatibilityPorts[0] ??
    null;
  const portMatches = React.useMemo(
    () =>
      selectedSpec && activeCompatibilityPort
        ? compatibleNodesForPort(
            selectedSpec,
            activeCompatibilityPort,
            catalogRegistry,
          )
        : [],
    [activeCompatibilityPort, catalogRegistry, selectedSpec],
  );
  const selectedPlugin = selectedSpec
    ? pluginFor(registry, selectedSpec.plugin_slug)
    : null;
  const selectedPrimaryInput = selectedSpec?.inputs[0] ?? null;
  const selectedPrimaryOutput = selectedSpec?.outputs[0] ?? null;
  const selectedPrimaryInputArtifact = selectedPrimaryInput
    ? portArtifactType(selectedPrimaryInput)
    : null;
  const selectedPrimaryOutputArtifact = selectedPrimaryOutput
    ? portArtifactType(selectedPrimaryOutput)
    : null;
  const resultsTitle =
    activeSourceFilter.id === "all"
      ? "All nodes"
      : activeSourceFilter.id === "workspace-library"
        ? "Workspace library"
        : `${activeSourceFilter.title} nodes`;
  const isModuleSelection = selectedPlugin?.entry_kind === "module";
  const isDeprecatedModule = selectedSpec?.publication_state === "deprecated";
  const selectionCanInsert = canInsert && selectedSpec?.runnable !== false;
  const pluginUnavailableReason =
    selectedSpec?.non_runnable_detail ??
    "This Plugin release is catalog-only until its isolated runtime is available.";
  const selectionDisabledReason = !canInsert
    ? insertDisabledReason
    : pluginUnavailableReason;
  const activeResultId = listedSpec
    ? `node-selector-result-${nodeKey(listedSpec)}`
    : undefined;
  const compatibilityPortTitle = compatibility
    ? (compatibility.port.title ?? compatibility.port.name)
    : null;
  const resultStatus = loading
    ? "Loading nodes…"
    : errorMessage
      ? "Nodes could not be loaded."
      : filteredNodes.length === 0
        ? "No nodes found."
        : `${filteredNodes.length} ${filteredNodes.length === 1 ? "node" : "nodes"}.`;

  const selectSource = (id: string) => {
    setActiveSourceId(id);
    setSelectedNodeKey(null);
    setTechnicalDetailsOpen(false);
    setCompatibilityPortSelection(null);
  };

  const focusSourceAt = (index: number) => {
    const boundedIndex = Math.max(0, Math.min(index, sourceFilters.length - 1));
    const nextFilter = sourceFilters[boundedIndex];
    if (!nextFilter) return;
    selectSource(nextFilter.id);
    filterRefs.current.get(nextFilter.id)?.focus();
  };

  const focusResultAt = (index: number) => {
    if (!filteredNodes.length) return;
    const boundedIndex = Math.max(0, Math.min(index, filteredNodes.length - 1));
    const nextSpec = filteredNodes[boundedIndex];
    if (!nextSpec) return;
    const key = nodeKey(nextSpec);
    setSelectedNodeKey(key);
    resultRefs.current.get(key)?.focus();
  };

  const insertNode = (spec: NodeSpec) => {
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
  };

  const inspectCatalogNode = (spec: NodeSpec) => {
    const key = nodeKey(spec);
    pendingResultFocusKey.current = key;
    setQuery("");
    setActiveSourceId(
      spec.plugin_slug === MODULE_PLUGIN_SLUG
        ? "workspace-library"
        : sourceFilterId(spec.plugin_slug),
    );
    setArtifactFilterId(null);
    setInputNodesOnly(false);
    setSelectedNodeKey(key);
    setSelectedRelease(null);
    setTechnicalDetailsOpen(false);
    setCompatibilityPortSelection(null);
  };

  React.useEffect(() => {
    if (mobileNodeSelector && detailsOpen) {
      pendingResultFocusKey.current = null;
      backRef.current?.focus();
      return;
    }
    const key = pendingResultFocusKey.current;
    if (!key) return;
    pendingResultFocusKey.current = null;
    const option = resultRefs.current.get(key);
    option?.scrollIntoView?.({ block: "nearest" });
    option?.focus();
  }, [
    activeSourceId,
    artifactFilterId,
    inputNodesOnly,
    query,
    selectedNodeKey,
    mobileNodeSelector,
    detailsOpen,
  ]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        ref={dialogRef}
        size="catalog"
        aria-labelledby="node-selector-title"
        aria-describedby="node-selector-description"
        initialFocus={finePointer ? searchRef : dialogRef}
        finalFocus={providedReturnFocusRef}
      >
        <div {...stylex.props(s.header)}>
          <div {...stylex.props(s.heading)}>
            <div {...stylex.props(s.titleRow)}>
              <DialogTitle id="node-selector-title" {...stylex.props(s.title)}>
                Add node
              </DialogTitle>
            </div>
            <DialogDescription
              id="node-selector-description"
              {...stylex.props(s.visuallyHidden)}
            >
              Choose what to add to your workflow.
            </DialogDescription>
          </div>
          <div
            {...stylex.props(
              s.searchWrap,
              mobileNodeSelector && detailsOpen && s.hidden,
            )}
          >
            <Search size={14} {...stylex.props(s.searchIcon)} />
            <input
              ref={searchRef}
              aria-label="Search nodes"
              aria-autocomplete="list"
              aria-controls="node-selector-results"
              aria-activedescendant={activeResultId}
              value={query}
              placeholder="Search nodes…"
              {...stylex.props(s.search)}
              onChange={(event) => {
                setQuery(event.currentTarget.value);
                setSelectedNodeKey(null);
              }}
              onKeyDown={(event) => {
                if (event.key === "ArrowDown") {
                  event.preventDefault();
                  focusResultAt(0);
                } else if (event.key === "Enter") {
                  event.preventDefault();
                  if (selectedSpec) insertNode(selectedSpec);
                }
              }}
            />
          </div>
        </div>

        <div
          {...stylex.props(
            s.layout,
            mobileNodeSelector && detailsOpen && s.detailLayout,
          )}
        >
          <nav
            aria-label="Node filters"
            {...stylex.props(
              s.filterPane,
              mobileNodeSelector && detailsOpen && s.hidden,
            )}
          >
            <div {...stylex.props(s.compactFilters)}>
              <select
                aria-label="Node source"
                value={activeSourceId}
                {...stylex.props(s.refinementSelect)}
                onChange={(event) => selectSource(event.currentTarget.value)}
              >
                {sourceFilters.map((filter) => (
                  <option key={filter.id} value={filter.id}>
                    {filter.id === "all" ? "All sources" : filter.title}
                  </option>
                ))}
              </select>
              <button
                type="button"
                aria-expanded={filtersOpen}
                aria-controls="node-selector-refinements"
                {...stylex.props(s.filterButton)}
                onClick={() => setFiltersOpen((open) => !open)}
              >
                <Settings2 size={14} aria-hidden="true" />
                Filters
                {artifactFilterId || inputNodesOnly
                  ? ` (${Number(!!artifactFilterId) + Number(inputNodesOnly)})`
                  : ""}
              </button>
            </div>
            <div {...stylex.props(s.sourceRail)}>
              <h3 {...stylex.props(s.filterHeading)}>Source</h3>
              <div
                role="toolbar"
                aria-label="Node sources"
                aria-orientation={
                  mobileNodeSelector ? "horizontal" : "vertical"
                }
                {...stylex.props(s.categoryToolbar)}
              >
                {sourceFilters.map((filter, index) => {
                  const active = filter.id === activeSourceId;
                  const count = filterAndSearchCatalogNodes(
                    compatibleCatalogNodes,
                    [filter, ...refinementFilters],
                    "",
                    registry,
                  ).length;
                  const filterButton = (
                    <button
                      ref={(element) => {
                        if (element) filterRefs.current.set(filter.id, element);
                        else filterRefs.current.delete(filter.id);
                      }}
                      type="button"
                      tabIndex={active ? 0 : -1}
                      aria-label={`${filter.title}, ${count} ${count === 1 ? "node" : "nodes"}`}
                      aria-pressed={active}
                      {...stylex.props(
                        s.categoryButton,
                        active ? s.categoryButtonActive : null,
                      )}
                      onClick={() => selectSource(filter.id)}
                      onKeyDown={(event) => {
                        if (
                          event.key === "ArrowDown" ||
                          event.key === "ArrowRight"
                        ) {
                          event.preventDefault();
                          focusSourceAt(index + 1);
                        } else if (
                          event.key === "ArrowUp" ||
                          event.key === "ArrowLeft"
                        ) {
                          event.preventDefault();
                          focusSourceAt(index - 1);
                        } else if (event.key === "Home") {
                          event.preventDefault();
                          focusSourceAt(0);
                        } else if (event.key === "End") {
                          event.preventDefault();
                          focusSourceAt(sourceFilters.length - 1);
                        }
                      }}
                    >
                      <SourceFilterIcon filter={filter} />
                      {filter.title}
                    </button>
                  );
                  return filter.id === "workspace-library" ? (
                    <div key={filter.id} {...stylex.props(s.filterLibrary)}>
                      {filterButton}
                    </div>
                  ) : (
                    <React.Fragment key={filter.id}>
                      {filterButton}
                    </React.Fragment>
                  );
                })}
              </div>
            </div>
            <div
              id="node-selector-refinements"
              {...stylex.props(
                s.refinementSection,
                !filtersOpen && s.refinementsCollapsed,
              )}
            >
              <label {...stylex.props(s.refinementField)}>
                <span>Artifact</span>
                <select
                  aria-label="Artifact type"
                  value={artifactFilterId ?? ""}
                  {...stylex.props(s.refinementSelect)}
                  onChange={(event) => {
                    setArtifactFilterId(event.currentTarget.value || null);
                    setSelectedNodeKey(null);
                  }}
                >
                  <option value="">Any artifact</option>
                  {artifactOptions.map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.title}
                    </option>
                  ))}
                </select>
              </label>
              <label {...stylex.props(s.refinementCheck)}>
                <input
                  type="checkbox"
                  checked={inputNodesOnly}
                  onChange={(event) => {
                    setInputNodesOnly(event.currentTarget.checked);
                    setSelectedNodeKey(null);
                  }}
                />
                Input nodes only
              </label>
            </div>
          </nav>

          <section
            aria-labelledby="node-selector-results-heading"
            {...stylex.props(
              s.nodePane,
              mobileNodeSelector && detailsOpen && s.hidden,
            )}
          >
            <header {...stylex.props(s.nodePaneHeader)}>
              <div {...stylex.props(s.resultHeading)}>
                <h3
                  id="node-selector-results-heading"
                  {...stylex.props(s.nodePaneTitle)}
                >
                  {resultsTitle}
                </h3>
                <span
                  role={errorMessage ? "alert" : "status"}
                  aria-live={errorMessage ? "assertive" : "polite"}
                  aria-atomic="true"
                  {...stylex.props(s.resultCount)}
                >
                  {resultStatus}
                </span>
              </div>
            </header>
            {compatibility && compatibilityPortTitle ? (
              <div
                id="node-selector-compatibility"
                {...stylex.props(s.compatibilityBanner)}
              >
                <Cable size={12} aria-hidden="true" />
                Showing nodes that can connect{" "}
                {compatibility.direction === "upstream" ? "to" : "from"}{" "}
                <strong>{compatibilityPortTitle}</strong>.
              </div>
            ) : null}
            <div
              id="node-selector-results"
              role="listbox"
              aria-label="Node results"
              aria-busy={loading}
              aria-activedescendant={activeResultId}
              {...stylex.props(s.nodeList)}
            >
              {errorMessage ? (
                <div {...stylex.props(s.empty)}>
                  <span>Nodes couldn’t be loaded. {errorMessage}</span>
                  {onRetry ? (
                    <button
                      type="button"
                      {...stylex.props(s.resetButton)}
                      onClick={onRetry}
                    >
                      Try again
                    </button>
                  ) : null}
                </div>
              ) : loading ? (
                <div {...stylex.props(s.empty)}>Loading nodes…</div>
              ) : filteredNodes.length ? (
                filteredNodes.map((spec, index) => {
                  const key = nodeKey(spec);
                  const active = listedSpec
                    ? key === nodeKey(listedSpec)
                    : false;
                  const representativePort = spec.outputs[0] ?? spec.inputs[0];
                  const representativeArtifact = representativePort
                    ? portArtifactType(representativePort)
                    : null;
                  return (
                    <button
                      key={key}
                      id={`node-selector-result-${key}`}
                      ref={(element) => {
                        if (element) resultRefs.current.set(key, element);
                        else resultRefs.current.delete(key);
                      }}
                      type="button"
                      role="option"
                      tabIndex={active ? 0 : -1}
                      aria-selected={active}
                      {...stylex.props(
                        s.nodeRow,
                        active ? s.nodeRowActive : null,
                      )}
                      style={
                        active && representativeArtifact
                          ? {
                              borderColor: artifactTypeColor(
                                representativeArtifact.id,
                                tokens.colorAccent,
                              ),
                            }
                          : undefined
                      }
                      onClick={() => {
                        setSelectedNodeKey(key);
                        setTechnicalDetailsOpen(false);
                        setDetailsOpen(true);
                      }}
                      onFocus={() => setSelectedNodeKey(key)}
                      onKeyDown={(event) => {
                        if (event.key === "ArrowDown") {
                          event.preventDefault();
                          focusResultAt(index + 1);
                        } else if (event.key === "ArrowUp") {
                          event.preventDefault();
                          focusResultAt(index - 1);
                        } else if (event.key === "Home") {
                          event.preventDefault();
                          focusResultAt(0);
                        } else if (event.key === "End") {
                          event.preventDefault();
                          focusResultAt(filteredNodes.length - 1);
                        } else if (event.key === "Enter") {
                          event.preventDefault();
                          if (selectedSpec) insertNode(selectedSpec);
                        }
                      }}
                    >
                      <span {...stylex.props(s.nodeCopy)}>
                        <span {...stylex.props(s.nodeTitleRow)}>
                          <span {...stylex.props(s.nodeTitle)}>
                            {spec.title}
                          </span>
                        </span>
                        <span {...stylex.props(s.nodeDescription)}>
                          {spec.description || "No description is available."}
                        </span>
                      </span>
                    </button>
                  );
                })
              ) : (
                <div {...stylex.props(s.empty)}>
                  <span>
                    {compatibility
                      ? "No nodes match this port and the current search or filter."
                      : showingModules
                        ? "No published Modules match the current search."
                        : "No nodes match the current search or filter."}
                  </span>
                  {normalizedQuery ||
                  activeSourceId !== "all" ||
                  artifactFilterId !== null ||
                  inputNodesOnly ? (
                    <button
                      type="button"
                      {...stylex.props(s.resetButton)}
                      onClick={() => {
                        setQuery("");
                        setActiveSourceId("all");
                        setArtifactFilterId(null);
                        setInputNodesOnly(false);
                        setSelectedNodeKey(null);
                      }}
                    >
                      Reset search and filter
                    </button>
                  ) : null}
                </div>
              )}
            </div>
            {showingModules && !loading && !errorMessage ? (
              <div
                aria-label="Workspace library notes"
                {...stylex.props(s.moduleDiagnostics)}
              >
                {activeEditingModule ? (
                  <p {...stylex.props(s.moduleDiagnosticsNote)}>
                    “{activeEditingModule.title}” is hidden here because it is
                    the graph currently being edited.
                  </p>
                ) : null}
                {filteredNodes.length === 0 && !normalizedQuery ? (
                  <p {...stylex.props(s.moduleDiagnosticsNote)}>
                    {compatibility
                      ? "No published Modules in this workspace can connect to this port."
                      : "No published Modules in this workspace yet. Open a source graph, declare Module Input/Output boundaries, then Publish release."}
                    {onOpenWorkspaceLibrary ? (
                      <>
                        {" "}
                        <button
                          type="button"
                          {...stylex.props(s.resetButton)}
                          onClick={onOpenWorkspaceLibrary}
                        >
                          Open workspace library
                        </button>
                      </>
                    ) : null}
                  </p>
                ) : null}
              </div>
            ) : null}
          </section>

          <aside
            aria-label="Node information"
            aria-labelledby={
              selectedSpec ? "node-selector-inspector-title" : undefined
            }
            {...stylex.props(
              s.inspector,
              mobileNodeSelector && !detailsOpen && s.hidden,
            )}
          >
            {mobileNodeSelector && detailsOpen ? (
              <button
                ref={backRef}
                type="button"
                {...stylex.props(s.backButton)}
                onClick={() => {
                  pendingResultFocusKey.current = listedSpec
                    ? nodeKey(listedSpec)
                    : null;
                  setDetailsOpen(false);
                }}
              >
                <ArrowLeft size={16} aria-hidden="true" /> Back to results
              </button>
            ) : null}
            {selectedSpec && selectedPlugin ? (
              <>
                <div
                  key={nodeKey(selectedSpec)}
                  {...stylex.props(s.inspectorBody)}
                  className={[
                    stylex.props(s.inspectorBody).className,
                    "grafy-node-detail",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                >
                  <div
                    {...stylex.props(s.previewStage)}
                    className={[
                      stylex.props(s.previewStage).className,
                      "grafy-node-preview-stage",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                  >
                    <CatalogNodePreview
                      spec={selectedSpec}
                      registry={registry}
                      fields={selectedFields}
                      selectedPortKey={
                        activeCompatibilityPort
                          ? portKey(activeCompatibilityPort)
                          : null
                      }
                      onSelectPort={(port) => {
                        if (!selectedSpecKey) return;
                        setCompatibilityPortSelection({
                          specKey: selectedSpecKey,
                          portKey: portKey(port),
                        });
                      }}
                    />
                  </div>
                  <div {...stylex.props(s.inspectorScroll)}>
                    {isModuleSelection ? (
                      <header {...stylex.props(s.inspectorHeader)}>
                        <div {...stylex.props(s.inspectorProvenance)}>
                          <div {...stylex.props(s.eyebrow)}>
                            Module · release{" "}
                            {selectedSpec.module_graph_revision}
                          </div>
                          <span {...stylex.props(s.originBadge)}>
                            {selectedSpec.publication_state ?? "published"}
                          </span>
                        </div>
                        <h3
                          id="node-selector-inspector-title"
                          {...stylex.props(s.inspectorTitle)}
                        >
                          {selectedSpec.title}
                        </h3>
                        <div {...stylex.props(s.operatorId)}>
                          Module contract · release{" "}
                          {selectedSpec.module_graph_revision}
                        </div>
                        {moduleReleases.length > 1 ? (
                          <label {...stylex.props(s.operatorId)}>
                            Release{" "}
                            <select
                              aria-label="Module release"
                              value={nodeKey(selectedSpec)}
                              onChange={(event) => {
                                const moduleKey =
                                  listedSpec.module_id ??
                                  listedSpec.module_graph_id;
                                if (!moduleKey) return;
                                setSelectedRelease({
                                  moduleKey,
                                  releaseKey: event.currentTarget.value,
                                });
                              }}
                            >
                              {moduleReleases.map((release) => (
                                <option
                                  key={nodeKey(release)}
                                  value={nodeKey(release)}
                                >
                                  Release {release.module_graph_revision}
                                  {release.is_current_library_release
                                    ? " (current)"
                                    : ""}
                                </option>
                              ))}
                            </select>
                          </label>
                        ) : null}
                        {isDeprecatedModule ? (
                          <p {...stylex.props(s.moduleDiagnosticsNote)}>
                            This Module is deprecated. New inserts are
                            discouraged; existing pins keep working.
                          </p>
                        ) : null}
                        {selectedSpec.module_graph_id && onOpenGraph ? (
                          <button
                            type="button"
                            title="Open the saved graph that defines this module"
                            {...stylex.props(
                              s.openGraphButton,
                              s.inspectorOpenGraph,
                            )}
                            onClick={() =>
                              onOpenGraph(selectedSpec.module_graph_id!)
                            }
                          >
                            <ExternalLink size={10} />
                            Open source graph
                          </button>
                        ) : null}
                        <p {...stylex.props(s.inspectorDescription)}>
                          {selectedSpec.description ||
                            "No description is available for this node."}
                        </p>
                        {selectedSpec.runnable === false ? (
                          <p {...stylex.props(s.moduleDiagnosticsNote)}>
                            Catalog preview only. {pluginUnavailableReason}
                          </p>
                        ) : null}
                      </header>
                    ) : (
                      <header {...stylex.props(s.inspectorHeader)}>
                        <h3
                          id="node-selector-inspector-title"
                          {...stylex.props(s.inspectorTitle)}
                        >
                          {selectedSpec.title}
                        </h3>
                        <p {...stylex.props(s.inspectorDescription)}>
                          {selectedSpec.description ||
                            "No description is available for this node."}
                        </p>
                        {selectedSpec.runnable === false ? (
                          <p {...stylex.props(s.moduleDiagnosticsNote)}>
                            Catalog preview only. {pluginUnavailableReason}
                          </p>
                        ) : null}
                        <div {...stylex.props(s.inspectorSummary)}>
                          <p {...stylex.props(s.inspectorStatement)}>
                            {selectedPrimaryInput ? (
                              <>
                                Accepts{" "}
                                <span
                                  {...stylex.props(s.inspectorStatementStrong)}
                                  style={{
                                    color: selectedPrimaryInputArtifact
                                      ? artifactTypeColor(
                                          selectedPrimaryInputArtifact.id,
                                          tokens.colorTextEmphasis,
                                        )
                                      : tokens.colorTextEmphasis,
                                  }}
                                >
                                  {artifactTitleFor(
                                    registry,
                                    selectedPrimaryInput,
                                  )}
                                </span>
                                {selectedSpec.inputs.length > 1
                                  ? ` + ${selectedSpec.inputs.length - 1} more`
                                  : ` · ${selectedPrimaryInput.shape === "many" ? "sequence" : "single value"}`}
                              </>
                            ) : (
                              "Starts a workflow"
                            )}
                          </p>
                          <p {...stylex.props(s.inspectorStatement)}>
                            {selectedPrimaryOutput ? (
                              <>
                                Produces{" "}
                                <span
                                  {...stylex.props(s.inspectorStatementStrong)}
                                  style={{
                                    color: selectedPrimaryOutputArtifact
                                      ? artifactTypeColor(
                                          selectedPrimaryOutputArtifact.id,
                                          tokens.colorTextEmphasis,
                                        )
                                      : tokens.colorTextEmphasis,
                                  }}
                                >
                                  {artifactTitleFor(
                                    registry,
                                    selectedPrimaryOutput,
                                  )}
                                </span>
                                {selectedSpec.outputs.length > 1
                                  ? ` + ${selectedSpec.outputs.length - 1} more`
                                  : ` · ${selectedPrimaryOutput.shape === "many" ? "sequence" : "single value"}`}
                              </>
                            ) : (
                              "Ends a workflow branch"
                            )}
                          </p>
                          <div {...stylex.props(s.inspectorConfiguration)}>
                            <span
                              {...stylex.props(s.inspectorConfigurationLabel)}
                            >
                              Configuration:
                            </span>
                            <span>
                              {selectedFields.length
                                ? `${selectedFields.map((field) => field.title).join(", ")} ${selectedFields.length === 1 ? "is" : "are"} editable after adding.`
                                : "No editable settings."}
                            </span>
                          </div>
                          <button
                            type="button"
                            aria-expanded={technicalDetailsOpen}
                            {...stylex.props(s.technicalToggle)}
                            onClick={() =>
                              setTechnicalDetailsOpen((open) => !open)
                            }
                          >
                            {technicalDetailsOpen
                              ? "Hide technical details"
                              : "View technical details"}
                          </button>
                        </div>
                      </header>
                    )}

                    {isModuleSelection || technicalDetailsOpen ? (
                      <>
                        <section {...stylex.props(s.section)}>
                          <div {...stylex.props(s.sectionTitleRow)}>
                            <Workflow
                              size={13}
                              {...stylex.props(s.sectionIcon)}
                            />
                            <h3 {...stylex.props(s.sectionTitle)}>
                              {isModuleSelection ? "Module contract" : "Ports"}
                            </h3>
                          </div>
                          {!isModuleSelection ? (
                            <p {...stylex.props(s.moduleDiagnosticsNote)}>
                              {selectedSpec.operator_id}@
                              {selectedSpec.operator_version}
                            </p>
                          ) : null}
                          <div {...stylex.props(s.portGrid)}>
                            <PortList
                              direction="input"
                              ports={selectedSpec.inputs}
                              registry={registry}
                            />
                            <PortList
                              direction="output"
                              ports={selectedSpec.outputs}
                              registry={registry}
                            />
                          </div>
                        </section>

                        <section {...stylex.props(s.section)}>
                          <div {...stylex.props(s.sectionTitleRow)}>
                            <Settings2
                              size={13}
                              {...stylex.props(s.sectionIcon)}
                            />
                            <h3 {...stylex.props(s.sectionTitle)}>
                              Configuration
                            </h3>
                          </div>
                          {selectedFields.length ? (
                            <div {...stylex.props(s.fieldList)}>
                              {selectedFields.map((field) => (
                                <div
                                  key={field.name}
                                  {...stylex.props(s.fieldRow)}
                                >
                                  <div {...stylex.props(s.fieldIdentity)}>
                                    <div {...stylex.props(s.fieldTitle)}>
                                      {field.title}
                                    </div>
                                    <div {...stylex.props(s.fieldName)}>
                                      {field.name}
                                    </div>
                                  </div>
                                  <div {...stylex.props(s.fieldDetails)}>
                                    <div {...stylex.props(s.fieldMeta)}>
                                      {fieldTypeLabel(field)} ·{" "}
                                      {fieldConstraintLabel(field)}
                                    </div>
                                    {field.description ? (
                                      <p {...stylex.props(s.fieldDescription)}>
                                        {field.description}
                                      </p>
                                    ) : null}
                                    {field.enumValues?.length ? (
                                      <p {...stylex.props(s.fieldChoices)}>
                                        Choices:{" "}
                                        {field.enumValues
                                          .map(String)
                                          .join(", ")}
                                      </p>
                                    ) : null}
                                    {field.pattern ? (
                                      <p {...stylex.props(s.fieldChoices)}>
                                        Pattern: {field.pattern}
                                      </p>
                                    ) : null}
                                  </div>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <p {...stylex.props(s.compatibilityEmpty)}>
                              No editable scalar settings are declared. Upload
                              or custom controls, when available, appear on the
                              node after it is added.
                            </p>
                          )}
                        </section>
                      </>
                    ) : null}

                    {activeCompatibilityPort ? (
                      <WorksWithSection
                        ports={compatibilityPorts}
                        activePort={activeCompatibilityPort}
                        matches={portMatches}
                        registry={registry}
                        onSelectPort={(port) => {
                          if (!selectedSpecKey) return;
                          setCompatibilityPortSelection({
                            specKey: selectedSpecKey,
                            portKey: portKey(port),
                          });
                        }}
                        onInspect={inspectCatalogNode}
                      />
                    ) : null}
                  </div>
                </div>

                <footer {...stylex.props(s.inspectorFooter)}>
                  {!selectionCanInsert ? (
                    <span
                      id="node-selector-insert-disabled-reason"
                      {...stylex.props(s.visuallyHidden)}
                    >
                      {selectionDisabledReason}
                    </span>
                  ) : null}
                  <button
                    type="button"
                    disabled={!selectionCanInsert}
                    aria-describedby={
                      !selectionCanInsert
                        ? "node-selector-insert-disabled-reason"
                        : undefined
                    }
                    title={
                      !selectionCanInsert
                        ? selectionDisabledReason
                        : isModuleSelection
                          ? `Insert module call for ${selectedSpec.title}`
                          : `Add ${selectedSpec.title} to the workflow`
                    }
                    {...stylex.props(
                      s.addButton,
                      !selectionCanInsert ? s.addButtonDisabled : null,
                    )}
                    onClick={() => insertNode(selectedSpec)}
                  >
                    <Plus size={14} />{" "}
                    {isModuleSelection
                      ? "Insert module call"
                      : `Add ${selectedSpec.title}`}
                  </button>
                </footer>
              </>
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
      </DialogContent>
    </Dialog>
  );
}
