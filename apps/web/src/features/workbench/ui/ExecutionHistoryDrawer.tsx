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
import { type GraphExecutionDetail, type GraphExecutionList } from "@/lib/api";
import { ArtifactPortPreview } from "../canvas/nodes/ArtifactsAppendix";
import { executionHistoryDrawerStyles as s } from "./ExecutionHistoryDrawer.styles";
import {
  errorMessage,
  executionTimestamp,
  statusStyle,
} from "./execution-history-display";
import {
  type ExecutionDetailKey,
  type ExecutionHistoryPageKey,
  loadExecutionDetail,
  loadExecutionHistoryPage,
} from "./execution-history-query";

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
