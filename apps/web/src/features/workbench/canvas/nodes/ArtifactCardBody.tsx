"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Menu } from "@base-ui/react/menu";
import {
  Handle,
  Position,
  useEdges,
  useNodesData,
  useUpdateNodeInternals,
} from "@xyflow/react";
import useSWR from "swr";
import {
  ArrowDown,
  ArrowUp,
  Download,
  File as FileIcon,
  GripVertical,
  ImageOff,
  MoreHorizontal,
  Trash2,
} from "lucide-react";

import { useWorkspaceContext } from "@/features/workspaces/WorkspaceLayout";
import {
  artifactInlineContentUrl,
  libraryFoldersApi,
  type PlacedLibraryItem,
} from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { useOptionalCanvasGridSettings } from "../canvas-grid-settings";
import { writeArtifactDrop } from "../../model/artifact-drop";
import {
  DEFAULT_ARTIFACT_CARD_WIDTH,
  artifactCardContract,
  artifactCardMediaHeight,
  artifactCardValue,
  cardArtifactRefs,
  isImageArtifact,
  moveArtifactCardRef,
  type ArtifactCardValue,
} from "../artifact-card";
import {
  ARTIFACT_VIEWER_EDGE_TYPE,
  ARTIFACT_VIEWER_INPUT_HANDLE,
  type ArtifactViewerEdge,
  type ArtifactViewerNodeData,
  type CanvasEdge,
  type CanvasNode,
} from "../artifact-viewer";
import type { ArtifactRef } from "@/lib/api";
import { handleStyle } from "../handle-style";
import { WORKFLOW_NODE_TYPE } from "../types";
import type { WorkflowNodeLayout } from "../node-layout";
import { CanvasNodeShell, useCanvasNodeShell } from "./CanvasNodeShell";
import { LayoutResizeHandle } from "./LayoutResizeHandle";
import {
  libraryFileDisplayName,
  libraryFileSubtitle,
} from "../../ui/side-panel/library-tree";

const s = stylex.create({
  /**
   * The strip a node header would occupy, kept the same height so an artifact's
   * body starts on the same line as the body of the node next to it. The name
   * rides in it instead of a title bar.
   */
  meta: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
    height: "34px",
    boxSizing: "border-box",
    padding: "0 28px 0 12px",
    fontSize: tokens.fontSizeXs,
    color: tokens.colorTextEmphasis,
    whiteSpace: "nowrap",
    overflow: "hidden",
    pointerEvents: "none",
    userSelect: "none",
  },
  metaContract: {
    color: tokens.colorMuted,
    fontFamily: "var(--font-mono, ui-monospace, monospace)",
  },
  mediaWrap: {
    position: "relative",
  },
  /**
   * The container sets the size and the artifact fills it, so a portrait photo
   * and a wide map take the same room on the canvas instead of each dictating
   * its own shape. Cropping beats empty bands of backdrop.
   */
  media: {
    position: "relative",
    width: "100%",
    borderRadius: "10px",
    overflow: "hidden",
    backgroundColor: tokens.colorSurfaceSunken,
    boxShadow: tokens.shadowNode,
  },
  image: {
    display: "block",
    width: "100%",
    height: "100%",
    objectFit: "cover",
  },
  fileTile: {
    display: "flex",
    alignItems: "center",
    gap: "9px",
    height: "100%",
    boxSizing: "border-box",
    padding: "0 13px",
  },
  fileIcon: {
    color: tokens.colorMuted,
    flexShrink: 0,
  },
  fileCopy: {
    display: "flex",
    flexDirection: "column",
    gap: "2px",
    minWidth: 0,
  },
  fileName: {
    fontSize: tokens.fontSizeSm,
    color: tokens.colorText,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  fileMeta: {
    fontSize: tokens.fontSizeXs,
    color: tokens.colorMuted,
  },
  awaiting: {
    position: "absolute",
    inset: 0,
    display: "grid",
    placeItems: "center",
    padding: "0 16px",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    textAlign: "center",
  },
  stack: {
    position: "relative",
    width: "100%",
    height: "100%",
  },
  stackThumb: {
    position: "absolute",
    width: "58%",
    height: "112px",
    objectFit: "cover",
    borderRadius: "7px",
    boxShadow: tokens.shadowNode,
    border: `1px solid ${tokens.colorBorder}`,
  },
  stackCount: {
    position: "absolute",
    right: "10px",
    bottom: "9px",
    padding: "2px 7px",
    borderRadius: "999px",
    backgroundColor: tokens.colorSurfaceRaised,
    border: `1px solid ${tokens.colorBorder}`,
    fontSize: tokens.fontSizeXs,
    color: tokens.colorText,
  },
  /** The pass handle: a floating ball that carries the card's artifacts. */
  ball: {
    position: "absolute",
    right: "-9px",
    top: "50%",
    transform: "translateY(-50%)",
    width: "18px",
    height: "18px",
    padding: 0,
    borderRadius: "999px",
    border: `2px solid ${tokens.colorSurface}`,
    backgroundColor: tokens.colorAccent,
    boxShadow: tokens.shadowNode,
    cursor: "grab",
    opacity: { default: 0.9, ":hover": 1 },
    zIndex: 2,
  },
  menu: {
    position: "absolute",
    top: "-30px",
    right: "2px",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    width: "22px",
    height: "22px",
    padding: 0,
    borderRadius: "6px",
    border: "none",
    backgroundColor: tokens.colorSurfaceRaised,
    color: tokens.colorText,
    cursor: "pointer",
    opacity: { default: 0.72, ":hover": 1 },
    zIndex: 2,
  },
  menuPopup: {
    minWidth: "188px",
    padding: "4px",
    borderRadius: "8px",
    border: `1px solid ${tokens.colorBorder}`,
    backgroundColor: tokens.colorSurfaceRaised,
    boxShadow: tokens.shadowNode,
    display: "flex",
    flexDirection: "column",
    gap: "2px",
    zIndex: 30,
  },
  menuItem: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    padding: "6px 8px",
    borderRadius: "6px",
    fontSize: tokens.fontSizeSm,
    color: tokens.colorText,
    cursor: "pointer",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
  },
  reorder: {
    display: "flex",
    flexDirection: "column",
    gap: "4px",
    marginTop: "6px",
    padding: "8px",
    borderRadius: "9px",
    border: `1px solid ${tokens.colorBorder}`,
    backgroundColor: tokens.colorSurfaceRaised,
    boxShadow: tokens.shadowNode,
  },
  reorderHead: {
    fontSize: tokens.fontSizeXs,
    color: tokens.colorMuted,
    marginBottom: "2px",
  },
  reorderRow: {
    display: "flex",
    alignItems: "center",
    gap: "7px",
  },
  reorderIndex: {
    width: "14px",
    fontSize: tokens.fontSizeXs,
    color: tokens.colorMuted,
    textAlign: "center",
  },
  reorderThumb: {
    width: "30px",
    height: "30px",
    borderRadius: "5px",
    objectFit: "cover",
    border: `1px solid ${tokens.colorBorder}`,
    flexShrink: 0,
  },
  reorderName: {
    flex: 1,
    minWidth: 0,
    fontSize: tokens.fontSizeXs,
    color: tokens.colorText,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  step: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    width: "20px",
    height: "20px",
    padding: 0,
    borderRadius: "5px",
    border: `1px solid ${tokens.colorBorder}`,
    backgroundColor: "transparent",
    color: tokens.colorText,
    cursor: "pointer",
  },
  stepDisabled: {
    color: tokens.colorTextDisabled,
    cursor: "default",
  },
});

/**
 * An artifact on the canvas: the artifact itself is the node, so an image carries
 * no card chrome and its name floats above it on the canvas. A run of artifacts
 * shows as a stack whose order is the order it passes on.
 */
export function ArtifactCardBody({
  id,
  data,
  value,
  selected,
  dragging,
}: {
  id: string;
  data: ArtifactViewerNodeData;
  value: ArtifactCardValue;
  selected?: boolean;
  dragging?: boolean;
}) {
  const { workspace } = useWorkspaceContext();
  const updateNodeInternals = useUpdateNodeInternals();
  const [draftLayout, setDraftLayout] =
    React.useState<WorkflowNodeLayout | null>(null);
  const { data: library } = useSWR(["library-tree", workspace.id], () =>
    libraryFoldersApi.listTree(workspace.id),
  );
  const [reordering, setReordering] = React.useState(false);
  const [imagesFailed, setImagesFailed] = React.useState<
    Record<string, boolean>
  >({});
  // A card an output port is wired into follows that port: it presents the
  // latest artifact the port produced instead of the ref it was dropped with.
  const edges = useEdges<CanvasEdge>();
  const feed = edges.find(
    (edge): edge is ArtifactViewerEdge =>
      edge.type === ARTIFACT_VIEWER_EDGE_TYPE &&
      edge.target === id &&
      edge.targetHandle === ARTIFACT_VIEWER_INPUT_HANDLE,
  );
  const producerCandidate = useNodesData<CanvasNode>(feed?.source ?? "");
  const producer =
    producerCandidate?.type === WORKFLOW_NODE_TYPE ? producerCandidate : null;
  const feedPortName = feed?.data?.sourcePortName ?? null;
  const feedPort =
    producer && feedPortName
      ? producer.data.spec.outputs.find(
          (candidate) => candidate.name === feedPortName,
        )
      : undefined;
  const succeededRun =
    producer?.data.run?.status === "succeeded" ? producer.data.run : null;
  const feedArtifacts =
    succeededRun && feedPortName
      ? (succeededRun.outputs.find(
          (candidate) => candidate.port === feedPortName,
        )?.artifacts ?? [])
      : [];
  // A fed card shows only what the port produced: falling back to the ref it was
  // dropped with would paint a stale artifact behind a live wire.
  const fedValue = artifactCardValue(
    [...feedArtifacts] as unknown as ArtifactRef[],
    value,
  );
  const shownValue: ArtifactCardValue | null = feed ? fedValue : value;
  const refs = shownValue ? cardArtifactRefs(shownValue) : [];
  const contract = shownValue
    ? artifactCardContract(shownValue)
    : (feedPortName ?? "—");
  const awaitingFeed = Boolean(feed) && refs.length === 0;
  const itemsById = React.useMemo(
    () =>
      new Map<string, PlacedLibraryItem>(
        (library?.items ?? []).map((item) => [item.artifact.artifact_id, item]),
      ),
    [library],
  );

  const nameOf = (artifactId: string) => {
    const item = itemsById.get(artifactId);
    return item ? libraryFileDisplayName(item) : null;
  };

  const titleLabel = feed
    ? `${producer?.data.spec.title ?? "Output"} → ${feedPort?.title ?? feedPortName ?? "output"}`
    : refs.length === 1
      ? (nameOf(refs[0].artifact_id) ?? refs[0].artifact_id)
      : `${refs.length} artifacts`;

  const grid = useOptionalCanvasGridSettings();
  const allowCornerResize = grid?.settings.allowWorkflowCornerResize ?? false;
  const shell = useCanvasNodeShell({
    id,
    selected,
    dragging,
    naturalWidth: data.layout?.width ?? DEFAULT_ARTIFACT_CARD_WIDTH,
    updateNodeInternals,
  });
  const layout = draftLayout ?? data.layout;

  const commitLayout = (next: WorkflowNodeLayout | null) => {
    setDraftLayout(null);
    data.onLayoutChange?.(id, next);
    window.requestAnimationFrame(() => updateNodeInternals(id));
  };

  const commit = (next: ArtifactCardValue | null) =>
    data.onRefsChange?.(id, next);

  const step = (index: number, delta: number) => {
    const moved = moveArtifactCardRef(refs, index, delta);
    const same =
      moved.length === refs.length &&
      moved.every((ref, at) => ref.artifact_id === refs[at].artifact_id);
    if (same) return;
    commit(artifactCardValue(moved, value));
  };

  const first = refs[0] ?? null;
  const firstItem = first ? itemsById.get(first.artifact_id) : undefined;
  const firstUrl = first
    ? artifactInlineContentUrl(workspace.id, first.artifact_id)
    : "";
  const showsImage =
    first !== null &&
    refs.length === 1 &&
    isImageArtifact(first, firstItem?.artifact.content_type) &&
    !imagesFailed[first.artifact_id];
  const mediaWidth = layout?.width ?? DEFAULT_ARTIFACT_CARD_WIDTH;
  const mediaHeight = layout?.bodyHeight ?? artifactCardMediaHeight(mediaWidth);

  return (
    <div data-artifact-card-id={id}>
      <CanvasNodeShell
        state={shell}
        selected={selected}
        remoteSelectionColor={data.remoteSelectionColor}
        variant="bare"
        ariaLabel={`Artifact ${contract}`}
        testId="artifact-card-node"
        resizeHandle={
          allowCornerResize ? (
            <LayoutResizeHandle
              layout={layout}
              axes={["width", "bodyHeight"]}
              ariaLabel="Resize artifact"
              onDraft={setDraftLayout}
              onCommit={commitLayout}
            />
          ) : undefined
        }
      >
        <span {...stylex.props(s.meta)}>
          {titleLabel}
          <span {...stylex.props(s.metaContract)}>{contract}</span>
        </span>

        <div {...stylex.props(s.mediaWrap)}>
          {/* The container sets the size; the artifact fits inside it. */}
          <div
            data-artifact-media="true"
            {...stylex.props(s.media)}
            style={{ height: mediaHeight }}
          >
            {awaitingFeed ? (
              <div {...stylex.props(s.awaiting)}>
                {producer
                  ? `Waiting for ${feedPort?.title ?? feedPortName ?? "output"}`
                  : "Waiting for this graph to run"}
              </div>
            ) : null}

            {showsImage ? (
              /* eslint-disable-next-line @next/next/no-img-element -- artifact bytes have no predictable size for the image optimizer */
              <img
                src={firstUrl}
                alt={nameOf(first.artifact_id) ?? contract}
                loading="lazy"
                decoding="async"
                onError={() =>
                  setImagesFailed((current) => ({
                    ...current,
                    [first.artifact_id]: true,
                  }))
                }
                {...stylex.props(s.image)}
              />
            ) : null}

            {refs.length > 1 ? (
              <div {...stylex.props(s.stack)}>
                {refs.slice(0, 3).map((ref, index) => (
                  /* eslint-disable-next-line @next/next/no-img-element -- artifact bytes have no predictable size for the image optimizer */
                  <img
                    key={ref.artifact_id}
                    src={artifactInlineContentUrl(
                      workspace.id,
                      ref.artifact_id,
                    )}
                    alt=""
                    loading="lazy"
                    decoding="async"
                    {...stylex.props(s.stackThumb)}
                    style={{
                      left: `${8 + index * 16}%`,
                      top: `${index * 9}px`,
                      transform: `rotate(${index === 0 ? 0 : index % 2 ? -2 : 2}deg)`,
                      zIndex: refs.length - index,
                    }}
                  />
                ))}
                <span {...stylex.props(s.stackCount)}>
                  {refs.length} items · drag to pass
                </span>
              </div>
            ) : null}

            {refs.length === 1 && !showsImage ? (
              <div {...stylex.props(s.fileTile)}>
                {isImageArtifact(first, firstItem?.artifact.content_type) ? (
                  <ImageOff size={20} {...stylex.props(s.fileIcon)} />
                ) : (
                  <FileIcon size={20} {...stylex.props(s.fileIcon)} />
                )}
                <span {...stylex.props(s.fileCopy)}>
                  <span {...stylex.props(s.fileName)}>
                    {nameOf(first.artifact_id) ?? `${contract} artifact`}
                  </span>
                  <span {...stylex.props(s.fileMeta)}>
                    {firstItem
                      ? libraryFileSubtitle(firstItem)
                      : "not in this library"}
                  </span>
                </span>
              </div>
            ) : null}
          </div>

          <Handle
            id={ARTIFACT_VIEWER_INPUT_HANDLE}
            type="target"
            position={Position.Left}
            isConnectable
            aria-label="Artifact input port, accepts any artifact"
            title="Drag an output port here so this card follows it"
            style={handleStyle("50%", tokens.colorAccent)}
          />

          <button
            type="button"
            className="nodrag"
            draggable={shownValue !== null}
            title="Drag onto a node input to pass these artifacts"
            aria-label={`Pass ${contract} to a node input`}
            onDragStart={(event) => {
              if (shownValue) writeArtifactDrop(event.dataTransfer, shownValue);
            }}
            {...stylex.props(s.ball)}
          />

          <Menu.Root>
            <Menu.Trigger
              className="nodrag"
              aria-label={`Actions for ${contract}`}
              {...stylex.props(s.menu)}
            >
              <MoreHorizontal size={13} />
            </Menu.Trigger>
            <Menu.Portal>
              <Menu.Positioner side="bottom" align="end" sideOffset={4}>
                <Menu.Popup {...stylex.props(s.menuPopup)}>
                  {!feed && refs.length > 1 ? (
                    <Menu.Item
                      onClick={() => setReordering((open) => !open)}
                      {...stylex.props(s.menuItem)}
                    >
                      <GripVertical size={13} />
                      Reorder items
                    </Menu.Item>
                  ) : null}
                  <Menu.Item
                    onClick={() =>
                      window.open(firstUrl, "_blank", "noopener,noreferrer")
                    }
                    {...stylex.props(s.menuItem)}
                  >
                    <Download size={13} />
                    Open original
                  </Menu.Item>
                  <Menu.Item
                    onClick={() => data.onRemoveNode?.(id)}
                    {...stylex.props(s.menuItem)}
                  >
                    <Trash2 size={13} />
                    Remove from canvas
                  </Menu.Item>
                </Menu.Popup>
              </Menu.Positioner>
            </Menu.Portal>
          </Menu.Root>
        </div>

        {reordering && !feed && refs.length > 1 ? (
          <div className="nodrag" {...stylex.props(s.reorder)}>
            <span {...stylex.props(s.reorderHead)}>
              Passed in this order · drag a row&rsquo;s arrows to change it
            </span>
            {refs.map((ref, index) => (
              <div key={ref.artifact_id} {...stylex.props(s.reorderRow)}>
                <span {...stylex.props(s.reorderIndex)}>{index + 1}</span>
                {/* eslint-disable-next-line @next/next/no-img-element -- artifact bytes have no predictable size for the image optimizer */}
                <img
                  src={artifactInlineContentUrl(workspace.id, ref.artifact_id)}
                  alt=""
                  loading="lazy"
                  decoding="async"
                  {...stylex.props(s.reorderThumb)}
                />
                <span {...stylex.props(s.reorderName)}>
                  {nameOf(ref.artifact_id) ?? ref.artifact_id}
                </span>
                <button
                  type="button"
                  disabled={index === 0}
                  aria-label="Move earlier in the order"
                  onClick={() => step(index, -1)}
                  {...stylex.props(s.step, index === 0 ? s.stepDisabled : null)}
                >
                  <ArrowUp size={11} />
                </button>
                <button
                  type="button"
                  disabled={index === refs.length - 1}
                  aria-label="Move later in the order"
                  onClick={() => step(index, 1)}
                  {...stylex.props(
                    s.step,
                    index === refs.length - 1 ? s.stepDisabled : null,
                  )}
                >
                  <ArrowDown size={11} />
                </button>
              </div>
            ))}
          </div>
        ) : null}
      </CanvasNodeShell>
    </div>
  );
}
