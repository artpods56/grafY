"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Menu } from "@base-ui/react/menu";
import { useEdges, useNodesData, useUpdateNodeInternals } from "@xyflow/react";
import useSWR from "swr";
import {
  ArrowDown,
  ArrowUp,
  Download,
  File as FileIcon,
  GripVertical,
  Image as ImageIcon,
  ImageOff,
  Layers,
  MoreVertical,
  Trash2,
  X,
} from "lucide-react";

import { useWorkspaceContext } from "@/features/workspaces/WorkspaceLayout";
import {
  artifactInlineContentUrl,
  libraryFoldersApi,
  type PlacedLibraryItem,
} from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { useOptionalCanvasGridSettings } from "../canvas-grid-settings";
import { ARTIFACT_CARD_OUTPUT_HANDLE } from "../artifact-connections";
import {
  ARTIFACT_CARD_WIDTH_MIN,
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
import { artifactTypeColor } from "../nodes.css";
import { WORKFLOW_NODE_TYPE } from "../types";
import type { WorkflowNodeLayout } from "../node-layout";
import { CanvasNodeShell, useCanvasNodeShell } from "./CanvasNodeShell";
import { CanvasPortRail, CanvasPortTab } from "./CanvasNodeChrome";
import { LayoutResizeHandle } from "./LayoutResizeHandle";
import {
  formatLibraryByteSize,
  libraryFileDisplayName,
} from "../../ui/side-panel/library-tree";

const s = stylex.create({
  header: {
    position: "relative",
    display: "flex",
    alignItems: "center",
    gap: "10px",
    minHeight: "58px",
    boxSizing: "border-box",
    padding: "8px 44px 8px 6px",
    userSelect: "none",
  },
  fileIcon: {
    display: "grid",
    placeItems: "center",
    width: "30px",
    height: "34px",
    borderRadius: "5px",
    backgroundColor: tokens.colorSurfaceRaised,
    color: tokens.colorMuted,
    flexShrink: 0,
  },
  imageIcon: { color: tokens.colorInfo },
  fileCopy: {
    display: "flex",
    flexDirection: "column",
    gap: "4px",
    minWidth: 0,
  },
  fileName: {
    fontSize: tokens.fontSizeSm,
    fontWeight: 500,
    color: tokens.colorTextEmphasis,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  fileMeta: {
    fontSize: tokens.fontSizeXs,
    color: tokens.colorMuted,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  card: { position: "relative" },
  body: {
    boxSizing: "border-box",
    padding: "0 10px 10px",
  },
  /**
   * A snapshot card has no upstream, so its input port stays out of the way
   * until the card is hovered, focused, or selected.
   */
  portPeek: {
    width: "100%",
    height: "100%",
    opacity: 0,
    transitionProperty: {
      default: "opacity",
      "@media (prefers-reduced-motion: reduce)": "none",
    },
    transitionDuration: "120ms",
    ":hover": { opacity: 1 },
    ":focus-within": { opacity: 1 },
  },
  portPeekShown: { opacity: 1 },
  media: {
    position: "relative",
    width: "100%",
    borderRadius: "6px",
    overflow: "hidden",
    backgroundColor: tokens.colorSurfaceSunken,
  },
  image: {
    display: "block",
    width: "100%",
    height: "100%",
    objectFit: "contain",
  },
  imageUnavailable: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "8px",
    height: "100%",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
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
    height: "112px",
  },
  stackThumb: {
    position: "absolute",
    display: "grid",
    placeItems: "center",
    width: "136px",
    height: "88px",
    objectFit: "cover",
    borderRadius: "6px",
    backgroundColor: tokens.colorSurfaceRaised,
    color: tokens.colorMuted,
    boxShadow: tokens.shadowNode,
    border: `1px solid ${tokens.colorBorderStrong}`,
  },
  menu: {
    position: "absolute",
    top: "14px",
    right: "12px",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    width: "28px",
    height: "28px",
    padding: 0,
    borderRadius: "6px",
    border: "none",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: tokens.colorMuted,
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
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "8px",
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
    display: "grid",
    placeItems: "center",
    color: tokens.colorMuted,
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
  isConnectable = true,
}: {
  id: string;
  data: ArtifactViewerNodeData;
  value: ArtifactCardValue;
  selected?: boolean;
  dragging?: boolean;
  isConnectable?: boolean;
}) {
  const { workspace } = useWorkspaceContext();
  const updateNodeInternals = useUpdateNodeInternals();
  const [draftLayout, setDraftLayout] =
    React.useState<WorkflowNodeLayout | null>(null);
  const { data: library } = useSWR(["library-tree", workspace.id], () =>
    libraryFoldersApi.listTree(workspace.id),
  );
  const [reordering, setReordering] = React.useState(false);
  const [imageSizes, setImageSizes] = React.useState<
    Record<string, { width: number; height: number }>
  >({});
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
  const fedValue = artifactCardValue(feedArtifacts, value);
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

  const grid = useOptionalCanvasGridSettings();
  const allowCornerResize = grid?.settings.allowWorkflowCornerResize ?? false;
  const layout = draftLayout ?? data.layout;
  const shell = useCanvasNodeShell({
    id,
    selected,
    dragging,
    naturalWidth: layout?.width ?? DEFAULT_ARTIFACT_CARD_WIDTH,
    minWidth: ARTIFACT_CARD_WIDTH_MIN,
    updateNodeInternals,
  });

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
  const firstSummary = feedArtifacts[0] ?? firstItem?.artifact;
  const imageArtifact =
    first !== null && isImageArtifact(first, firstSummary?.content_type);
  const isSequence = shownValue !== null && "item_refs" in shownValue;
  const imageSize = first ? imageSizes[first.artifact_id] : undefined;
  const titleLabel = feed
    ? `${producer?.data.spec.title ?? "Output"} → ${feedPort?.title ?? feedPortName ?? "output"}`
    : isSequence
      ? `${refs.length} artifacts`
      : first
        ? (nameOf(first.artifact_id) ?? (imageArtifact ? "Image" : "File"))
        : "Artifact";
  const byteSize = formatLibraryByteSize(firstSummary?.byte_size);
  const subtitle = awaitingFeed
    ? "Output"
    : isSequence
      ? `${imageArtifact ? "Image sequence" : "Sequence"} · ${refs.length} items`
      : [
          byteSize,
          imageSize
            ? `${imageSize.width} × ${imageSize.height}`
            : imageArtifact
              ? "Image"
              : "File",
        ]
          .filter(Boolean)
          .join(" · ");
  const mediaWidth = shell.paintWidth;
  const mediaHeight =
    layout?.bodyHeight ??
    (imageSize
      ? Math.min(
          320,
          Math.max(
            100,
            Math.round((mediaWidth * imageSize.height) / imageSize.width),
          ),
        )
      : artifactCardMediaHeight(mediaWidth));
  const hasPreview = imageArtifact || isSequence || awaitingFeed;
  const portColor = first
    ? artifactTypeColor(first.artifact_type, tokens.colorAccent)
    : tokens.colorInfo;
  const outputPortLabel = shownValue
    ? shownValue.artifact_type
    : (feedPort?.title ?? feedPortName ?? "Output");

  React.useLayoutEffect(() => {
    updateNodeInternals(id);
  }, [id, updateNodeInternals, mediaWidth, reordering]);

  return (
    <div data-artifact-card-id={id}>
      <CanvasNodeShell
        state={shell}
        selected={selected}
        remoteSelectionColor={data.remoteSelectionColor}
        ariaLabel={`Artifact ${contract}`}
        testId="artifact-card-node"
        resizeHandle={
          allowCornerResize ? (
            <LayoutResizeHandle
              layout={layout}
              axes={
                hasPreview && !isSequence ? ["width", "bodyHeight"] : ["width"]
              }
              ariaLabel="Resize artifact"
              onDraft={setDraftLayout}
              onCommit={commitLayout}
            />
          ) : undefined
        }
      >
        <div {...stylex.props(s.card)}>
          <div {...stylex.props(s.header)}>
            <span
              aria-hidden="true"
              {...stylex.props(s.fileIcon, imageArtifact ? s.imageIcon : null)}
            >
              {isSequence ? (
                <Layers size={21} />
              ) : imageArtifact ? (
                <ImageIcon size={21} />
              ) : (
                <FileIcon size={23} />
              )}
            </span>
            <span {...stylex.props(s.fileCopy)}>
              <span title={titleLabel} {...stylex.props(s.fileName)}>
                {titleLabel}
              </span>
              <span title={contract} {...stylex.props(s.fileMeta)}>
                {subtitle}
              </span>
            </span>
          </div>

          <CanvasPortRail
            rows={[
              {
                input: (
                  <div
                    {...stylex.props(
                      s.portPeek,
                      feed || selected ? s.portPeekShown : null,
                    )}
                  >
                    <CanvasPortTab
                      nodeId={id}
                      label="Artifact"
                      hint={feed ? undefined : "any"}
                      direction="input"
                      handleId={ARTIFACT_VIEWER_INPUT_HANDLE}
                      color={feed ? tokens.colorSuccess : tokens.colorInfo}
                      isConnectable={isConnectable}
                      ariaLabel="Input port Artifact, accepts any artifact"
                      title="Accepts any artifact or artifact sequence. Drag an output port here so this card follows it."
                    />
                  </div>
                ),
                output: (
                  <CanvasPortTab
                    nodeId={id}
                    label={outputPortLabel}
                    hint={isSequence ? "· many" : undefined}
                    direction="output"
                    handleId={ARTIFACT_CARD_OUTPUT_HANDLE}
                    color={portColor}
                    multiple={isSequence}
                    inactive={refs.length === 0}
                    isConnectable={isConnectable && refs.length > 0}
                    ariaLabel={`Connect ${contract} to a node input`}
                    title="Connect to a compatible input"
                  />
                ),
              },
            ]}
          />

          {hasPreview || isSequence ? (
            <div {...stylex.props(s.body)}>
              {hasPreview && !isSequence ? (
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
                  ) : first && !imagesFailed[first.artifact_id] ? (
                    /* eslint-disable-next-line @next/next/no-img-element -- artifact bytes have no predictable size for the image optimizer */
                    <img
                      src={firstUrl}
                      alt={titleLabel}
                      loading="lazy"
                      decoding="async"
                      draggable={false}
                      onLoad={(event) => {
                        const { naturalWidth: width, naturalHeight: height } =
                          event.currentTarget;
                        if (width > 0 && height > 0) {
                          setImageSizes((current) => ({
                            ...current,
                            [first.artifact_id]: { width, height },
                          }));
                        }
                      }}
                      onError={() =>
                        setImagesFailed((current) => ({
                          ...current,
                          [first.artifact_id]: true,
                        }))
                      }
                      {...stylex.props(s.image)}
                    />
                  ) : (
                    <div {...stylex.props(s.imageUnavailable)}>
                      <ImageOff size={18} />
                      Preview unavailable
                    </div>
                  )}
                </div>
              ) : null}

              {isSequence ? (
                <div
                  aria-label={`${refs.length} items in sequence`}
                  {...stylex.props(s.stack)}
                >
                  {refs.slice(0, 4).map((ref, index) => {
                    const position = {
                      left: 6 + index * 12,
                      top: index * 6,
                      zIndex: index + 1,
                    };
                    return isImageArtifact(
                      ref,
                      itemsById.get(ref.artifact_id)?.artifact.content_type,
                    ) && !imagesFailed[ref.artifact_id] ? (
                      /* eslint-disable-next-line @next/next/no-img-element -- artifact bytes have no predictable size for the image optimizer */
                      <img
                        key={ref.artifact_id}
                        src={artifactInlineContentUrl(
                          workspace.id,
                          ref.artifact_id,
                        )}
                        alt={nameOf(ref.artifact_id) ?? `Item ${index + 1}`}
                        loading="lazy"
                        decoding="async"
                        draggable={false}
                        onError={() =>
                          setImagesFailed((current) => ({
                            ...current,
                            [ref.artifact_id]: true,
                          }))
                        }
                        {...stylex.props(s.stackThumb)}
                        style={position}
                      />
                    ) : (
                      <span
                        key={ref.artifact_id}
                        {...stylex.props(s.stackThumb)}
                        style={position}
                      >
                        <FileIcon size={28} />
                      </span>
                    );
                  })}
                </div>
              ) : null}
            </div>
          ) : null}

          {selected ? (
            <Menu.Root>
              <Menu.Trigger
                className="nodrag"
                aria-label={`Actions for ${contract}`}
                {...stylex.props(s.menu)}
              >
                <MoreVertical size={16} />
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
                      disabled={!first}
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
          ) : null}
        </div>

        {reordering && !feed && refs.length > 1 ? (
          <div className="nodrag" {...stylex.props(s.reorder)}>
            <span {...stylex.props(s.reorderHead)}>
              <span>{refs.length} items · use arrows to reorder</span>
              <button
                type="button"
                aria-label="Close sequence order"
                onClick={() => setReordering(false)}
                {...stylex.props(s.step)}
              >
                <X size={12} />
              </button>
            </span>
            {refs.map((ref, index) => (
              <div key={ref.artifact_id} {...stylex.props(s.reorderRow)}>
                <span {...stylex.props(s.reorderIndex)}>{index + 1}</span>
                {isImageArtifact(
                  ref,
                  itemsById.get(ref.artifact_id)?.artifact.content_type,
                ) && !imagesFailed[ref.artifact_id] ? (
                  /* eslint-disable-next-line @next/next/no-img-element -- artifact bytes have no predictable size for the image optimizer */
                  <img
                    src={artifactInlineContentUrl(
                      workspace.id,
                      ref.artifact_id,
                    )}
                    alt=""
                    loading="lazy"
                    decoding="async"
                    draggable={false}
                    onError={() =>
                      setImagesFailed((current) => ({
                        ...current,
                        [ref.artifact_id]: true,
                      }))
                    }
                    {...stylex.props(s.reorderThumb)}
                  />
                ) : (
                  <span {...stylex.props(s.reorderThumb)}>
                    <FileIcon size={16} />
                  </span>
                )}
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
