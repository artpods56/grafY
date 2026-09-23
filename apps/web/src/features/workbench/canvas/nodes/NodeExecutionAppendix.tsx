"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Tabs } from "@base-ui/react/tabs";
import useSWR from "swr";

import {
  getGraphExecution,
  listGraphExecutions,
  type RunNodeResult,
} from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";
import type {
  NodeExecution,
  WorkflowNodeHistoryContext,
  WorkflowNodeProgress,
  WorkflowNodeProgressEntry,
} from "../types";

const MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";

const s = stylex.create({
  root: {
    minWidth: 0,
    maxWidth: "100%",
    marginTop: "6px",
    color: tokens.colorText,
    boxSizing: "border-box",
  },
  footprint: {
    minWidth: 0,
    maxWidth: "100%",
    overflow: "hidden",
    margin: 0,
    paddingInline: "10px",
    color: tokens.colorSubtle,
    fontFamily: MONO,
    fontSize: "9px",
    lineHeight: 1.45,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  footprintError: { color: tokens.colorDanger },
  footprintEvent: { color: tokens.colorMuted },
  expanded: {
    minWidth: 0,
    maxWidth: "100%",
    display: "grid",
    gap: "5px",
  },
  tabs: {
    minWidth: 0,
    maxWidth: "100%",
    display: "grid",
    gap: "5px",
    overflow: "hidden",
  },
  tabList: {
    width: "fit-content",
    display: "flex",
    alignItems: "center",
    gap: "2px",
    padding: "2px",
    borderRadius: "9999px",
    backgroundColor: tokens.colorSurfaceSunken,
  },
  tab: {
    minHeight: "22px",
    display: "inline-flex",
    alignItems: "center",
    paddingInline: "9px",
    borderWidth: 0,
    borderRadius: "9999px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
    outlineStyle: "solid",
    outlineColor: tokens.colorAccent,
    outlineOffset: "2px",
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorHoverStrong,
    },
    color: tokens.colorMuted,
    cursor: "pointer",
    fontSize: "9px",
    fontWeight: 600,
    letterSpacing: "0.04em",
    textTransform: "uppercase",
  },
  tabActive: {
    backgroundColor: tokens.colorSurface,
    color: tokens.colorTextEmphasis,
  },
  tabCount: {
    marginLeft: "5px",
    color: tokens.colorSubtle,
    fontFamily: MONO,
    fontSize: "9px",
    fontWeight: 600,
  },
  panel: {
    minWidth: 0,
    maxWidth: "100%",
    overflow: "hidden",
  },
  stack: {
    minWidth: 0,
    maxWidth: "100%",
    display: "grid",
    gap: "3px",
    margin: 0,
    padding: 0,
    listStyle: "none",
  },
  disclosureList: {
    maxHeight: "126px",
    overflowX: "hidden",
    overflowY: "auto",
  },
  row: {
    minWidth: 0,
    maxWidth: "100%",
    display: "flex",
    alignItems: "baseline",
    gap: "6px",
    overflow: "hidden",
    paddingInline: "10px",
    color: tokens.colorMuted,
    fontSize: "9px",
    lineHeight: 1.45,
  },
  rowCopy: {
    minWidth: 0,
    flex: 1,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  rowContext: {
    color: tokens.colorSubtle,
    fontFamily: MONO,
  },
  rowAmount: {
    color: tokens.colorSubtle,
    fontFamily: MONO,
  },
  rowError: { color: tokens.colorDanger },
  expandButton: {
    flexShrink: 0,
    padding: 0,
    borderWidth: 0,
    outlineWidth: { default: 0, ":focus-visible": "2px" },
    outlineStyle: "solid",
    outlineColor: tokens.colorAccent,
    outlineOffset: "2px",
    backgroundColor: "transparent",
    color: { default: tokens.colorSubtle, ":hover": tokens.colorMuted },
    cursor: "pointer",
    fontFamily: MONO,
    fontSize: "9px",
    fontWeight: 600,
  },
  omission: {
    margin: 0,
    paddingInline: "10px",
    color: tokens.colorSubtle,
    fontSize: "9px",
    lineHeight: 1.45,
  },
  historyList: {
    maxHeight: "146px",
    overflowX: "hidden",
    overflowY: "auto",
  },
  historyButton: {
    width: "100%",
    minWidth: 0,
    display: "flex",
    alignItems: "baseline",
    gap: "7px",
    overflow: "hidden",
    padding: "2px 10px",
    borderWidth: 0,
    outlineWidth: { default: 0, ":focus-visible": "2px" },
    outlineStyle: "solid",
    outlineColor: tokens.colorAccent,
    outlineOffset: "-2px",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: tokens.colorMuted,
    cursor: "pointer",
    fontSize: "9px",
    lineHeight: 1.45,
    textAlign: "left",
  },
  historyTimestamp: {
    minWidth: 0,
    flex: 1,
    overflow: "hidden",
    color: tokens.colorMuted,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  historyMeta: {
    flexShrink: 0,
    color: tokens.colorSubtle,
    fontFamily: MONO,
  },
  temporaryRow: {
    color: tokens.colorWarning,
  },
  temporaryLabel: {
    minWidth: 0,
    flex: 1,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  state: {
    margin: 0,
    paddingInline: "10px",
    color: tokens.colorSubtle,
    fontSize: "9px",
    lineHeight: 1.45,
  },
  stateError: { color: tokens.colorDanger },
});

type AppendixTab = "events" | "history";

interface NodeHistoryRow {
  executionId: string;
  graphRevision: number;
  artifactCount: number;
  timestamp: string;
}

interface NodeHistoryResult {
  rows: readonly NodeHistoryRow[];
  hasMore: boolean;
}

type NodeHistoryKey = readonly [
  "node-execution-appendix-history",
  string,
  string,
  string,
  string,
];

export interface NodeExecutionAppendixProps {
  nodeId: string;
  nodeTitle: string;
  expanded: boolean;
  width: number;
  execution: NodeExecution;
  progress: WorkflowNodeProgress | null;
  run: RunNodeResult | null;
  historyContext: WorkflowNodeHistoryContext | null;
  onOpenHistory?: (nodeId: string, executionId?: string) => void;
}

function interactionProps(props: ReturnType<typeof stylex.props>) {
  return {
    ...props,
    className: `nodrag nopan nowheel${props.className ? ` ${props.className}` : ""}`,
  };
}

function progressEntryContext(
  entry: WorkflowNodeProgressEntry,
  nodeTitle: string,
): string {
  const source = entry.sourceNodePath.length
    ? entry.sourceNodePath.join(" › ")
    : nodeTitle;
  const invocationPath = entry.invocationPath.length
    ? entry.invocationPath.map((index) => index + 1)
    : entry.invocationIndex === null
      ? []
      : [entry.invocationIndex + 1];
  if (!invocationPath.length) return source;
  const invocationLabel = invocationPath.length === 1 ? "item" : "items";
  return `${source} · ${invocationLabel} ${invocationPath.join(" › ")}`;
}

function progressEntryAmount(entry: WorkflowNodeProgressEntry): string | null {
  if (entry.current === null && entry.total === null) return null;
  if (entry.total === null) return String(entry.current);
  return `${entry.current ?? 0} / ${entry.total}`;
}

function progressEntryLabel(
  entry: WorkflowNodeProgressEntry,
  nodeTitle: string,
): string {
  const parts = [progressEntryContext(entry, nodeTitle), entry.message];
  const amount = progressEntryAmount(entry);
  if (amount) parts.push(amount);
  return parts.join(" · ");
}

function historyTimestamp(row: NodeHistoryRow): string {
  const date = new Date(row.timestamp);
  if (Number.isNaN(date.getTime())) return row.timestamp;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

async function loadNodeHistory([
  ,
  workspaceId,
  graphId,
  nodeId,
]: NodeHistoryKey): Promise<NodeHistoryResult> {
  const executionList = await listGraphExecutions(workspaceId, graphId, {
    limit: 5,
    nodeId,
  });
  const details = await Promise.all(
    executionList.items.map((item) =>
      getGraphExecution(workspaceId, graphId, item.execution_id),
    ),
  );
  const rows: NodeHistoryRow[] = [];
  for (const detail of details) {
    let nodeArtifactCount = 0;
    for (const result of detail.node_results) {
      if (result.node_id !== nodeId) continue;
      for (const output of result.outputs) {
        nodeArtifactCount += output.artifacts.length;
      }
    }
    if (nodeArtifactCount === 0) continue;
    rows.push({
      executionId: detail.execution_id,
      graphRevision: detail.graph_revision,
      artifactCount: nodeArtifactCount,
      timestamp: detail.finished_at ?? detail.started_at ?? detail.created_at,
    });
  }
  return { rows, hasMore: executionList.next_cursor !== null };
}

function ProgressRow({
  entry,
  nodeTitle,
}: {
  entry: WorkflowNodeProgressEntry;
  nodeTitle: string;
}) {
  const context = progressEntryContext(entry, nodeTitle);
  const amount = progressEntryAmount(entry);
  return (
    <span
      title={progressEntryLabel(entry, nodeTitle)}
      {...stylex.props(s.rowCopy)}
    >
      <span {...stylex.props(s.rowContext)}>{context}</span>
      {" · "}
      {entry.message}
      {amount ? (
        <span {...stylex.props(s.rowAmount)}>{` · ${amount}`}</span>
      ) : null}
    </span>
  );
}

function CollapsedFootprint({
  nodeTitle,
  execution,
  latestEvent,
  artifactCount,
}: {
  nodeTitle: string;
  execution: NodeExecution;
  latestEvent: WorkflowNodeProgressEntry | undefined;
  artifactCount: number;
}) {
  if (execution.error) {
    return (
      <p
        role="alert"
        title={execution.error}
        {...stylex.props(s.footprint, s.footprintError)}
      >
        {execution.error}
      </p>
    );
  }

  const executionIsActive =
    execution.status === "queued" ||
    execution.status === "running" ||
    execution.status === "cancelling";
  if (latestEvent && (executionIsActive || artifactCount === 0)) {
    return (
      <p
        aria-live="polite"
        title={progressEntryLabel(latestEvent, nodeTitle)}
        {...stylex.props(s.footprint, s.footprintEvent)}
      >
        <span {...stylex.props(s.rowContext)}>
          {progressEntryContext(latestEvent, nodeTitle)}
        </span>
        {" · "}
        {latestEvent.message}
      </p>
    );
  }

  if (artifactCount > 0) {
    return (
      <p {...stylex.props(s.footprint)}>
        Latest result · {artifactCount} artifact{artifactCount === 1 ? "" : "s"}
      </p>
    );
  }

  return null;
}

function EventsPanel({
  nodeTitle,
  execution,
  entries,
  omittedCount,
}: {
  nodeTitle: string;
  execution: NodeExecution;
  entries: readonly WorkflowNodeProgressEntry[];
  omittedCount: number;
}) {
  const [disclosed, setDisclosed] = React.useState(false);
  const latest = entries[0];
  const earlier = entries.slice(1);

  if (!latest && !execution.error) {
    return <p {...stylex.props(s.state)}>No events for this node.</p>;
  }

  return (
    <div {...stylex.props(s.stack)}>
      {execution.error ? (
        <div role="alert" {...stylex.props(s.row, s.rowError)}>
          <span title={execution.error} {...stylex.props(s.rowCopy)}>
            {execution.error}
          </span>
        </div>
      ) : null}
      {latest ? (
        <div aria-live="polite" {...stylex.props(s.row)}>
          <ProgressRow entry={latest} nodeTitle={nodeTitle} />
          {earlier.length ? (
            <button
              type="button"
              aria-expanded={disclosed}
              aria-label={
                disclosed
                  ? "Hide earlier events"
                  : `Show ${earlier.length} earlier events`
              }
              {...interactionProps(stylex.props(s.expandButton))}
              onClick={() => setDisclosed((current) => !current)}
            >
              {disclosed ? "−" : `+${earlier.length}`}
            </button>
          ) : null}
        </div>
      ) : null}
      {disclosed ? (
        <ol
          aria-label="Earlier events"
          {...interactionProps(stylex.props(s.stack, s.disclosureList))}
        >
          {earlier.map((entry) => (
            <li key={entry.sequence} {...stylex.props(s.row)}>
              <ProgressRow entry={entry} nodeTitle={nodeTitle} />
            </li>
          ))}
        </ol>
      ) : null}
      {omittedCount > 0 ? (
        <p {...stylex.props(s.omission)}>
          {omittedCount} earlier update{omittedCount === 1 ? "" : "s"} omitted
        </p>
      ) : null}
    </div>
  );
}

function HistoryPanel({
  nodeId,
  graphId,
  isDirty,
  artifactCount,
  rows,
  loading,
  error,
  onOpenHistory,
}: {
  nodeId: string;
  graphId: string | null;
  isDirty: boolean;
  artifactCount: number;
  rows: readonly NodeHistoryRow[];
  loading: boolean;
  error: Error | undefined;
  onOpenHistory?: (nodeId: string, executionId?: string) => void;
}) {
  const showTemporaryResult = artifactCount > 0 && (!graphId || isDirty);
  return (
    <div
      role="list"
      aria-label="Node execution history"
      {...stylex.props(s.stack, s.historyList)}
    >
      {showTemporaryResult ? (
        <div
          role="listitem"
          aria-label="Temporary current result"
          {...stylex.props(s.row, s.temporaryRow)}
        >
          <span {...stylex.props(s.temporaryLabel)}>
            Current result · temporary
          </span>
          <span {...stylex.props(s.historyMeta)}>
            {artifactCount} artifact{artifactCount === 1 ? "" : "s"}
          </span>
        </div>
      ) : null}
      {!graphId ? (
        <p {...stylex.props(s.state)}>
          Save the graph to build durable history.
        </p>
      ) : loading ? (
        <p role="status" {...stylex.props(s.state)}>
          Loading history…
        </p>
      ) : error ? (
        <p
          role="alert"
          title={error.message}
          {...stylex.props(s.state, s.stateError)}
        >
          History unavailable.
        </p>
      ) : rows.length === 0 ? (
        <p {...stylex.props(s.state)}>No materialized results yet.</p>
      ) : (
        rows.map((row) => {
          const timestamp = historyTimestamp(row);
          const content = (
            <>
              <span title={timestamp} {...stylex.props(s.historyTimestamp)}>
                {timestamp}
              </span>
              <span {...stylex.props(s.historyMeta)}>r{row.graphRevision}</span>
              <span {...stylex.props(s.historyMeta)}>
                {row.artifactCount} artifact{row.artifactCount === 1 ? "" : "s"}
              </span>
            </>
          );
          return onOpenHistory ? (
            <button
              key={row.executionId}
              type="button"
              role="listitem"
              aria-label={`Open ${timestamp}, revision ${row.graphRevision}, ${row.artifactCount} artifacts`}
              {...interactionProps(stylex.props(s.historyButton))}
              onClick={() => onOpenHistory(nodeId, row.executionId)}
            >
              {content}
            </button>
          ) : (
            <div key={row.executionId} role="listitem" {...stylex.props(s.row)}>
              {content}
            </div>
          );
        })
      )}
    </div>
  );
}

export function NodeExecutionAppendix({
  nodeId,
  nodeTitle,
  expanded,
  width,
  execution,
  progress,
  run,
  historyContext,
  onOpenHistory,
}: NodeExecutionAppendixProps) {
  const [activeTab, setActiveTab] = React.useState<AppendixTab>("events");
  const entries = React.useMemo(
    () =>
      [...(progress?.entries ?? [])].sort(
        (left, right) => right.sequence - left.sequence,
      ),
    [progress],
  );
  const artifactCount = (run?.outputs ?? []).reduce(
    (total, output) => total + output.artifacts.length,
    0,
  );
  const workspaceId = historyContext?.workspaceId ?? null;
  const graphId = historyContext?.graphId ?? null;
  const isDirty = historyContext?.isDirty ?? true;
  const runArtifactRevision = JSON.stringify(
    (run?.outputs ?? []).flatMap((output) =>
      output.artifacts.map((artifact) => artifact.artifact_id),
    ),
  );
  const historyKey: NodeHistoryKey | null =
    expanded && workspaceId && graphId
      ? [
          "node-execution-appendix-history",
          workspaceId,
          graphId,
          nodeId,
          runArtifactRevision,
        ]
      : null;
  const {
    data: historyResult,
    error: historyError,
    isLoading: historyLoading,
  } = useSWR<NodeHistoryResult, Error, NodeHistoryKey | null>(
    historyKey,
    loadNodeHistory,
  );
  const temporaryHistoryCount =
    artifactCount > 0 && (!graphId || isDirty) ? 1 : 0;
  const durableHistoryCount = historyResult?.rows.length ?? 0;
  const historyCount = `${durableHistoryCount + temporaryHistoryCount}${
    historyResult?.hasMore ? "+" : ""
  }`;
  const eventCount =
    entries.length + (progress?.omittedCount ?? 0) + (execution.error ? 1 : 0);

  const footprint = (
    <CollapsedFootprint
      nodeTitle={nodeTitle}
      execution={execution}
      latestEvent={entries[0]}
      artifactCount={artifactCount}
    />
  );
  if (!expanded) {
    if (!execution.error && !entries.length && artifactCount === 0) return null;
    return (
      <aside
        aria-label={`${nodeTitle} execution summary`}
        {...interactionProps(stylex.props(s.root))}
        style={{ width }}
      >
        {footprint}
      </aside>
    );
  }

  // A node that has never run has nothing to put in either tab, and an empty
  // Events/History pair is chrome reporting its own emptiness.
  if (
    execution.status === "idle" &&
    eventCount === 0 &&
    durableHistoryCount + temporaryHistoryCount === 0 &&
    !historyError
  ) {
    return null;
  }

  return (
    <aside
      aria-label={`${nodeTitle} execution appendix`}
      {...interactionProps(stylex.props(s.root, s.expanded))}
      style={{ width }}
    >
      <Tabs.Root
        value={activeTab}
        onValueChange={(value) => {
          if (value === "events" || value === "history") {
            setActiveTab(value);
          }
        }}
        {...stylex.props(s.tabs)}
      >
        <Tabs.List
          aria-label={`${nodeTitle} execution context`}
          {...interactionProps(stylex.props(s.tabList))}
        >
          <Tabs.Tab
            value="events"
            {...interactionProps(
              stylex.props(s.tab, activeTab === "events" ? s.tabActive : null),
            )}
          >
            Events <span {...stylex.props(s.tabCount)}>{eventCount}</span>
          </Tabs.Tab>
          <Tabs.Tab
            value="history"
            {...interactionProps(
              stylex.props(s.tab, activeTab === "history" ? s.tabActive : null),
            )}
          >
            History <span {...stylex.props(s.tabCount)}>{historyCount}</span>
          </Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="events" {...stylex.props(s.panel)}>
          <EventsPanel
            nodeTitle={nodeTitle}
            execution={execution}
            entries={entries}
            omittedCount={progress?.omittedCount ?? 0}
          />
        </Tabs.Panel>
        <Tabs.Panel value="history" {...stylex.props(s.panel)}>
          <HistoryPanel
            nodeId={nodeId}
            graphId={graphId}
            isDirty={isDirty}
            artifactCount={artifactCount}
            rows={historyResult?.rows ?? []}
            loading={historyLoading}
            error={historyError}
            onOpenHistory={onOpenHistory}
          />
        </Tabs.Panel>
      </Tabs.Root>
    </aside>
  );
}
