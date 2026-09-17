"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import useSWR from "swr";
import { Collapsible } from "@base-ui/react/collapsible";
import { ScrollArea } from "@base-ui/react/scroll-area";
import {
  ChevronRight,
  CircleAlert,
  Layers,
  LoaderCircle,
  RefreshCw,
  X,
} from "lucide-react";

import {
  getGraphExecution,
  listGraphExecutions,
  listLibraryArtifacts,
  saveRunArtifactToLibrary,
  type ArtifactSummary,
  type GraphExecutionDetail,
  type GraphExecutionList,
  type GraphExecutionSummary,
  type LibraryList,
  type NodeRegistry,
} from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { artifactTypeColor } from "../canvas/nodes.css";
import { writeArtifactDrop } from "../model/artifact-drop";
import { BLOB_ARTIFACT_NOTICE, isBlobArtifact } from "../model/blob-notice";

const MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";
/**
 * How many recorded runs one canvas qualifies for. Each one shown under
 * `Previous runs` costs one detail request while that batch is open.
 */
const HISTORY_LIMIT = 10;

const s = stylex.create({
  drawer: {
    position: "absolute",
    zIndex: 10,
    top: {
      default: 0,
      "@media (max-width: 720px)":
        "calc(var(--grafy-mobile-overlay-top, 68px) + env(safe-area-inset-top, 0px))",
    },
    right: {
      default: 0,
      "@media (max-width: 720px)":
        "calc(12px + env(safe-area-inset-right, 0px))",
    },
    bottom: {
      default: 0,
      "@media (max-width: 720px)":
        "calc(12px + env(safe-area-inset-bottom, 0px))",
    },
    left: {
      default: "auto",
      "@media (max-width: 720px)":
        "calc(12px + env(safe-area-inset-left, 0px))",
    },
    width: {
      // The shell publishes this width while the drawer is open; the fallback
      // matches its GENERATED_DRAWER_WIDTH.
      default: "var(--grafy-generated-drawer-width, 320px)",
      "@media (max-width: 720px)": "auto",
    },
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
    borderWidth: { default: 0, "@media (max-width: 720px)": 1 },
    borderStyle: { default: "none", "@media (max-width: 720px)": "solid" },
    borderColor: tokens.colorBorder,
    borderRadius: { default: 0, "@media (max-width: 720px)": tokens.radiusLg },
    backgroundColor: tokens.colorChrome,
    boxShadow: {
      default: "none",
      "@media (max-width: 720px)": tokens.shadowNodeRaised,
    },
    color: tokens.colorText,
  },
  header: {
    minHeight: "44px",
    display: "flex",
    alignItems: "center",
    gap: "8px",
    flexShrink: 0,
    padding: "7px 8px 7px 10px",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorBorder,
  },
  headerIcon: {
    width: "26px",
    height: "26px",
    display: "grid",
    placeItems: "center",
    flexShrink: 0,
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorAccentSoft,
    color: tokens.colorAccent,
  },
  headerCopy: { minWidth: 0, flex: 1, display: "grid", gap: "1px" },
  title: {
    overflow: "hidden",
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeSm,
    fontWeight: 700,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  subtitle: {
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontSize: "10px",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  headerButton: {
    width: "28px",
    height: "28px",
    display: "grid",
    placeItems: "center",
    flexShrink: 0,
    borderWidth: 0,
    borderRadius: tokens.radiusMd,
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
  spinner: {
    animationName: "grafy-spin",
    animationDuration: "900ms",
    animationIterationCount: "infinite",
    animationTimingFunction: "linear",
  },
  notice: {
    display: "flex",
    alignItems: "flex-start",
    gap: "6px",
    flexShrink: 0,
    padding: "7px 10px",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorBorder,
    backgroundColor: tokens.colorDangerHover,
    color: tokens.colorDanger,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
  scrollRoot: { position: "relative", flex: 1, minHeight: 0, display: "flex" },
  scrollViewport: {
    width: "100%",
    height: "100%",
    overflowY: "auto",
    overscrollBehavior: "contain",
  },
  scrollContent: {
    display: "flex",
    flexDirection: "column",
    padding: "6px 8px 12px",
  },
  scrollbar: {
    position: "absolute",
    top: 0,
    right: "2px",
    bottom: 0,
    width: "8px",
    padding: "2px",
    display: "flex",
    justifyContent: "center",
  },
  scrollThumb: {
    width: "4px",
    height: "var(--scroll-area-thumb-height)",
    borderRadius: "9999px",
    backgroundColor: tokens.colorBorderStrong,
  },
  scrollCorner: { position: "absolute", right: 0, bottom: 0, width: "8px" },
  message: {
    display: "grid",
    placeItems: "center",
    alignContent: "center",
    gap: "7px",
    minHeight: "160px",
    padding: "22px 16px",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.5,
    textAlign: "center",
  },
  messageError: { color: tokens.colorDanger },
  retry: {
    height: "26px",
    paddingInline: "9px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorderStrong,
    borderRadius: tokens.radiusMd,
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: tokens.colorMuted,
    cursor: "pointer",
    fontSize: tokens.fontSizeXs,
    fontWeight: 700,
  },
  batch: { display: "grid", gap: "1px" },
  batchTrigger: {
    width: "100%",
    display: "flex",
    alignItems: "center",
    gap: "6px",
    padding: "6px 4px",
    borderWidth: 0,
    borderRadius: tokens.radiusSm,
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: tokens.colorText,
    cursor: "pointer",
    textAlign: "left",
  },
  batchTitle: {
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeXs,
    fontWeight: 700,
  },
  batchMeta: {
    marginInlineStart: "auto",
    flexShrink: 0,
    color: tokens.colorSubtle,
    fontFamily: MONO,
    fontSize: "10px",
    whiteSpace: "nowrap",
  },
  chevron: {
    flexShrink: 0,
    color: tokens.colorSubtle,
    transitionDuration: "120ms",
    transitionProperty: "transform",
    transform: {
      default: null,
      [stylex.when.ancestor("[data-panel-open]")]: "rotate(90deg)",
    },
  },
  batchPanel: { display: "grid", gap: "2px", paddingInlineStart: "6px" },
  groupTrigger: {
    width: "100%",
    display: "flex",
    alignItems: "center",
    gap: "6px",
    padding: "4px 4px",
    borderWidth: 0,
    borderRadius: tokens.radiusSm,
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: tokens.colorText,
    cursor: "pointer",
    textAlign: "left",
  },
  groupTitle: {
    minWidth: 0,
    overflow: "hidden",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    fontWeight: 650,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  groupPanel: {
    display: "grid",
    gap: "1px",
    paddingInlineStart: "14px",
    paddingBlockEnd: "2px",
  },
  groupMessage: {
    padding: "5px 4px 7px",
    color: tokens.colorSubtle,
    fontSize: "10px",
    lineHeight: 1.5,
  },
  row: {
    display: "grid",
    gridTemplateColumns: "3px minmax(0, 1fr) auto",
    alignItems: "center",
    columnGap: "7px",
    rowGap: "1px",
    padding: "5px 6px",
    borderRadius: tokens.radiusSm,
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    cursor: "grab",
  },
  swatch: {
    width: "3px",
    height: "100%",
    minHeight: "16px",
    gridRow: "1 / span 3",
    borderRadius: "9999px",
  },
  rowLabel: {
    minWidth: 0,
    overflow: "hidden",
    color: tokens.colorText,
    fontSize: tokens.fontSizeXs,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  rowActions: {
    gridColumn: "3",
    gridRow: 1,
    display: "flex",
    alignItems: "center",
    gap: "6px",
  },
  savedBadge: {
    flexShrink: 0,
    padding: "1px 6px",
    borderRadius: "9999px",
    backgroundColor: tokens.colorAccentSoft,
    color: tokens.colorAccent,
    fontSize: "9px",
    fontWeight: 700,
  },
  saveButton: {
    flexShrink: 0,
    height: "20px",
    paddingInline: "7px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusSm,
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorHoverStrong,
      ":disabled": "transparent",
    },
    color: {
      default: tokens.colorMuted,
      ":disabled": tokens.colorTextDisabled,
    },
    cursor: { default: "pointer", ":disabled": "not-allowed" },
    fontSize: "10px",
  },
  rowMeta: {
    gridColumn: "2 / span 2",
    minWidth: 0,
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontFamily: MONO,
    fontSize: "10px",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  rowNotice: {
    gridColumn: "2 / span 2",
    color: tokens.colorWarning,
    fontSize: "10px",
    lineHeight: 1.4,
  },
});

interface GeneratedRowArtifact {
  readonly artifact: ArtifactSummary;
  readonly executionId: string;
  readonly nodeId: string;
  readonly revision: number;
}

interface GeneratedRowGroup {
  readonly key: string;
  readonly nodeTitle: string;
  readonly time: string;
  readonly artifacts: readonly GeneratedRowArtifact[];
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

type GeneratedHistoryKey = readonly ["generated-runs", string, string];

async function loadGeneratedHistory([
  ,
  workspaceId,
  graphId,
]: GeneratedHistoryKey): Promise<GraphExecutionList> {
  return listGraphExecutions(workspaceId, graphId, { limit: HISTORY_LIMIT });
}

function timeLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function executionTimeLabel(execution: GraphExecutionSummary): string {
  return timeLabel(
    execution.finished_at ?? execution.started_at ?? execution.created_at,
  );
}

/**
 * The name this artifact carries in the Library: the artifact's own metadata
 * first, then the registry title, mirroring the server's `_artifact_name`.
 */
function artifactLabel(
  artifact: ArtifactSummary,
  registry: NodeRegistry | null,
): string {
  for (const key of ["download_name", "source_name"]) {
    const value = artifact.metadata?.[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return artifactTypeTitle(
    registry,
    artifact.artifact_type,
    artifact.schema_version,
  );
}

function artifactTypeTitle(
  registry: NodeRegistry | null,
  artifactType: string,
  schemaVersion: number,
): string {
  return (
    registry?.artifact_types.find(
      (candidate) =>
        candidate.key.id === artifactType &&
        candidate.key.schema_version === schemaVersion,
    )?.title ?? `${artifactType}@${schemaVersion}`
  );
}

/**
 * One node's artifacts inside one run. A run records its own revision, so every
 * row in the group names the revision the artifact came from.
 */
function nodeGroups(
  detail: GraphExecutionDetail,
  nodeTitles: Readonly<Record<string, string>>,
): GeneratedRowGroup[] {
  const groups: GeneratedRowGroup[] = [];
  for (const result of detail.node_results.toSorted(
    (left, right) => left.position - right.position,
  )) {
    const seen = new Set<string>();
    const artifacts: GeneratedRowArtifact[] = [];
    for (const output of result.outputs) {
      for (const artifact of output.artifacts) {
        if (seen.has(artifact.artifact_id)) continue;
        seen.add(artifact.artifact_id);
        artifacts.push({
          artifact,
          executionId: detail.execution_id,
          nodeId: result.node_id,
          revision: detail.graph_revision,
        });
      }
    }
    if (!artifacts.length) continue;
    groups.push({
      key: `${detail.execution_id}:${result.node_id}`,
      nodeTitle: nodeTitles[result.node_id] ?? result.node_id,
      time: timeLabel(result.completed_at),
      artifacts,
    });
  }
  return groups;
}

function ArtifactRow({
  artifact,
  registry,
  saved,
  saving,
  canSave,
  onSave,
}: {
  artifact: GeneratedRowArtifact;
  registry: NodeRegistry | null;
  saved: boolean;
  saving: boolean;
  canSave: boolean;
  onSave: (artifact: GeneratedRowArtifact) => void;
}) {
  const label = artifactLabel(artifact.artifact, registry);

  return (
    <div
      draggable
      data-artifact-row={artifact.artifact.artifact_id}
      onDragStart={(event) => {
        writeArtifactDrop(event.dataTransfer, {
          artifact_id: artifact.artifact.artifact_id,
          artifact_type: artifact.artifact.artifact_type,
          schema_version: artifact.artifact.schema_version,
          content_hash: artifact.artifact.sha256 ?? null,
        });
      }}
      {...stylex.props(s.row)}
    >
      <span
        aria-hidden="true"
        {...stylex.props(s.swatch)}
        style={{
          backgroundColor: artifactTypeColor(
            artifact.artifact.artifact_type,
            tokens.colorAccent,
          ),
        }}
      />
      <span {...stylex.props(s.rowLabel)}>{label}</span>
      <span {...stylex.props(s.rowActions)}>
        {saved ? <span {...stylex.props(s.savedBadge)}>saved</span> : null}
        <button
          type="button"
          disabled={saving || !canSave}
          title={
            canSave
              ? `Save ${label} into the Library`
              : "Saving into the Library needs edit access"
          }
          {...stylex.props(s.saveButton)}
          onClick={() => onSave(artifact)}
        >
          {saving ? "Saving…" : "Save"}
        </button>
      </span>
      <span {...stylex.props(s.rowMeta)}>
        {artifact.artifact.artifact_type}@{artifact.artifact.schema_version} ·
        rev {artifact.revision}
      </span>
      {isBlobArtifact(artifact.artifact) ? (
        <span role="status" {...stylex.props(s.rowNotice)}>
          {BLOB_ARTIFACT_NOTICE}
        </span>
      ) : null}
    </div>
  );
}

function NodeGroup({
  group,
  registry,
  savedArtifactIds,
  savingArtifactId,
  canSave,
  onSave,
}: {
  group: GeneratedRowGroup;
  registry: NodeRegistry | null;
  savedArtifactIds: ReadonlySet<string>;
  savingArtifactId: string | null;
  canSave: boolean;
  onSave: (artifact: GeneratedRowArtifact) => void;
}) {
  return (
    <Collapsible.Root defaultOpen {...stylex.props(s.batch)}>
      <Collapsible.Trigger {...stylex.props(s.groupTrigger)}>
        <ChevronRight size={12} aria-hidden {...stylex.props(s.chevron)} />
        <span {...stylex.props(s.groupTitle)}>{group.nodeTitle}</span>
        <span {...stylex.props(s.batchMeta)}>{group.time}</span>
      </Collapsible.Trigger>
      <Collapsible.Panel {...stylex.props(s.groupPanel)}>
        {group.artifacts.map((artifact) => (
          <ArtifactRow
            key={artifact.artifact.artifact_id}
            artifact={artifact}
            registry={registry}
            saved={savedArtifactIds.has(artifact.artifact.artifact_id)}
            saving={savingArtifactId === artifact.artifact.artifact_id}
            canSave={canSave}
            onSave={onSave}
          />
        ))}
      </Collapsible.Panel>
    </Collapsible.Root>
  );
}

/** The node groups of one recorded run. Mounted only while its batch is open. */
function RunNodeGroups({
  workspaceId,
  graphId,
  executionId,
  nodeTitles,
  registry,
  savedArtifactIds,
  savingArtifactId,
  canSave,
  onSave,
}: {
  workspaceId: string;
  graphId: string;
  executionId: string;
  nodeTitles: Readonly<Record<string, string>>;
  registry: NodeRegistry | null;
  savedArtifactIds: ReadonlySet<string>;
  savingArtifactId: string | null;
  canSave: boolean;
  onSave: (artifact: GeneratedRowArtifact) => void;
}) {
  const { data, error, isLoading } = useSWR<
    GraphExecutionDetail,
    Error,
    ExecutionDetailKey
  >(
    ["graph-execution-detail", workspaceId, graphId, executionId],
    loadExecutionDetail,
  );

  if (isLoading) {
    return (
      <p {...stylex.props(s.groupMessage)}>
        <LoaderCircle size={11} aria-hidden /> Loading this run…
      </p>
    );
  }
  if (error || !data) {
    return (
      <p role="alert" {...stylex.props(s.groupMessage, s.messageError)}>
        {error instanceof Error ? error.message : "Could not load this run."}
      </p>
    );
  }
  const groups = nodeGroups(data, nodeTitles);
  if (!groups.length) {
    return (
      <p {...stylex.props(s.groupMessage)}>This run recorded no outputs.</p>
    );
  }
  return (
    <>
      {groups.map((group) => (
        <NodeGroup
          key={group.key}
          group={group}
          registry={registry}
          savedArtifactIds={savedArtifactIds}
          savingArtifactId={savingArtifactId}
          canSave={canSave}
          onSave={onSave}
        />
      ))}
    </>
  );
}

export interface GeneratedDrawerProps {
  workspaceId: string;
  /** Null while the canvas is unsaved, so there is no recorded run to read. */
  graphId: string | null;
  nodeTitles: Readonly<Record<string, string>>;
  registry: NodeRegistry | null;
  /** The Library save endpoint needs edit access, so a viewer reads Runs only. */
  canSave: boolean;
  /** A finished run adds a recorded execution, so the newest batch re-reads. */
  executionRunning: boolean;
  onClose: () => void;
}

/**
 * The Runs drawer: Run artifacts of one canvas, newest first, grouped by run
 * and then by the node that produced them. Rows drag onto ports with the same
 * payload as Library rows, and Save promotes the exact artifact reference into
 * the Library, leaving the row here.
 */
export function GeneratedDrawer({
  workspaceId,
  graphId,
  nodeTitles,
  registry,
  canSave,
  executionRunning,
  onClose,
}: GeneratedDrawerProps) {
  const historyKey: GeneratedHistoryKey | null = graphId
    ? ["generated-runs", workspaceId, graphId]
    : null;
  const {
    data: history,
    error: historyError,
    isLoading,
    isValidating,
    mutate: refreshHistory,
  } = useSWR<GraphExecutionList, Error, GeneratedHistoryKey | null>(
    historyKey,
    loadGeneratedHistory,
  );
  const { data: library, mutate: refreshLibrary } = useSWR<
    LibraryList,
    Error,
    [string, string] | null
  >(graphId ? ["library-artifacts", workspaceId] : null, () =>
    listLibraryArtifacts(workspaceId),
  );
  const [savingArtifactId, setSavingArtifactId] = React.useState<string | null>(
    null,
  );
  const [saveError, setSaveError] = React.useState<string | null>(null);

  const previousRunningRef = React.useRef(executionRunning);
  React.useEffect(() => {
    const runCompleted = previousRunningRef.current && !executionRunning;
    previousRunningRef.current = executionRunning;
    if (runCompleted) void refreshHistory();
  }, [executionRunning, refreshHistory]);

  const executions = history?.items ?? [];
  const latest = executions[0] ?? null;
  const previous = executions.slice(1);
  const savedArtifactIds = React.useMemo(
    () =>
      new Set((library?.items ?? []).map((item) => item.artifact.artifact_id)),
    [library],
  );

  const saveArtifact = React.useCallback(
    async (artifact: GeneratedRowArtifact) => {
      const artifactId = artifact.artifact.artifact_id;
      setSavingArtifactId(artifactId);
      setSaveError(null);
      try {
        await saveRunArtifactToLibrary(workspaceId, {
          artifact_id: artifactId,
          execution_id: artifact.executionId,
          node_id: artifact.nodeId,
          node_title: nodeTitles[artifact.nodeId] ?? artifact.nodeId,
        });
        await refreshLibrary();
      } catch (error) {
        setSaveError(
          error instanceof Error
            ? error.message
            : "Could not save this Run artifact into the Library.",
        );
      } finally {
        setSavingArtifactId(null);
      }
    },
    [nodeTitles, refreshLibrary, workspaceId],
  );

  const refresh = () => {
    void refreshHistory();
    // No canvas means no rows, so the Library was never read for this drawer.
    if (graphId) void refreshLibrary();
  };

  return (
    <aside aria-label="Generated" {...stylex.props(s.drawer)}>
      <header {...stylex.props(s.header)}>
        <span aria-hidden="true" {...stylex.props(s.headerIcon)}>
          <Layers size={14} />
        </span>
        <span {...stylex.props(s.headerCopy)}>
          <span {...stylex.props(s.title)}>Generated</span>
          <span {...stylex.props(s.subtitle)}>
            Run artifacts of this canvas, newest first
          </span>
        </span>
        <button
          type="button"
          aria-label="Refresh Run artifacts"
          title="Refresh Run artifacts"
          disabled={!graphId || isValidating}
          onClick={refresh}
          {...stylex.props(s.headerButton)}
        >
          <RefreshCw
            size={13}
            aria-hidden
            {...stylex.props(isValidating ? s.spinner : null)}
          />
        </button>
        <button
          type="button"
          aria-label="Close Generated"
          title="Close Generated"
          onClick={onClose}
          {...stylex.props(s.headerButton)}
        >
          <X size={14} aria-hidden />
        </button>
      </header>

      {saveError ? (
        <p role="alert" {...stylex.props(s.notice)}>
          <CircleAlert size={13} aria-hidden />
          {saveError}
        </p>
      ) : null}

      <ScrollArea.Root {...stylex.props(s.scrollRoot)}>
        <ScrollArea.Viewport {...stylex.props(s.scrollViewport)}>
          <ScrollArea.Content {...stylex.props(s.scrollContent)}>
            {!graphId ? (
              <p {...stylex.props(s.message)}>
                Save this graph before browsing the Run artifacts of this
                canvas. A run of an unsaved graph is not recorded.
              </p>
            ) : isLoading ? (
              <p role="status" {...stylex.props(s.message)}>
                <LoaderCircle
                  size={15}
                  aria-hidden
                  {...stylex.props(s.spinner)}
                />
                Loading runs…
              </p>
            ) : historyError ? (
              <p role="alert" {...stylex.props(s.message, s.messageError)}>
                <CircleAlert size={15} aria-hidden />
                {historyError.message}
                <button
                  type="button"
                  {...stylex.props(s.retry)}
                  onClick={() => void refreshHistory()}
                >
                  Try again
                </button>
              </p>
            ) : !latest ? (
              <p {...stylex.props(s.message)}>
                No run of this canvas is recorded yet. Run the graph to record
                the artifacts it makes.
              </p>
            ) : (
              <>
                <Collapsible.Root defaultOpen {...stylex.props(s.batch)}>
                  <Collapsible.Trigger {...stylex.props(s.batchTrigger)}>
                    <ChevronRight
                      size={13}
                      aria-hidden
                      {...stylex.props(s.chevron)}
                    />
                    <span {...stylex.props(s.batchTitle)}>Latest run</span>
                    <span {...stylex.props(s.batchMeta)}>
                      {executionTimeLabel(latest)} · rev {latest.graph_revision}
                    </span>
                  </Collapsible.Trigger>
                  <Collapsible.Panel {...stylex.props(s.batchPanel)}>
                    <RunNodeGroups
                      workspaceId={workspaceId}
                      graphId={graphId}
                      executionId={latest.execution_id}
                      nodeTitles={nodeTitles}
                      registry={registry}
                      savedArtifactIds={savedArtifactIds}
                      savingArtifactId={savingArtifactId}
                      canSave={canSave}
                      onSave={saveArtifact}
                    />
                  </Collapsible.Panel>
                </Collapsible.Root>

                {previous.length ? (
                  <Collapsible.Root {...stylex.props(s.batch)}>
                    <Collapsible.Trigger {...stylex.props(s.batchTrigger)}>
                      <ChevronRight
                        size={13}
                        aria-hidden
                        {...stylex.props(s.chevron)}
                      />
                      <span {...stylex.props(s.batchTitle)}>Previous runs</span>
                      <span {...stylex.props(s.batchMeta)}>
                        {previous.length} run{previous.length === 1 ? "" : "s"}
                      </span>
                    </Collapsible.Trigger>
                    <Collapsible.Panel {...stylex.props(s.batchPanel)}>
                      {previous.map((execution) => (
                        <RunNodeGroups
                          key={execution.execution_id}
                          workspaceId={workspaceId}
                          graphId={graphId}
                          executionId={execution.execution_id}
                          nodeTitles={nodeTitles}
                          registry={registry}
                          savedArtifactIds={savedArtifactIds}
                          savingArtifactId={savingArtifactId}
                          canSave={canSave}
                          onSave={saveArtifact}
                        />
                      ))}
                    </Collapsible.Panel>
                  </Collapsible.Root>
                ) : null}
              </>
            )}
          </ScrollArea.Content>
        </ScrollArea.Viewport>
        <ScrollArea.Scrollbar
          orientation="vertical"
          {...stylex.props(s.scrollbar)}
        >
          <ScrollArea.Thumb {...stylex.props(s.scrollThumb)} />
        </ScrollArea.Scrollbar>
        <ScrollArea.Corner {...stylex.props(s.scrollCorner)} />
      </ScrollArea.Root>
    </aside>
  );
}
