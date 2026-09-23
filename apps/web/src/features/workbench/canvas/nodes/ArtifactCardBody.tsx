"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  useConnection,
  useEdges,
  useNodesData,
  useUpdateNodeInternals,
} from "@xyflow/react";
import useSWR from "swr";
import {
  ArrowDown,
  ArrowUp,
  File as FileIcon,
  FileSpreadsheet,
  FileText,
  X,
} from "lucide-react";

import { useWorkspaceContext } from "@/features/workspaces/WorkspaceLayout";
import {
  artifactInlineContentUrl,
  libraryFoldersApi,
  type PlacedLibraryItem,
} from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { RemoteSelectionRing } from "../../room/RemoteSelectionRing";
import { useOptionalCanvasGridSettings } from "../canvas-grid-settings";
import { resolveArtifactCardSource } from "../artifact-connections";
import { gridAlignedWidth } from "../grid-layout";
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
import { LayoutResizeHandle } from "./LayoutResizeHandle";
import {
  ARTIFACT_RAIL_GAP,
  ARTIFACT_RAIL_PORT,
  ArtifactLeftRail,
  ArtifactRightRail,
  ArtifactSequenceBar,
} from "./ArtifactControls";
import { ArtifactLabel, ImageArtifactBody } from "./ImageArtifactBody";
import { usePickupLift } from "./usePickupLift";
import {
  formatLibraryByteSize,
  libraryFileDisplayName,
} from "../../ui/side-panel/library-tree";

const s = stylex.create({
  artifactNode: {
    position: "relative",
    display: "flex",
    flexDirection: "column",
    width: "fit-content",
    color: tokens.colorText,
    cursor: "grab",
    transitionProperty: {
      default: "transform",
      "@media (prefers-reduced-motion: reduce)": "none",
    },
    transitionDuration: "140ms",
    transitionTimingFunction: "cubic-bezier(0.22, 1, 0.36, 1)",
  },
  artifactNodeActive: { transform: "translate3d(0, -2px, 0)" },
  artifactNodeDragged: {
    transform: "translate3d(0, -8px, 0)",
    cursor: "grabbing",
  },
  // The plate a file artifact shows instead of its pixels. It lifts on the same
  // tier ladder as an image's media box.
  fileBody: {
    position: "relative",
    display: "flex",
    alignItems: "center",
    gap: "8px",
    width: "100%",
    // The rails, not the content, set this floor: the stacked actions take the
    // rail's top 50px (4 + 22 + 2 + 22) and the output ball its bottom 30px.
    minHeight: "80px",
    boxSizing: "border-box",
    padding: "8px 10px",
    border: `1px solid ${tokens.colorBorder}`,
    borderRadius: tokens.radiusSm,
    backgroundColor: tokens.colorSurface,
    boxShadow: "none",
  },
  fileBodyRaised: { boxShadow: tokens.shadowNodeActive },
  fileBodyDragged: { boxShadow: tokens.shadowNodeDragged },
  fileIcon: {
    display: "grid",
    placeItems: "center",
    color: tokens.colorMuted,
    flexShrink: 0,
  },
  pdfIcon: { color: tokens.colorDanger },
  tableIcon: { color: tokens.colorSuccess },
  fileMeta: {
    minWidth: 0,
    fontSize: tokens.fontSizeXs,
    color: tokens.colorMuted,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  frame: {
    display: "grid",
    gridTemplateRows: "auto minmax(0, 1fr)",
    position: "relative",
    transitionProperty: "margin-left, grid-template-columns, column-gap",
    transitionDuration: "180ms",
    transitionTimingFunction: "cubic-bezier(0.22, 1, 0.36, 1)",
    "@media (prefers-reduced-motion: reduce)": { transitionDuration: "0ms" },
  },
  head: {
    gridColumn: 2,
    gridRow: 1,
    minWidth: 0,
  },
  body: {
    gridColumn: 2,
    gridRow: 2,
    minWidth: 0,
    position: "relative",
  },
  imageUnavailable: {
    padding: "16px 0",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
  },
  stack: {
    position: "relative",
    width: "100%",
    height: "130px",
  },
  stackThumb: {
    position: "absolute",
    display: "grid",
    placeItems: "center",
    width: "calc(100% - 48px)",
    height: "105px",
    objectFit: "cover",
    borderRadius: tokens.radiusSm,
    backgroundColor: "transparent",
    color: tokens.colorMuted,
    boxShadow: tokens.shadowNode,
  },
  stackThumbSelected: { boxShadow: tokens.shadowNodeActive },
  stackThumbDragged: { boxShadow: tokens.shadowNodeDragged },
  stackFile: { backgroundColor: tokens.colorSurfaceRaised },
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
 * An artifact on the canvas: the artifact itself is the node. The head is the
 * same width as the body. The side rails sit only beside the body. Picking it
 * up opens those rails so the ports and actions sit just beside the image or
 * file.
 * A run of artifacts shows as a stack whose order is the order it passes on.
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
  value: ArtifactCardValue | null;
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
  const [overlayOpen, setOverlayOpen] = React.useState(false);
  const connecting = useConnection((connection) => connection.inProgress);
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
  const source = resolveArtifactCardSource({
    value,
    feed,
    run: producer?.data.run,
  });
  const shownValue = source.value;
  const refs = cardArtifactRefs(shownValue);
  const contract = shownValue
    ? artifactCardContract(shownValue)
    : (feedPortName ?? "Artifact");
  const awaitingFeed = source.kind === "waiting";
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
  const { tier, liftRef, holdHandlers } = usePickupLift({
    id,
    selected,
    dragging,
    updateNodeInternals,
  });
  const requestedWidth = gridAlignedWidth(
    layout?.width ?? DEFAULT_ARTIFACT_CARD_WIDTH,
    grid?.settings,
    grid?.bypassSnap,
    ARTIFACT_CARD_WIDTH_MIN,
  );

  const commitLayout = (next: WorkflowNodeLayout | null) => {
    setDraftLayout(null);
    data.onLayoutChange?.(id, next);
    window.requestAnimationFrame(() => updateNodeInternals(id));
  };

  const step = (index: number, delta: number) => {
    const moved = moveArtifactCardRef(refs, index, delta);
    const same =
      moved.length === refs.length &&
      moved.every((ref, at) => ref.artifact_id === refs[at].artifact_id);
    if (same) return;
    data.onRefsChange?.(id, artifactCardValue(moved, shownValue));
  };

  const first = refs[0] ?? null;
  const firstItem = first ? itemsById.get(first.artifact_id) : undefined;
  const firstUrl = first
    ? artifactInlineContentUrl(workspace.id, first.artifact_id)
    : "";
  const firstSummary = source.output?.artifacts[0] ?? firstItem?.artifact;
  const imageArtifact =
    first !== null && isImageArtifact(first, firstSummary?.content_type);
  const isSequence = shownValue !== null && "item_refs" in shownValue;
  const imageSize = first ? imageSizes[first.artifact_id] : undefined;
  const recordedName = firstSummary?.metadata?.original_filename;
  const fileName =
    (first ? nameOf(first.artifact_id) : null) ??
    (typeof recordedName === "string" ? recordedName : null);
  const isPdf =
    firstSummary?.content_type === "application/pdf" ||
    first?.artifact_type === "file.pdf" ||
    fileName?.toLowerCase().endsWith(".pdf");
  const isTableFile =
    firstSummary?.content_type === "text/csv" ||
    first?.artifact_type === "file.csv" ||
    first?.artifact_type.startsWith("table.") ||
    fileName?.toLowerCase().endsWith(".csv");
  const titleLabel = isSequence
    ? imageArtifact
      ? `${refs.length} ${refs.length === 1 ? "item" : "items"}`
      : "File sequence"
    : first
      ? (fileName ??
        (feed
          ? `${producer?.data.spec.title ?? "Output"} → ${feedPort?.title ?? feedPortName ?? "output"}`
          : imageArtifact
            ? "Image"
            : "File"))
      : "Artifact";
  const byteSize = formatLibraryByteSize(firstSummary?.byte_size);

  const subtitle = awaitingFeed
    ? "Output"
    : isSequence
      ? contract
      : [
          byteSize,
          imageSize
            ? `${imageSize.width} × ${imageSize.height}`
            : imageArtifact
              ? "Image"
              : isPdf
                ? "PDF"
                : isTableFile
                  ? "Table"
                  : "File",
        ]
          .filter(Boolean)
          .join(" · ");
  const imageAspect = imageSize ? imageSize.width / imageSize.height : 4 / 3;
  const mediaWidth = imageArtifact
    ? Math.min(
        requestedWidth,
        Math.round((layout?.bodyHeight ?? 360) * imageAspect),
      )
    : requestedWidth;
  const mediaHeight = imageArtifact
    ? Math.round(
        (mediaWidth - (isSequence ? (Math.min(refs.length, 3) - 1) * 12 : 0)) /
          imageAspect,
      )
    : (layout?.bodyHeight ?? artifactCardMediaHeight(mediaWidth));
  const portColor = first
    ? artifactTypeColor(first.artifact_type, tokens.colorAccent)
    : tokens.colorInfo;

  const fileGlyph = isPdf ? (
    <FileText size={16} />
  ) : isTableFile ? (
    <FileSpreadsheet size={16} />
  ) : (
    <FileIcon size={16} />
  );

  const showActions = Boolean(selected) || overlayOpen;
  const showPorts = showActions || connecting;
  const leftRail = showPorts ? ARTIFACT_RAIL_PORT : 0;
  const rightRail = showPorts ? ARTIFACT_RAIL_PORT : 0;
  const railGap = showPorts ? ARTIFACT_RAIL_GAP : 0;
  const cardWidth = imageArtifact ? mediaWidth : requestedWidth;

  React.useLayoutEffect(() => {
    updateNodeInternals(id);
  }, [
    id,
    updateNodeInternals,
    mediaWidth,
    mediaHeight,
    reordering,
    titleLabel,
    subtitle,
  ]);

  const reorderStyle = stylex.props(s.reorder);
  const sequenceStack = isSequence ? (
    <div
      aria-label={`${refs.length} items in sequence`}
      {...stylex.props(s.stack)}
    >
      {!selected && data.remoteSelectionColor ? (
        <RemoteSelectionRing color={data.remoteSelectionColor} radius={5} />
      ) : null}
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
            data-artifact-shadow-scope="sequence-item"
            src={artifactInlineContentUrl(workspace.id, ref.artifact_id)}
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
            {...stylex.props(
              s.stackThumb,
              selected ? s.stackThumbSelected : null,
              tier === "dragged" ? s.stackThumbDragged : null,
            )}
            style={position}
          />
        ) : (
          <span
            key={ref.artifact_id}
            data-artifact-shadow-scope="sequence-item"
            {...stylex.props(
              s.stackThumb,
              s.stackFile,
              selected ? s.stackThumbSelected : null,
              tier === "dragged" ? s.stackThumbDragged : null,
            )}
            style={position}
          >
            <FileIcon size={28} />
          </span>
        );
      })}
    </div>
  ) : null;

  return (
    <div
      ref={liftRef}
      {...holdHandlers}
      data-artifact-card-id={id}
      data-artifact-node="true"
      data-testid="artifact-card-node"
      {...stylex.props(
        s.artifactNode,
        tier === "active" ? s.artifactNodeActive : null,
        tier === "dragged" ? s.artifactNodeDragged : null,
      )}
      style={{ width: cardWidth }}
      role="group"
      aria-label={`Artifact ${contract}`}
    >
      <div
        data-artifact-frame="true"
        data-artifact-content="true"
        {...stylex.props(s.frame)}
        style={{
          width: cardWidth + leftRail + rightRail + railGap * 2,
          marginLeft: -(leftRail + railGap),
          gridTemplateColumns: `${leftRail}px ${cardWidth}px ${rightRail}px`,
          columnGap: railGap,
        }}
      >
        <div data-artifact-head="true" {...stylex.props(s.head)}>
          <ArtifactLabel
            title={titleLabel}
            contract={contract}
            selected={selected ?? false}
            image={imageArtifact}
          />
        </div>
        <ArtifactLeftRail
          color={portColor}
          sequence={isSequence}
          showPorts={showPorts}
          isConnectable={isConnectable}
        />
        <div data-artifact-body="true" {...stylex.props(s.body)}>
          {imageArtifact ? (
            <ImageArtifactBody
              images={refs.map((ref, index) => ({
                id: ref.artifact_id,
                url: artifactInlineContentUrl(workspace.id, ref.artifact_id),
                name:
                  nameOf(ref.artifact_id) ??
                  (index === 0 ? titleLabel : `Item ${index + 1}`),
                failed: imagesFailed[ref.artifact_id] ?? false,
              }))}
              sequence={isSequence}
              mediaHeight={mediaHeight}
              selected={selected ?? false}
              tier={tier}
              remoteSelectionColor={data.remoteSelectionColor}
              onSize={(artifactId, width, height) =>
                setImageSizes((current) => {
                  const previous = current[artifactId];
                  return previous?.width === width && previous.height === height
                    ? current
                    : { ...current, [artifactId]: { width, height } };
                })
              }
              onError={(artifactId) =>
                setImagesFailed((current) => ({
                  ...current,
                  [artifactId]: true,
                }))
              }
            />
          ) : (
            <>
              {awaitingFeed ? (
                <div {...stylex.props(s.imageUnavailable)}>
                  {producer
                    ? `Waiting for ${feedPort?.title ?? feedPortName ?? "output"}`
                    : "Waiting for this graph to run"}
                </div>
              ) : null}
              {isSequence ? (
                sequenceStack
              ) : first && !awaitingFeed ? (
                <div
                  data-artifact-file-body="true"
                  data-artifact-shadow-scope="file"
                  {...stylex.props(
                    s.fileBody,
                    tier === "active" ? s.fileBodyRaised : null,
                    tier === "dragged" ? s.fileBodyDragged : null,
                  )}
                >
                  {!selected && data.remoteSelectionColor ? (
                    <RemoteSelectionRing
                      color={data.remoteSelectionColor}
                      radius={4}
                    />
                  ) : null}
                  <span
                    aria-hidden="true"
                    {...stylex.props(
                      s.fileIcon,
                      isPdf ? s.pdfIcon : null,
                      isTableFile ? s.tableIcon : null,
                    )}
                  >
                    {fileGlyph}
                  </span>
                  <span {...stylex.props(s.fileMeta)}>{subtitle}</span>
                </div>
              ) : null}
            </>
          )}
          {allowCornerResize ? (
            <LayoutResizeHandle
              layout={layout ?? { width: requestedWidth }}
              axes={["width"]}
              ariaLabel="Resize artifact"
              onDraft={setDraftLayout}
              onCommit={commitLayout}
            />
          ) : null}
        </div>
        <ArtifactRightRail
          contract={contract}
          title={titleLabel}
          detail={awaitingFeed ? "Waiting for output" : subtitle}
          artifactId={isSequence ? undefined : first?.artifact_id}
          originalUrl={first ? firstUrl : undefined}
          color={portColor}
          sequence={isSequence}
          hasArtifacts={refs.length > 0}
          isConnectable={isConnectable}
          showActions={showActions}
          showPorts={showPorts}
          onOverlayChange={setOverlayOpen}
          editableSequence={isSequence && !feed && isConnectable}
          onRearrange={() => setReordering((open) => !open)}
          onRemove={() => data.onRemoveNode?.(id)}
        />
        {selected && isSequence && !feed && isConnectable ? (
          <ArtifactSequenceBar
            onRearrange={() => setReordering((open) => !open)}
            onUngroup={data.onUngroup ? () => data.onUngroup?.(id) : undefined}
            ungroupDisabledReason={data.ungroupDisabledReason}
          />
        ) : null}
      </div>

      {reordering && !feed && refs.length > 1 ? (
        <div
          {...reorderStyle}
          className={`nodrag nopan ${reorderStyle.className ?? ""}`}
        >
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
          <div role="list" aria-label="Sequence order">
            {refs.map((ref, index) => (
              <div
                role="listitem"
                key={ref.artifact_id}
                {...stylex.props(s.reorderRow)}
              >
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
        </div>
      ) : null}
    </div>
  );
}
