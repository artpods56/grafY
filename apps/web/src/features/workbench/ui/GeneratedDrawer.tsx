"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import useSWR from "swr";
import { Collapsible } from "@base-ui/react/collapsible";
import { ScrollArea } from "@base-ui/react/scroll-area";
import {
  ChevronRight,
  CircleAlert,
  LoaderCircle,
  RefreshCw,
  X,
} from "lucide-react";

import {
  getInstanceResult,
  listGraphInstances,
  listLibraryArtifacts,
  saveInstanceArtifactToLibrary,
  type ArtifactOutputValue,
  type InstanceResult,
  type InstanceStateList,
  type InstanceStateName,
  type LibraryList,
  type NodeRegistry,
} from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { artifactTypeKey } from "../canvas/artifact-type-key";
import { formatArtifactTypeLabel } from "../canvas/artifact-type-label";
import { artifactTypeColor } from "../canvas/nodes.css";
import { writeArtifactDrop } from "../model/artifact-drop";
import { BLOB_ARTIFACT_NOTICE, isBlobArtifact } from "../model/blob-notice";

const MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";

const s = stylex.create({
  drawer: {
    position: "relative",
    flex: 1,
    minHeight: 0,
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
    backgroundColor: tokens.colorBg,
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
  /**
   * A failed read whose result is still on screen. Warning, not danger: nothing
   * was lost, this line only says how old what is left is.
   */
  stale: {
    display: "flex",
    alignItems: "flex-start",
    flexWrap: "wrap",
    gap: "4px 6px",
    flexShrink: 0,
    padding: "6px 10px",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorBorder,
    color: tokens.colorWarning,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
  staleInline: {
    display: "flex",
    alignItems: "flex-start",
    flexWrap: "wrap",
    gap: "3px 6px",
    padding: "4px 4px 5px",
    color: tokens.colorWarning,
    fontSize: "10px",
    lineHeight: 1.45,
  },
  staleText: { minWidth: 0, flex: 1 },
  staleIcon: { flexShrink: 0, marginTop: "2px" },
  staleRetry: { flexShrink: 0, marginInlineStart: "auto" },
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
    color: tokens.colorText,
    fontSize: tokens.fontSizeXs,
    fontWeight: 650,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  groupVia: {
    minWidth: 0,
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontSize: "10px",
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
  groupHint: {
    padding: "4px 4px 2px",
    color: tokens.colorSubtle,
    fontSize: "10px",
    lineHeight: 1.45,
  },
  groupNotice: {
    display: "flex",
    alignItems: "flex-start",
    gap: "5px",
    padding: "4px 4px 6px",
    color: tokens.colorWarning,
    fontSize: "10px",
    lineHeight: 1.45,
  },
  groupMeta: {
    padding: "4px 4px 5px",
    color: tokens.colorSubtle,
    fontFamily: MONO,
    fontSize: "10px",
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
  stateBadge: {
    flexShrink: 0,
    padding: "1px 6px",
    borderRadius: "9999px",
    fontSize: "9px",
    fontWeight: 700,
    whiteSpace: "nowrap",
  },
  /** The instance is up to date: what is stored is what the node computes now. */
  stateFresh: {
    backgroundColor: tokens.colorAccentSoft,
    color: tokens.colorAccent,
  },
  /** A stored result the document has moved past: shown, but not current. */
  stateStale: {
    backgroundColor: tokens.colorHover,
    color: tokens.colorWarning,
  },
  stateActive: { backgroundColor: tokens.colorHover, color: tokens.colorMuted },
  stateFailed: {
    backgroundColor: tokens.colorDangerHover,
    color: tokens.colorDanger,
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

/**
 * One stored artifact of a node instance. A stored result carries references,
 * so a row holds identity only: the bytes stay behind the artifact routes.
 */
interface GeneratedRow {
  readonly artifactId: string;
  readonly artifactType: string;
  readonly schemaVersion: number;
  readonly contentHash: string | null;
  /** The output port the artifact was handed back on: the Library save names it. */
  readonly outputPort: string;
  /** Its place in a sequence output, `null` for a single artifact. */
  readonly itemIndex: number | null;
}

/**
 * One node instance with something stored. The instance is the address — Graph,
 * node and call path — and `state` says whether what it shows is current.
 */
interface GeneratedGroup {
  readonly key: string;
  /** The Graph the instance belongs to: a callee for an instance reached by call. */
  readonly graphId: string;
  readonly nodeId: string;
  readonly callPath: readonly string[];
  readonly nodeTitle: string;
  /** The call nodes that reach this instance, when it is not in the open Graph. */
  readonly callPathLabel: string | null;
  readonly state: InstanceStateName;
  readonly fingerprint: string;
  readonly resultFingerprint: string;
  readonly mapIndex: number | null;
  readonly error: string | null;
}

type InstanceListKey = readonly ["graph-instances", string, string, string];

async function loadInstances([
  ,
  workspaceId,
  projectId,
  graphId,
]: InstanceListKey): Promise<InstanceStateList> {
  return listGraphInstances(workspaceId, projectId, graphId);
}

type InstanceResultKey = readonly [
  "instance-result",
  string,
  string,
  string,
  string,
  readonly string[],
];

async function loadInstanceResult([
  ,
  workspaceId,
  projectId,
  graphId,
  nodeId,
  callPath,
]: InstanceResultKey): Promise<InstanceResult> {
  return getInstanceResult(workspaceId, projectId, {
    graph_id: graphId,
    node_id: nodeId,
    call_path: callPath,
  });
}

function timeLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

const STATE_LABELS: Readonly<Record<InstanceStateName, string>> = {
  fresh: "Fresh",
  stale: "Stale",
  queued: "Queued",
  running: "Running",
  failed: "Failed",
};

const STATE_TITLES: Readonly<Record<InstanceStateName, string>> = {
  fresh: "Fresh: this is what the node computes now.",
  stale: "Stale: the node changed after this result was stored.",
  queued: "Queued: a Run is waiting to compute this node.",
  running: "Running: a Run is computing this node.",
  failed: "Failed: the last attempt at the node's current state failed.",
};

function stateLabel(state: InstanceStateName): string {
  return STATE_LABELS[state] ?? state;
}

function stateTitle(state: InstanceStateName): string {
  return STATE_TITLES[state] ?? state;
}

/**
 * The call path of an instance as a person reads it: the call nodes that reach
 * it, by title, outermost first.
 */
function callPathLabel(
  callPath: readonly string[],
  nodeTitles: Readonly<Record<string, string>>,
): string | null {
  if (!callPath.length) return null;
  return `via ${callPath.map((id) => nodeTitles[id] ?? id).join(" / ")}`;
}

/**
 * The instances of one Graph that have something to show, in the order the
 * Graph's own expansion walks them. An instance without a stored result is a
 * demand nobody satisfied yet, so it is not an entry here.
 */
function instanceGroups(
  list: InstanceStateList,
  nodeTitles: Readonly<Record<string, string>>,
): GeneratedGroup[] {
  const groups: GeneratedGroup[] = [];
  for (const instance of list.instances) {
    const resultFingerprint = instance.last_result_fingerprint;
    if (!resultFingerprint) continue;
    const { graph_id, node_id, call_path, map_index } = instance.key;
    const path = call_path ?? [];
    groups.push({
      key: `${graph_id}:${path.join(">")}:${node_id}:${map_index ?? ""}`,
      graphId: graph_id,
      nodeId: node_id,
      callPath: path,
      nodeTitle: nodeTitles[node_id] ?? node_id,
      callPathLabel: callPathLabel(path, nodeTitles),
      state: instance.state,
      fingerprint: instance.fingerprint,
      resultFingerprint,
      mapIndex: map_index ?? null,
      error: instance.error,
    });
  }
  return groups;
}

/** Every artifact a stored output hands back, single or in a sequence. */
function outputRefs(value: ArtifactOutputValue): {
  artifactId: string;
  artifactType: string;
  schemaVersion: number;
  contentHash: string | null;
  itemIndex: number | null;
}[] {
  if ("item_refs" in value) {
    return value.item_refs.map((ref, index) => ({
      artifactId: ref.artifact_id,
      artifactType: ref.artifact_type,
      schemaVersion: ref.schema_version,
      contentHash: ref.content_hash ?? null,
      itemIndex: index,
    }));
  }
  return [
    {
      artifactId: value.artifact_id,
      artifactType: value.artifact_type,
      schemaVersion: value.schema_version,
      contentHash: value.content_hash ?? null,
      itemIndex: null,
    },
  ];
}

/**
 * The rows of one stored result: one per artifact, across every output port.
 * An artifact handed back on two ports is one row, on the first port that
 * carries it, because a row is a thing to drag and to file, not a port listing.
 */
function resultRows(result: InstanceResult): GeneratedRow[] {
  const outputs = result.outputs;
  if (!outputs) return [];
  const rows: GeneratedRow[] = [];
  const seen = new Set<string>();
  for (const [port, value] of Object.entries(outputs)) {
    for (const ref of outputRefs(value)) {
      if (seen.has(ref.artifactId)) continue;
      seen.add(ref.artifactId);
      rows.push({
        artifactId: ref.artifactId,
        artifactType: ref.artifactType,
        schemaVersion: ref.schemaVersion,
        contentHash: ref.contentHash,
        outputPort: port,
        itemIndex: ref.itemIndex,
      });
    }
  }
  return rows;
}

/** What a row is called: the catalog's name for its type. */
function rowLabel(row: GeneratedRow, registry: NodeRegistry | null): string {
  return formatArtifactTypeLabel(
    { id: row.artifactType, schema_version: row.schemaVersion },
    registry?.artifact_types ?? null,
  );
}

/** `tables`, or `tables[2]` for one item of a sequence output. */
function portLabel(row: GeneratedRow): string {
  return row.itemIndex === null
    ? row.outputPort
    : `${row.outputPort}[${row.itemIndex}]`;
}

/**
 * A read that failed while its result was already on screen. The content stays;
 * this line names the read those rows came from and asks for the failed one
 * again. `inline` sits inside an open group instead of under the header.
 */
function RefreshFailure({
  reason,
  onRetry,
  pending,
  inline = false,
}: {
  readonly reason: string;
  readonly onRetry: () => void;
  readonly pending: boolean;
  readonly inline?: boolean;
}) {
  return (
    <p role="alert" {...stylex.props(inline ? s.staleInline : s.stale)}>
      <CircleAlert
        size={inline ? 11 : 13}
        aria-hidden
        {...stylex.props(s.staleIcon)}
      />
      <span {...stylex.props(s.staleText)}>{reason}</span>
      <button
        type="button"
        disabled={pending}
        onClick={onRetry}
        {...stylex.props(s.retry, s.staleRetry)}
      >
        {pending ? "Retrying…" : "Try again"}
      </button>
    </p>
  );
}

function ArtifactRow({
  row,
  registry,
  saved,
  saving,
  canSave,
  onSave,
}: {
  row: GeneratedRow;
  registry: NodeRegistry | null;
  saved: boolean;
  saving: boolean;
  canSave: boolean;
  onSave: (row: GeneratedRow, name: string) => void;
}) {
  const label = rowLabel(row, registry);

  return (
    <div
      draggable
      data-artifact-row={row.artifactId}
      onDragStart={(event) => {
        writeArtifactDrop(event.dataTransfer, {
          artifact_id: row.artifactId,
          artifact_type: row.artifactType,
          schema_version: row.schemaVersion,
          content_hash: row.contentHash,
        });
      }}
      {...stylex.props(s.row)}
    >
      <span
        aria-hidden="true"
        {...stylex.props(s.swatch)}
        style={{
          backgroundColor: artifactTypeColor(
            row.artifactType,
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
          onClick={() => {
            const name = window.prompt(`Save ${label} into the Library`, label);
            if (name !== null) onSave(row, name);
          }}
        >
          {saving ? "Saving…" : "Save"}
        </button>
      </span>
      <span {...stylex.props(s.rowMeta)}>
        {portLabel(row)} ·{" "}
        {artifactTypeKey({
          id: row.artifactType,
          schema_version: row.schemaVersion,
        })}
      </span>
      {isBlobArtifact({
        artifact_type: row.artifactType,
        schema_version: row.schemaVersion,
      }) ? (
        <span role="status" {...stylex.props(s.rowNotice)}>
          {BLOB_ARTIFACT_NOTICE}
        </span>
      ) : null}
    </div>
  );
}

/**
 * What one instance last stored. Mounted only while its group is open: a group
 * closed again costs no read, and the read is addressed by the instance, not by
 * the Run that happened to ask for it.
 */
function InstanceOutputs({
  workspaceId,
  projectId,
  group,
  registry,
  savedArtifactIds,
  savingArtifactId,
  canSave,
  onSave,
}: {
  workspaceId: string;
  projectId: string;
  group: GeneratedGroup;
  registry: NodeRegistry | null;
  savedArtifactIds: ReadonlySet<string>;
  savingArtifactId: string | null;
  canSave: boolean;
  onSave: (group: GeneratedGroup, row: GeneratedRow, name: string) => void;
}) {
  const {
    data,
    error,
    isLoading,
    isValidating,
    mutate: reloadResult,
  } = useSWR<InstanceResult, Error, InstanceResultKey>(
    [
      "instance-result",
      workspaceId,
      projectId,
      group.graphId,
      group.nodeId,
      group.callPath,
    ],
    loadInstanceResult,
    // Re-reading this instance, or reading the result a Run just stored, must
    // not blank the rows an earlier read already put on screen.
    { keepPreviousData: true },
  );

  if (isLoading) {
    return (
      <p {...stylex.props(s.groupMessage)}>
        <LoaderCircle size={11} aria-hidden /> Reading this result…
      </p>
    );
  }
  if (data) {
    const rows = resultRows(data);
    return (
      <>
        {error ? (
          <RefreshFailure
            inline
            pending={isValidating}
            onRetry={() => void reloadResult()}
            reason={`Showing this result from the last successful read. Refresh failed: ${error.message}`}
          />
        ) : null}
        {data.created_at ? (
          <p {...stylex.props(s.groupMeta)}>
            stored {timeLabel(data.created_at)}
          </p>
        ) : null}
        {rows.length ? (
          rows.map((row) => (
            <ArtifactRow
              key={row.artifactId}
              row={row}
              registry={registry}
              saved={savedArtifactIds.has(row.artifactId)}
              saving={savingArtifactId === row.artifactId}
              canSave={canSave}
              onSave={(row, name) => onSave(group, row, name)}
            />
          ))
        ) : (
          <p {...stylex.props(s.groupMessage)}>
            This result handed back no artifacts.
          </p>
        )}
      </>
    );
  }
  // Nothing was ever read for this instance, so there is nothing here to keep.
  return (
    <RefreshFailure
      inline
      pending={isValidating}
      onRetry={() => void reloadResult()}
      reason={error ? error.message : "Could not read this result."}
    />
  );
}

/** One node instance: its title, whether its result is current, and the rows. */
function InstanceGroup({
  workspaceId,
  projectId,
  group,
  open,
  registry,
  savedArtifactIds,
  savingArtifactId,
  canSave,
  onSave,
}: {
  workspaceId: string;
  projectId: string;
  group: GeneratedGroup;
  open: boolean;
  registry: NodeRegistry | null;
  savedArtifactIds: ReadonlySet<string>;
  savingArtifactId: string | null;
  canSave: boolean;
  onSave: (group: GeneratedGroup, row: GeneratedRow, name: string) => void;
}) {
  return (
    <Collapsible.Root defaultOpen={open} {...stylex.props(s.batch)}>
      <Collapsible.Trigger {...stylex.props(s.groupTrigger)}>
        <ChevronRight size={12} aria-hidden {...stylex.props(s.chevron)} />
        <span {...stylex.props(s.groupTitle)}>{group.nodeTitle}</span>
        {group.callPathLabel ? (
          <span {...stylex.props(s.groupVia)}>{group.callPathLabel}</span>
        ) : null}
        <span
          title={stateTitle(group.state)}
          {...stylex.props(
            s.stateBadge,
            group.state === "fresh"
              ? s.stateFresh
              : group.state === "stale"
                ? s.stateStale
                : group.state === "failed"
                  ? s.stateFailed
                  : s.stateActive,
          )}
        >
          {stateLabel(group.state)}
        </span>
      </Collapsible.Trigger>
      <Collapsible.Panel {...stylex.props(s.groupPanel)}>
        {group.state === "stale" ? (
          <p {...stylex.props(s.groupHint)}>
            The node changed after this result was stored. Run the Graph to
            store a fresh one.
          </p>
        ) : null}
        {group.error ? (
          <p role="status" {...stylex.props(s.groupNotice)}>
            <CircleAlert size={11} aria-hidden {...stylex.props(s.staleIcon)} />
            <span {...stylex.props(s.staleText)}>{group.error}</span>
          </p>
        ) : null}
        <InstanceOutputs
          workspaceId={workspaceId}
          projectId={projectId}
          group={group}
          registry={registry}
          savedArtifactIds={savedArtifactIds}
          savingArtifactId={savingArtifactId}
          canSave={canSave}
          onSave={onSave}
        />
      </Collapsible.Panel>
    </Collapsible.Root>
  );
}

export interface GeneratedDrawerProps {
  workspaceId: string;
  /** The Project that holds the open Graph: results are addressed under it. */
  projectId: string;
  /** The open Graph, or null while the canvas has no Graph to read results of. */
  graphId: string | null;
  nodeTitles: Readonly<Record<string, string>>;
  registry: NodeRegistry | null;
  /** The Library save endpoint needs edit access, so a viewer reads only. */
  canSave: boolean;
  /**
   * Bumped by the shell when a stored result may have changed — a Run finished,
   * or the room reported an instance state change. Each change re-reads the
   * Graph's instances.
   */
  refreshToken?: number;
  /** The panel's own close control, placed at the end of the header row. */
  onClose?: () => void;
}

/**
 * The Generated panel: the results this Graph's node instances store, by node.
 *
 * A result belongs to the instance that produced it — Graph, node and call —
 * so nothing here is keyed by a Run or by a revision. The state beside each
 * node says whether what it shows is what the node computes now. Rows drag onto
 * ports with the same payload as Library rows, and Save files the exact result
 * the row came from into the Library, leaving the row here.
 */
export function GeneratedDrawer({
  workspaceId,
  projectId,
  graphId,
  nodeTitles,
  registry,
  canSave,
  refreshToken = 0,
  onClose,
}: GeneratedDrawerProps) {
  const instancesKey: InstanceListKey | null = graphId
    ? ["graph-instances", workspaceId, projectId, graphId]
    : null;
  const {
    data: instances,
    error: instancesError,
    isLoading,
    isValidating,
    mutate: refreshInstances,
  } = useSWR<InstanceStateList, Error, InstanceListKey | null>(
    instancesKey,
    loadInstances,
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

  const refresh = React.useCallback(() => {
    void refreshInstances();
    // No Graph means no rows, so the Library was never read for this drawer.
    if (graphId) void refreshLibrary();
  }, [graphId, refreshInstances, refreshLibrary]);

  const previousTokenRef = React.useRef(refreshToken);
  React.useEffect(() => {
    const resultMayHaveChanged = previousTokenRef.current !== refreshToken;
    previousTokenRef.current = refreshToken;
    if (resultMayHaveChanged) refresh();
  }, [refreshToken, refresh]);

  const groups = React.useMemo(
    () => (instances ? instanceGroups(instances, nodeTitles) : []),
    [instances, nodeTitles],
  );
  /** A failed refresh still has the list the last good read returned. */
  const instancesLoaded = instances !== undefined;
  const savedArtifactIds = React.useMemo(
    () =>
      new Set((library?.items ?? []).map((item) => item.artifact.artifact_id)),
    [library],
  );

  const saveArtifact = React.useCallback(
    async (group: GeneratedGroup, row: GeneratedRow, requestedName: string) => {
      const name = requestedName.trim();
      if (!name || name.length > 160) {
        setSaveError("Library names must be between 1 and 160 characters.");
        return;
      }
      setSavingArtifactId(row.artifactId);
      setSaveError(null);
      try {
        await saveInstanceArtifactToLibrary(workspaceId, {
          project_id: projectId,
          graph_id: group.graphId,
          node_id: group.nodeId,
          output_port: row.outputPort,
          name,
          result_fingerprint: group.resultFingerprint,
          call_path: group.callPath,
          ...(row.itemIndex === null ? {} : { item_index: row.itemIndex }),
          ...(group.mapIndex === null ? {} : { map_index: group.mapIndex }),
        });
        await refreshLibrary();
      } catch (error) {
        setSaveError(
          error instanceof Error
            ? error.message
            : "Could not save this result into the Library.",
        );
      } finally {
        setSavingArtifactId(null);
      }
    },
    [projectId, refreshLibrary, workspaceId],
  );

  return (
    <section aria-label="Generated artifacts" {...stylex.props(s.drawer)}>
      <header {...stylex.props(s.header)}>
        <span {...stylex.props(s.headerCopy)}>
          <span {...stylex.props(s.title)}>Generated</span>
          <span {...stylex.props(s.subtitle)}>
            Results this Graph stores, by node
          </span>
        </span>
        <button
          type="button"
          aria-label="Refresh Generated artifacts"
          title="Refresh Generated artifacts"
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
        {onClose ? (
          <button
            type="button"
            aria-label="Close Generated artifacts"
            title="Close Generated artifacts"
            onClick={onClose}
            {...stylex.props(s.headerButton)}
          >
            <X size={14} aria-hidden />
          </button>
        ) : null}
      </header>

      {saveError ? (
        <p role="alert" {...stylex.props(s.notice)}>
          <CircleAlert size={13} aria-hidden />
          {saveError}
        </p>
      ) : null}

      {instancesError && instancesLoaded ? (
        <RefreshFailure
          pending={isValidating}
          onRetry={() => void refreshInstances()}
          reason={`Showing the results from the last successful read. Refresh failed: ${instancesError.message}`}
        />
      ) : null}

      <ScrollArea.Root {...stylex.props(s.scrollRoot)}>
        <ScrollArea.Viewport {...stylex.props(s.scrollViewport)}>
          <ScrollArea.Content {...stylex.props(s.scrollContent)}>
            {!graphId ? (
              <p {...stylex.props(s.message)}>
                Open a Graph to browse the results it stores. A result belongs
                to the node that produced it, inside one Project.
              </p>
            ) : isLoading ? (
              <p role="status" {...stylex.props(s.message)}>
                <LoaderCircle
                  size={15}
                  aria-hidden
                  {...stylex.props(s.spinner)}
                />
                Reading the results of this Graph…
              </p>
            ) : instancesError && !instancesLoaded ? (
              <p role="alert" {...stylex.props(s.message, s.messageError)}>
                <CircleAlert size={15} aria-hidden />
                {instancesError.message}
                <button
                  type="button"
                  {...stylex.props(s.retry)}
                  onClick={() => void refreshInstances()}
                >
                  Try again
                </button>
              </p>
            ) : !groups.length ? (
              <p {...stylex.props(s.message)}>
                No node of this Graph has stored a result yet. Run the Graph to
                store what its nodes produce.
              </p>
            ) : (
              groups.map((group, index) => (
                <InstanceGroup
                  key={group.key}
                  workspaceId={workspaceId}
                  projectId={projectId}
                  group={group}
                  open={index === 0}
                  registry={registry}
                  savedArtifactIds={savedArtifactIds}
                  savingArtifactId={savingArtifactId}
                  canSave={canSave}
                  onSave={saveArtifact}
                />
              ))
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
    </section>
  );
}
