"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Tabs } from "@base-ui/react/tabs";

import type {
  RunExecutionNodeStatus,
  RunNodeResult,
  RunPortOutput,
} from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { Button } from "@/components/ui/button";
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
  /** The row's own type over the kit's text Button. */
  expandButton: {
    fontFamily: MONO,
    fontSize: "9px",
    fontWeight: 600,
    color: {
      default: tokens.colorSubtle,
      ":hover:not(:disabled)": tokens.colorMuted,
    },
  },
  omission: {
    margin: 0,
    paddingInline: "10px",
    color: tokens.colorSubtle,
    fontSize: "9px",
    lineHeight: 1.45,
  },
  rowMeta: {
    flexShrink: 0,
    color: tokens.colorSubtle,
    fontFamily: MONO,
  },
  state: {
    margin: 0,
    paddingInline: "10px",
    color: tokens.colorSubtle,
    fontSize: "9px",
    lineHeight: 1.45,
  },
});

type AppendixTab = "events" | "result";

/**
 * The state of this node's instance, as the Project derives it.
 *
 * The canvas overlay carries the coarse status the run surface publishes, so a
 * caller that knows the derived instance state passes it and the card says
 * "fresh" or "stale" outright. Without one the card reads what the overlay can
 * still tell it, and never invents a state it was not given.
 */
export type NodeInstanceState = RunExecutionNodeStatus;

export interface NodeExecutionAppendixProps {
  nodeId: string;
  nodeTitle: string;
  expanded: boolean;
  width: number;
  execution: NodeExecution;
  progress: WorkflowNodeProgress | null;
  run: RunNodeResult | null;
  historyContext: WorkflowNodeHistoryContext | null;
  instanceState?: NodeInstanceState | null;
}

const STATE_LABELS: Record<NodeInstanceState, string> = {
  fresh: "Fresh",
  stale: "Stale",
  queued: "Queued",
  running: "Running",
  failed: "Failed",
};

const STATE_EXPLANATIONS: Record<NodeInstanceState, string> = {
  fresh: "Its current fingerprint has a stored result.",
  stale: "The graph changed since this instance last computed.",
  queued: "A Run is waiting to compute it.",
  running: "A computation for it is in flight.",
  failed: "Its last attempt failed; a Run retries it.",
};

function nodeArtifactCount(
  outputs: readonly RunPortOutput[] | undefined,
): number {
  return (outputs ?? []).reduce(
    (total, output) => total + output.artifacts.length,
    0,
  );
}

function deriveInstanceState(
  execution: NodeExecution,
  run: RunNodeResult | null,
  instanceState: NodeInstanceState | null | undefined,
): NodeInstanceState | null {
  if (instanceState) return instanceState;
  switch (execution.status) {
    case "queued":
      return "queued";
    case "running":
    case "cancelling":
      return "running";
    case "failed":
      return "failed";
    case "succeeded":
      return "fresh";
    default:
      return run ? "stale" : null;
  }
}

function storedResultLabel(run: RunNodeResult | null): string | null {
  const created_at = run?.created_at;
  if (!created_at) return null;
  const storedAt = new Date(created_at);
  if (Number.isNaN(storedAt.getTime())) return null;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(storedAt);
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
  state,
}: {
  nodeTitle: string;
  execution: NodeExecution;
  latestEvent: WorkflowNodeProgressEntry | undefined;
  artifactCount: number;
  state: NodeInstanceState | null;
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
    const stateLabel = state ? STATE_LABELS[state] : "Stored";
    return (
      <p
        title={state ? STATE_EXPLANATIONS[state] : undefined}
        {...stylex.props(s.footprint)}
      >
        {stateLabel} result · {artifactCount} artifact
        {artifactCount === 1 ? "" : "s"}
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
            <Button
              type="button"
              size="text"
              variant="ghost"
              aria-expanded={disclosed}
              aria-label={
                disclosed
                  ? "Hide earlier events"
                  : `Show ${earlier.length} earlier events`
              }
              className="nodrag nopan nowheel"
              xstyle={s.expandButton}
              onClick={() => setDisclosed((current) => !current)}
            >
              {disclosed ? "−" : `+${earlier.length}`}
            </Button>
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

function ResultPanel({
  state,
  run,
  artifactCount,
}: {
  state: NodeInstanceState | null;
  run: RunNodeResult | null;
  artifactCount: number;
}) {
  const storedAt = storedResultLabel(run);
  return (
    <div role="list" aria-label="Stored result" {...stylex.props(s.stack)}>
      <div role="listitem" {...stylex.props(s.row)}>
        <span
          {...stylex.props(s.rowCopy)}
          title={STATE_EXPLANATIONS[state ?? "stale"]}
        >
          {state
            ? `${STATE_LABELS[state]} · ${STATE_EXPLANATIONS[state]}`
            : "This node has not been in a Run yet."}
        </span>
      </div>
      {run?.status === "failed" && run.error ? (
        <div role="alert" {...stylex.props(s.row, s.rowError)}>
          <span title={run.error} {...stylex.props(s.rowCopy)}>
            {run.error}
          </span>
        </div>
      ) : null}
      {artifactCount === 0 ? (
        <p {...stylex.props(s.state)}>No stored result for this instance.</p>
      ) : (
        <>
          <div role="listitem" {...stylex.props(s.row)}>
            <span {...stylex.props(s.rowCopy)}>
              {storedAt
                ? `Stored ${storedAt}`
                : "Stored result of this instance"}
            </span>
            <span {...stylex.props(s.rowMeta)}>
              {artifactCount} artifact{artifactCount === 1 ? "" : "s"}
            </span>
          </div>
          {run?.result_fingerprint ? (
            <div role="listitem" {...stylex.props(s.row)}>
              <span
                title={run.result_fingerprint}
                {...stylex.props(s.rowCopy, s.rowContext)}
              >
                {run.result_fingerprint.slice(0, 12)}
              </span>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}

export function NodeExecutionAppendix({
  nodeTitle,
  expanded,
  width,
  execution,
  progress,
  run,
  instanceState = null,
}: NodeExecutionAppendixProps) {
  const [activeTab, setActiveTab] = React.useState<AppendixTab>("events");
  const entries = React.useMemo(
    () =>
      [...(progress?.entries ?? [])].sort(
        (left, right) => right.sequence - left.sequence,
      ),
    [progress],
  );
  const artifactCount = nodeArtifactCount(run?.outputs);
  const state = deriveInstanceState(execution, run, instanceState);
  const eventCount =
    entries.length + (progress?.omittedCount ?? 0) + (execution.error ? 1 : 0);
  const resultCount =
    (run && artifactCount > 0 ? 1 : 0) +
    (run?.status === "failed" ? 1 : 0) +
    (state ? 1 : 0);

  const footprint = (
    <CollapsedFootprint
      nodeTitle={nodeTitle}
      execution={execution}
      latestEvent={entries[0]}
      artifactCount={artifactCount}
      state={state}
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

  // A node that has never been in a Run and never stored a result has nothing
  // to put in either tab, and an empty pair is chrome reporting its own
  // emptiness.
  if (eventCount === 0 && resultCount === 0) {
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
          if (value === "events" || value === "result") {
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
            value="result"
            {...interactionProps(
              stylex.props(s.tab, activeTab === "result" ? s.tabActive : null),
            )}
          >
            Result <span {...stylex.props(s.tabCount)}>{resultCount}</span>
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
        <Tabs.Panel value="result" {...stylex.props(s.panel)}>
          <ResultPanel state={state} run={run} artifactCount={artifactCount} />
        </Tabs.Panel>
      </Tabs.Root>
    </aside>
  );
}
