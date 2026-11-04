"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import useSWR from "swr";
import {
  CircleAlert,
  ListChecks,
  LoaderCircle,
  RefreshCw,
  X,
} from "lucide-react";

import type { Run, RunList, WorkspaceMember } from "@/lib/api";

import { Button, IconButton } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";
import { executionHistoryDrawerStyles as s } from "./ExecutionHistoryDrawer.styles";
import {
  errorMessage,
  graphLabel,
  isActiveRun,
  runFinishLabel,
  runStartLabel,
  runStarterNames,
  runTargetsSummary,
  starterLabel,
  statusStyle,
} from "./execution-history-display";
import {
  type ProjectRunsKey,
  type RunStartersKey,
  loadProjectRuns,
  loadRunStarters,
  projectRunsKey,
  runStartersKey,
} from "./execution-history-query";

/** How often the list re-reads itself while a Run still holds its demand. */
const ACTIVE_RUN_REFRESH_MS = 4000;

export interface ExecutionHistoryDrawerProps {
  workspaceId: string;
  /**
   * The Project whose Runs are listed: a Run is a demand over one Project's
   * document, so with no Project there is nothing to demand. Optional only
   * because `Workbench` is still ported to Projects; the drawer says so when it
   * is absent.
   */
  projectId?: string | null;
  /** Which Graph the author has open, so its Runs read apart from the rest. */
  graphId?: string | null;
  returnFocusRef: React.RefObject<HTMLElement | null>;
  onClose: () => void;

  /**
   * @deprecated Retired with execution history. Accepted so the un-ported
   * `Workbench` compiles, and never read.
   */
  graphName?: string;
  /** @deprecated Retired with execution history; never read. */
  nodeId?: string | null;
  /** @deprecated Retired with execution history; never read. */
  initialExecutionId?: string | null;
  /** @deprecated Retired with execution history; never read. */
  nodeTitles?: Readonly<Record<string, string>>;
  /** @deprecated Runs are independent of the author's own run; never read. */
  executionRunning?: boolean;
  /** @deprecated Edits never lock a document; never read. */
  isDirty?: boolean;
}

export function ExecutionHistoryDrawer({
  workspaceId,
  projectId,
  graphId,
  returnFocusRef,
  onClose,
}: ExecutionHistoryDrawerProps) {
  const drawerRef = React.useRef<HTMLElement>(null);
  const closeButtonRef = React.useRef<HTMLButtonElement>(null);
  const runsKey = projectRunsKey(workspaceId, projectId);
  const {
    data: runList,
    error: runsFailure,
    isLoading,
    isValidating,
    mutate: refreshRuns,
  } = useSWR<RunList, Error, ProjectRunsKey | null>(runsKey, loadProjectRuns, {
    revalidateOnMount: true,
  });
  const runs = runList?.runs ?? [];
  const startersKey = runStartersKey(workspaceId, runs);
  const { data: members } = useSWR<
    readonly WorkspaceMember[],
    Error,
    RunStartersKey | null
  >(startersKey, loadRunStarters, { shouldRetryOnError: false });
  const starterNames = React.useMemo(() => runStarterNames(members), [members]);
  const activeCount = runs.filter(isActiveRun).length;

  /*
   * A Run finishes while the person is still reading the list, and this component
   * is not one of the room's `run.finished` listeners. Until the Workbench wires
   * those in, the list re-reads itself only while some Run still holds its demand,
   * and goes quiet once every Run is terminal.
   */
  const someRunHoldsDemand = activeCount > 0;
  React.useEffect(() => {
    if (!someRunHoldsDemand) return;
    const timer = window.setInterval(
      () => void refreshRuns(),
      ACTIVE_RUN_REFRESH_MS,
    );
    return () => window.clearInterval(timer);
  }, [refreshRuns, someRunHoldsDemand]);

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
  /*
   * Layout effect on purpose: the cleanup has to read where focus is while the
   * drawer's nodes are still attached. A passive cleanup runs after React has
   * detached them, by which point the browser has already dropped focus to
   * `<body>` and there is nothing left to hand back to.
   */
  React.useLayoutEffect(() => {
    const drawer = drawerRef.current;
    const returnFocusElement = returnFocusRef.current;
    closeButtonRef.current?.focus();
    return () => {
      if (drawer?.contains(document.activeElement)) {
        returnFocusElement?.focus();
      }
    };
  }, [returnFocusRef]);

  const listError = runsFailure
    ? errorMessage(runsFailure, "Could not load the runs of this project.")
    : null;

  return (
    <aside
      ref={drawerRef}
      role="dialog"
      aria-label="Runs"
      {...stylex.props(s.drawer)}
    >
      <header {...stylex.props(s.header)}>
        <span aria-hidden="true" {...stylex.props(s.headerIcon)}>
          <ListChecks size={14} />
        </span>
        <span {...stylex.props(s.headerCopy)}>
          <span {...stylex.props(s.title)}>Runs</span>
          <span {...stylex.props(s.subtitle)}>
            {activeCount > 0
              ? `${activeCount} running now`
              : "Demands for fresh results"}
          </span>
        </span>
        <IconButton
          label="Refresh runs"
          size="md"
          disabled={isValidating}
          xstyle={s.headerButton}
          onClick={() => {
            void refreshRuns();
          }}
        >
          <RefreshCw
            size={13}
            {...stylex.props(isValidating ? s.spinner : null)}
          />
        </IconButton>
        <IconButton
          ref={closeButtonRef}
          label="Close runs"
          size="md"
          xstyle={s.headerButton}
          onClick={closeDrawer}
        >
          <X size={14} />
        </IconButton>
      </header>

      <div {...stylex.props(s.content)}>
        <section aria-label="Project runs" {...stylex.props(s.listPane)}>
          <div role="list" {...stylex.props(s.list)}>
            {!projectId ? (
              <div {...stylex.props(s.message)}>
                Runs belong to a project. Open a saved project to see what it is
                waiting for.
              </div>
            ) : isLoading ? (
              <Notice tone="neutral" xstyle={s.message}>
                <LoaderCircle size={16} {...stylex.props(s.spinner)} />
                Loading runs…
              </Notice>
            ) : listError && runs.length === 0 ? (
              <Notice
                tone="danger"
                xstyle={s.message}
                action={
                  <Button
                    variant="secondary"
                    size="xs"
                    onClick={() => void refreshRuns()}
                  >
                    Try again
                  </Button>
                }
              >
                <CircleAlert size={16} />
                {listError}
              </Notice>
            ) : runs.length === 0 ? (
              <div {...stylex.props(s.message)}>
                No run has been started in this project yet.
              </div>
            ) : (
              runs.map((run) => (
                <RunRow
                  key={run.id}
                  run={run}
                  openGraphId={graphId}
                  starterNames={starterNames}
                />
              ))
            )}
          </div>
          {runs.length > 0 && listError ? (
            <div {...stylex.props(s.noticeWrap)}>
              <Notice tone="danger">{listError}</Notice>
            </div>
          ) : null}
        </section>
      </div>
    </aside>
  );
}

function RunRow({
  run,
  openGraphId,
  starterNames,
}: {
  run: Run;
  openGraphId: string | null | undefined;
  starterNames: ReadonlyMap<string, string>;
}) {
  const finished = runFinishLabel(run);
  return (
    <div role="listitem" {...stylex.props(s.listItem)}>
      <span {...stylex.props(s.listCopy)}>
        <span {...stylex.props(s.listTop)}>
          <span {...stylex.props(s.timestamp)}>{runStartLabel(run)}</span>
          <span {...stylex.props(s.status, statusStyle(run.status))}>
            {run.status}
          </span>
        </span>
        <span {...stylex.props(s.meta)}>
          {graphLabel(run.graph_id, openGraphId)} ·{" "}
          {runTargetsSummary(run.targets)}
        </span>
        <span {...stylex.props(s.meta)}>
          Started by {starterLabel(run, starterNames)}
          {finished ? ` · ended ${finished}` : ""}
        </span>
        {run.error ? (
          <span {...stylex.props(s.runError)}>{run.error}</span>
        ) : null}
        <span title="Run id" {...stylex.props(s.id)}>
          {run.id}
        </span>
      </span>
    </div>
  );
}
