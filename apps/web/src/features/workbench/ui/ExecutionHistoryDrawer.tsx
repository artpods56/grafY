"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import useSWR from "swr";
import useSWRInfinite from "swr/infinite";
import {
  ChevronRight,
  CircleAlert,
  History,
  LoaderCircle,
  RefreshCw,
  X,
} from "lucide-react";

import { useNodeRegistry } from "@/hooks/use-api";
import {
  getGraphExecution,
  listGraphExecutions,
  type GraphExecutionDetail,
  type GraphExecutionList,
  type GraphExecutionStatus,
  type GraphExecutionSummary,
} from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { ArtifactPortPreview } from "../canvas/nodes/ArtifactsAppendix";

const PAGE_SIZE = 20;
const MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";

const s = stylex.create({
  drawer: {
    position: "absolute",
    zIndex: 35,
    top: {
      default: "66px",
      "@media (max-width: 720px)": "12px",
      "@media (max-width: 620px)":
        "calc(var(--grafy-mobile-overlay-top, 68px) + env(safe-area-inset-top, 0px))",
    },
    right: {
      default: "13px",
      "@media (max-width: 720px)":
        "calc(12px + env(safe-area-inset-right, 0px))",
    },
    bottom: {
      default: "12px",
      "@media (max-width: 720px)":
        "calc(12px + env(safe-area-inset-bottom, 0px))",
    },
    left: {
      default: "auto",
      "@media (max-width: 720px)":
        "calc(12px + env(safe-area-inset-left, 0px))",
    },
    width: {
      default: "min(880px, calc(100% - 26px))",
      "@media (max-width: 720px)": "auto",
    },
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorderStrong,
    borderRadius: "12px",
    backgroundColor: tokens.colorSurface,
    boxShadow: tokens.shadowNodeSelected,
    color: tokens.colorText,
  },
  header: {
    minHeight: "52px",
    display: "flex",
    alignItems: "center",
    gap: "9px",
    padding: "8px 9px 8px 14px",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorBorder,
  },
  headerIcon: {
    width: "28px",
    height: "28px",
    display: "grid",
    placeItems: "center",
    flexShrink: 0,
    borderRadius: "8px",
    backgroundColor: tokens.colorAccentSoft,
    color: tokens.colorAccent,
  },
  headerCopy: { minWidth: 0, flex: 1, display: "grid", gap: "1px" },
  title: {
    overflow: "hidden",
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeMd,
    fontWeight: 760,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  subtitle: {
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  headerButton: {
    width: {
      default: "30px",
      "@media (max-width: 720px)": "44px",
    },
    height: {
      default: "30px",
      "@media (max-width: 720px)": "44px",
    },
    display: "grid",
    placeItems: "center",
    flexShrink: 0,
    borderWidth: 0,
    borderRadius: "7px",
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorHover,
      ":disabled": "transparent",
    },
    color: {
      default: tokens.colorMuted,
      ":disabled": tokens.colorTextDisabled,
    },
    cursor: { default: "pointer", ":disabled": "not-allowed" },
  },
  dirtyWarning: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    padding: "8px 14px",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorBorder,
    backgroundColor:
      "light-dark(rgba(201, 146, 15, 0.09), rgba(251, 191, 36, 0.1))",
    color: tokens.colorWarning,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
  content: {
    minHeight: 0,
    flex: 1,
    display: "grid",
    gridTemplateColumns: {
      default: "300px minmax(0, 1fr)",
      "@media (max-width: 720px)": "1fr",
    },
    gridTemplateRows: {
      default: "minmax(0, 1fr)",
      "@media (max-width: 720px)": "minmax(180px, 0.8fr) minmax(0, 1.2fr)",
    },
  },
  listPane: {
    minHeight: 0,
    display: "flex",
    flexDirection: "column",
    borderRightWidth: {
      default: 1,
      "@media (max-width: 720px)": 0,
    },
    borderRightStyle: "solid",
    borderRightColor: tokens.colorBorder,
  },
  list: { minHeight: 0, flex: 1, overflowY: "auto", padding: "5px" },
  listItem: {
    width: "100%",
    minHeight: "82px",
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) 16px",
    alignItems: "center",
    gap: "7px",
    padding: "9px 8px 9px 10px",
    borderWidth: 0,
    borderRadius: "8px",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: tokens.colorText,
    cursor: "pointer",
    textAlign: "left",
  },
  listItemSelected: {
    backgroundColor: {
      default: tokens.colorAccentSoft,
      ":hover": tokens.colorAccentSoft,
    },
  },
  listCopy: { minWidth: 0, display: "grid", gap: "5px" },
  listTop: { display: "flex", alignItems: "center", gap: "6px" },
  timestamp: {
    minWidth: 0,
    flex: 1,
    overflow: "hidden",
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeSm,
    fontWeight: 690,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  status: {
    flexShrink: 0,
    padding: "2px 6px",
    borderRadius: "9999px",
    backgroundColor: tokens.colorSurfaceMuted,
    color: tokens.colorMuted,
    fontSize: "9px",
    fontWeight: 780,
    letterSpacing: "0.03em",
    textTransform: "uppercase",
  },
  statusSuccess: {
    backgroundColor:
      "light-dark(rgba(42, 157, 124, 0.11), rgba(67, 197, 158, 0.14))",
    color: tokens.colorSuccess,
  },
  statusFailure: {
    backgroundColor: tokens.colorDangerHover,
    color: tokens.colorDanger,
  },
  statusActive: {
    backgroundColor: tokens.colorAccentSoft,
    color: tokens.colorAccent,
  },
  statusCancelled: {
    backgroundColor:
      "light-dark(rgba(201, 146, 15, 0.12), rgba(251, 191, 36, 0.15))",
    color: tokens.colorWarning,
  },
  meta: {
    color: tokens.colorSubtle,
    fontSize: "10px",
    lineHeight: 1.35,
  },
  id: {
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontFamily: MONO,
    fontSize: "9px",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  loadMoreWrap: {
    padding: "7px",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorBorder,
  },
  loadMore: {
    width: "100%",
    height: {
      default: "31px",
      "@media (max-width: 720px)": "44px",
    },
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "6px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "7px",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: tokens.colorMuted,
    cursor: "pointer",
    fontSize: tokens.fontSizeXs,
    fontWeight: 700,
  },
  detailPane: {
    minHeight: 0,
    overflowY: "auto",
    padding: {
      default: "14px",
      "@media (max-width: 720px)": "12px",
    },
    borderTopWidth: {
      default: 0,
      "@media (max-width: 720px)": 1,
    },
    borderTopStyle: "solid",
    borderTopColor: tokens.colorBorder,
  },
  detailHeader: {
    display: "grid",
    gap: "7px",
    marginBottom: "14px",
    paddingBottom: "12px",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
  },
  detailHeading: {
    display: "flex",
    alignItems: "center",
    flexWrap: "wrap",
    gap: "7px",
  },
  detailTitle: { fontSize: "15px", fontWeight: 760 },
  detailMeta: {
    display: "flex",
    alignItems: "center",
    flexWrap: "wrap",
    gap: "5px 10px",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
  },
  nodeList: { display: "grid", gap: "12px" },
  nodeResult: {
    display: "grid",
    gap: "10px",
    padding: "11px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "10px",
    backgroundColor: tokens.colorSurfaceRaised,
  },
  nodeHead: { display: "flex", alignItems: "center", gap: "7px" },
  nodePosition: {
    width: "22px",
    height: "22px",
    display: "grid",
    placeItems: "center",
    flexShrink: 0,
    borderRadius: "6px",
    backgroundColor: tokens.colorSurfaceMuted,
    color: tokens.colorSubtle,
    fontFamily: MONO,
    fontSize: "9px",
  },
  nodeCopy: { minWidth: 0, flex: 1, display: "grid", gap: "1px" },
  nodeTitle: {
    overflow: "hidden",
    fontSize: tokens.fontSizeSm,
    fontWeight: 720,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  nodeId: {
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontFamily: MONO,
    fontSize: "9px",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  nodeError: {
    margin: 0,
    padding: "7px 8px",
    borderRadius: "6px",
    backgroundColor: tokens.colorDangerHover,
    color: tokens.colorDanger,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
    whiteSpace: "pre-wrap",
  },
  outputList: { display: "grid", gap: "12px" },
  unavailableOutput: {
    display: "grid",
    gap: "5px",
    padding: "9px 10px",
    borderRadius: "8px",
    backgroundColor: tokens.colorSurfaceMuted,
  },
  unavailablePort: {
    color: tokens.colorMuted,
    fontFamily: MONO,
    fontSize: "10px",
    fontWeight: 750,
  },
  message: {
    minHeight: "150px",
    display: "grid",
    placeItems: "center",
    alignContent: "center",
    gap: "8px",
    padding: "28px 18px",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.5,
    textAlign: "center",
  },
  messageError: { color: tokens.colorDanger },
  retry: {
    height: "29px",
    paddingInline: "10px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorderStrong,
    borderRadius: "7px",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: tokens.colorMuted,
    cursor: "pointer",
    fontSize: tokens.fontSizeXs,
    fontWeight: 700,
  },
  spinner: {
    animationName: "grafy-spin",
    animationDuration: "900ms",
    animationIterationCount: "infinite",
    animationTimingFunction: "linear",
  },
});

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function executionTimestamp(execution: GraphExecutionSummary): string {
  const value =
    execution.finished_at ?? execution.started_at ?? execution.created_at;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function statusStyle(status: GraphExecutionStatus) {
  if (status === "succeeded") return s.statusSuccess;
  if (status === "failed") return s.statusFailure;
  if (status === "cancelled" || status === "cancelling") {
    return s.statusCancelled;
  }
  return s.statusActive;
}

type ExecutionHistoryPageKey = readonly [
  "graph-execution-history",
  string,
  string,
  string | null,
  string | null,
];

async function loadExecutionHistoryPage([
  ,
  workspaceId,
  graphId,
  nodeId,
  cursor,
]: ExecutionHistoryPageKey): Promise<GraphExecutionList> {
  return listGraphExecutions(workspaceId, graphId, {
    limit: PAGE_SIZE,
    cursor: cursor ?? undefined,
    nodeId: nodeId ?? undefined,
  });
}

type ExecutionDetailKey = readonly [
  "graph-execution-detail",
  string,
  string,
  string,
];

async function loadExecutionDetail([
  ,
  workspaceId,
  graphId,
  executionId,
]: ExecutionDetailKey): Promise<GraphExecutionDetail> {
  return getGraphExecution(workspaceId, graphId, executionId);
}

export interface ExecutionHistoryDrawerProps {
  workspaceId: string;
  graphId: string | null;
  graphName: string;
  nodeId: string | null;
  initialExecutionId: string | null;
  nodeTitles: Readonly<Record<string, string>>;
  executionRunning: boolean;
  isDirty: boolean;
  returnFocusRef: React.RefObject<HTMLElement | null>;
  onClose: () => void;
}

export function ExecutionHistoryDrawer({
  workspaceId,
  graphId,
  graphName,
  nodeId,
  initialExecutionId,
  nodeTitles,
  executionRunning,
  isDirty,
  returnFocusRef,
  onClose,
}: ExecutionHistoryDrawerProps) {
  const { data: registry } = useNodeRegistry(workspaceId);
  const drawerRef = React.useRef<HTMLElement>(null);
  const closeButtonRef = React.useRef<HTMLButtonElement>(null);
  const [selectedExecutionId, setSelectedExecutionId] = React.useState<
    string | null
  >(initialExecutionId);
  const historyKey = React.useCallback(
    (
      index: number,
      previousPage: GraphExecutionList | null,
    ): ExecutionHistoryPageKey | null => {
      if (!graphId || (previousPage && !previousPage.next_cursor)) return null;
      return [
        "graph-execution-history",
        workspaceId,
        graphId,
        nodeId,
        index === 0 ? null : (previousPage?.next_cursor ?? null),
      ];
    },
    [graphId, nodeId, workspaceId],
  );
  const {
    data: historyPages,
    error: historyError,
    isLoading: loading,
    isValidating: historyValidating,
    size,
    setSize,
    mutate: refreshHistory,
  } = useSWRInfinite<GraphExecutionList, Error, typeof historyKey>(
    historyKey,
    loadExecutionHistoryPage,
    {
      revalidateFirstPage: true,
      revalidateOnMount: true,
    },
  );
  const items = React.useMemo(() => {
    const executions = historyPages?.flatMap((page) => page.items) ?? [];
    const known = new Set<string>();
    return executions.filter((execution) => {
      if (known.has(execution.execution_id)) return false;
      known.add(execution.execution_id);
      return true;
    });
  }, [historyPages]);
  const nextCursor = historyPages?.at(-1)?.next_cursor ?? null;
  const effectiveSelectedExecutionId =
    selectedExecutionId &&
    items.some((execution) => execution.execution_id === selectedExecutionId)
      ? selectedExecutionId
      : (items[0]?.execution_id ?? null);
  const detailKey: ExecutionDetailKey | null =
    graphId && effectiveSelectedExecutionId
      ? [
          "graph-execution-detail",
          workspaceId,
          graphId,
          effectiveSelectedExecutionId,
        ]
      : null;
  const {
    data: detail,
    error: detailFailure,
    isLoading: detailLoading,
    mutate: refreshDetail,
  } = useSWR<GraphExecutionDetail, Error, ExecutionDetailKey | null>(
    detailKey,
    loadExecutionDetail,
  );
  const previousExecutionRunningRef = React.useRef(executionRunning);
  React.useEffect(() => {
    const executionCompleted =
      previousExecutionRunningRef.current && !executionRunning;
    previousExecutionRunningRef.current = executionRunning;
    if (!executionCompleted) return;

    void refreshHistory();
    void refreshDetail();
  }, [executionRunning, refreshDetail, refreshHistory]);
  const closeDrawer = React.useCallback(() => {
    returnFocusRef.current?.focus();
    onClose();
  }, [onClose, returnFocusRef]);
  React.useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      event.preventDefault();
      closeDrawer();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [closeDrawer]);
  React.useEffect(() => {
    const drawer = drawerRef.current;
    const returnFocusElement = returnFocusRef.current;
    closeButtonRef.current?.focus();
    return () => {
      if (drawer?.contains(document.activeElement)) {
        returnFocusElement?.focus();
      }
    };
  }, [returnFocusRef]);
  const listError = historyError
    ? errorMessage(historyError, "Could not load execution history.")
    : null;
  const detailError = detailFailure
    ? errorMessage(detailFailure, "Could not load this execution.")
    : null;
  const loadingMore = historyValidating && Boolean(items.length);

  const selectedSummary = items.find(
    (execution) => execution.execution_id === effectiveSelectedExecutionId,
  );
  const visibleNodeResults = (detail?.node_results ?? [])
    .filter((result) => nodeId === null || result.node_id === nodeId)
    .toSorted((left, right) => left.position - right.position);
  const filteredNodeTitle = nodeId ? (nodeTitles[nodeId] ?? nodeId) : null;

  return (
    <aside
      ref={drawerRef}
      role="dialog"
      aria-label="Execution history"
      {...stylex.props(s.drawer)}
    >
      <header {...stylex.props(s.header)}>
        <span aria-hidden="true" {...stylex.props(s.headerIcon)}>
          <History size={14} />
        </span>
        <span {...stylex.props(s.headerCopy)}>
          <span {...stylex.props(s.title)}>Execution history</span>
          <span {...stylex.props(s.subtitle)}>
            {filteredNodeTitle
              ? `${graphName} · ${filteredNodeTitle}`
              : graphName}
          </span>
        </span>
        <button
          type="button"
          aria-label="Refresh execution history"
          title="Refresh execution history"
          disabled={historyValidating}
          {...stylex.props(s.headerButton)}
          onClick={() => {
            void refreshHistory();
            void refreshDetail();
          }}
        >
          <RefreshCw
            size={13}
            {...stylex.props(historyValidating ? s.spinner : null)}
          />
        </button>
        <button
          ref={closeButtonRef}
          type="button"
          aria-label="Close execution history"
          {...stylex.props(s.headerButton)}
          onClick={closeDrawer}
        >
          <X size={14} />
        </button>
      </header>

      {graphId && isDirty ? (
        <div role="note" {...stylex.props(s.dirtyWarning)}>
          <CircleAlert aria-hidden="true" size={14} />
          Runs started with unsaved changes are temporary and are not recorded
          here. Save the graph first to keep durable execution history.
        </div>
      ) : null}

      <div {...stylex.props(s.content)}>
        <section aria-label="Executions" {...stylex.props(s.listPane)}>
          <div role="list" {...stylex.props(s.list)}>
            {!graphId ? (
              <div {...stylex.props(s.message)}>
                Save this graph before browsing its executions.
              </div>
            ) : loading ? (
              <div role="status" {...stylex.props(s.message)}>
                <LoaderCircle size={16} {...stylex.props(s.spinner)} />
                Loading execution history…
              </div>
            ) : listError && items.length === 0 ? (
              <div role="alert" {...stylex.props(s.message, s.messageError)}>
                <CircleAlert size={16} />
                {listError}
                <button
                  type="button"
                  {...stylex.props(s.retry)}
                  onClick={() => void refreshHistory()}
                >
                  Try again
                </button>
              </div>
            ) : items.length === 0 ? (
              <div {...stylex.props(s.message)}>
                {filteredNodeTitle
                  ? `No recorded executions include ${filteredNodeTitle}.`
                  : "No executions have been recorded for this graph yet."}
              </div>
            ) : (
              items.map((execution) => {
                const selected =
                  execution.execution_id === effectiveSelectedExecutionId;
                return (
                  <button
                    key={execution.execution_id}
                    type="button"
                    role="listitem"
                    aria-current={selected ? "true" : undefined}
                    {...stylex.props(
                      s.listItem,
                      selected ? s.listItemSelected : null,
                    )}
                    onClick={() =>
                      setSelectedExecutionId(execution.execution_id)
                    }
                  >
                    <span {...stylex.props(s.listCopy)}>
                      <span {...stylex.props(s.listTop)}>
                        <span {...stylex.props(s.timestamp)}>
                          {executionTimestamp(execution)}
                        </span>
                        <span
                          {...stylex.props(
                            s.status,
                            statusStyle(execution.status),
                          )}
                        >
                          {execution.status}
                        </span>
                      </span>
                      <span {...stylex.props(s.meta)}>
                        r{execution.graph_revision} ·{" "}
                        {execution.scope.replaceAll("-", " ")} ·{" "}
                        {execution.requested_node_ids.length} requested node
                        {execution.requested_node_ids.length === 1
                          ? ""
                          : "s"} · {execution.node_count} node
                        {execution.node_count === 1 ? "" : "s"} ·{" "}
                        {execution.artifact_count} artifact
                        {execution.artifact_count === 1 ? "" : "s"}
                      </span>
                      <span {...stylex.props(s.id)}>
                        {execution.execution_id}
                      </span>
                    </span>
                    <ChevronRight size={13} />
                  </button>
                );
              })
            )}
          </div>
          {items.length > 0 && (nextCursor || listError) ? (
            <div {...stylex.props(s.loadMoreWrap)}>
              {listError ? (
                <div role="alert" {...stylex.props(s.messageError, s.meta)}>
                  {listError}
                </div>
              ) : null}
              {nextCursor ? (
                <button
                  type="button"
                  disabled={loadingMore}
                  {...stylex.props(s.loadMore)}
                  onClick={() => {
                    if (listError) {
                      void refreshHistory();
                    } else {
                      void setSize(size + 1);
                    }
                  }}
                >
                  {loadingMore ? (
                    <LoaderCircle size={12} {...stylex.props(s.spinner)} />
                  ) : null}
                  {loadingMore
                    ? "Loading…"
                    : listError
                      ? "Try loading again"
                      : "Load more"}
                </button>
              ) : null}
            </div>
          ) : null}
        </section>

        <section aria-label="Execution details" {...stylex.props(s.detailPane)}>
          {!effectiveSelectedExecutionId ? (
            <div {...stylex.props(s.message)}>
              Select an execution to inspect its node outputs.
            </div>
          ) : detailLoading ? (
            <div role="status" {...stylex.props(s.message)}>
              <LoaderCircle size={16} {...stylex.props(s.spinner)} />
              Loading execution details…
            </div>
          ) : detailError ? (
            <div role="alert" {...stylex.props(s.message, s.messageError)}>
              <CircleAlert size={16} />
              {detailError}
              <button
                type="button"
                {...stylex.props(s.retry)}
                onClick={() => {
                  void refreshDetail();
                }}
              >
                Try again
              </button>
            </div>
          ) : detail && selectedSummary ? (
            <>
              <div {...stylex.props(s.detailHeader)}>
                <div {...stylex.props(s.detailHeading)}>
                  <span {...stylex.props(s.detailTitle)}>
                    {executionTimestamp(detail)}
                  </span>
                  <span {...stylex.props(s.status, statusStyle(detail.status))}>
                    {detail.status}
                  </span>
                </div>
                <div {...stylex.props(s.detailMeta)}>
                  <span>graph revision {detail.graph_revision}</span>
                  <span>{detail.scope.replaceAll("-", " ")}</span>
                  <span>
                    {detail.requested_node_ids.length} requested node
                    {detail.requested_node_ids.length === 1 ? "" : "s"}
                  </span>
                  <span>
                    {detail.node_count} node result
                    {detail.node_count === 1 ? "" : "s"}
                  </span>
                  <span>
                    {detail.artifact_count} artifact
                    {detail.artifact_count === 1 ? "" : "s"}
                  </span>
                </div>
                {detail.error ? (
                  <p {...stylex.props(s.nodeError)}>{detail.error}</p>
                ) : null}
              </div>
              {visibleNodeResults.length ? (
                <div {...stylex.props(s.nodeList)}>
                  {visibleNodeResults.map((result) => {
                    const outputs = result.outputs;
                    return (
                      <article
                        key={result.node_id}
                        {...stylex.props(s.nodeResult)}
                      >
                        <header {...stylex.props(s.nodeHead)}>
                          <span {...stylex.props(s.nodePosition)}>
                            {result.position + 1}
                          </span>
                          <span {...stylex.props(s.nodeCopy)}>
                            <span {...stylex.props(s.nodeTitle)}>
                              {nodeTitles[result.node_id] ?? result.node_id}
                            </span>
                            <span {...stylex.props(s.nodeId)}>
                              {result.node_id}
                            </span>
                          </span>
                          <span
                            {...stylex.props(
                              s.status,
                              result.status === "succeeded"
                                ? s.statusSuccess
                                : result.status === "failed"
                                  ? s.statusFailure
                                  : null,
                            )}
                          >
                            {result.status}
                          </span>
                        </header>
                        {result.error ? (
                          <p {...stylex.props(s.nodeError)}>{result.error}</p>
                        ) : null}
                        {outputs.length ? (
                          <div {...stylex.props(s.outputList)}>
                            {outputs.map((output) =>
                              output.artifacts.length ? (
                                <ArtifactPortPreview
                                  key={output.port}
                                  output={output}
                                  artifactTypes={registry?.artifact_types ?? []}
                                  previewHeight={300}
                                />
                              ) : (
                                <section
                                  key={output.port}
                                  aria-label={`${output.port} historical artifact unavailable`}
                                  {...stylex.props(s.unavailableOutput)}
                                >
                                  <span {...stylex.props(s.unavailablePort)}>
                                    {output.port}
                                  </span>
                                  <span {...stylex.props(s.meta)}>
                                    Historical artifact metadata is unavailable.
                                    The execution record remains, but its
                                    payload cannot be previewed.
                                  </span>
                                </section>
                              ),
                            )}
                          </div>
                        ) : (
                          <span {...stylex.props(s.meta)}>
                            No artifacts produced.
                          </span>
                        )}
                      </article>
                    );
                  })}
                </div>
              ) : (
                <div {...stylex.props(s.message)}>
                  {filteredNodeTitle
                    ? `${filteredNodeTitle} has no recorded result in this execution.`
                    : "This execution has no recorded node results."}
                </div>
              )}
            </>
          ) : null}
        </section>
      </div>
    </aside>
  );
}
