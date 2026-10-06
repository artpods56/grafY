"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { useUpdateNodeInternals } from "@xyflow/react";
import useSWR from "swr";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  File as FileIcon,
  LoaderCircle,
  Trash2,
  Ungroup,
  X,
} from "lucide-react";

import { useWorkspaceContext } from "@/features/workspaces/WorkspaceLayout";
import {
  artifactInlineContentUrl,
  libraryFoldersApi,
  type ArtifactRef,
  type PlacedLibraryItem,
} from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";
import {
  COLLECTION_PORT,
  collectionSparePlugId,
  type CollectionMember,
} from "../../model/collection";
import { RemoteSelectionRing } from "../../room/RemoteSelectionRing";
import { libraryFileDisplayName } from "../../ui/side-panel/library-tree";
import { DEFAULT_ARTIFACT_CARD_WIDTH, isImageArtifact } from "../artifact-card";
import { useOptionalCanvasGridSettings } from "../canvas-grid-settings";
import { gridAlignedWidth } from "../grid-layout";
import { encodeHandleId } from "../handles";
import { artifactTypeColor } from "../nodes.css";
import { useArtifactTypeCatalog } from "../use-artifact-type-catalog";
import {
  formatArtifactTypeLabel,
  formatArtifactTypeSequence,
  formatArtifactTypeSequenceTooltip,
} from "../artifact-type-label";
import {
  portMetaForPort,
  resolvedPortArtifactType,
  type WorkflowNodeData,
} from "../types";
import { artifactRail } from "./ArtifactControls";
import { ArtifactLabel, ImageArtifactBody } from "./ImageArtifactBody";
import { NodeMenu, type NodeMenuItem } from "./NodeMenu";
import {
  PortBall,
  PortRevealProvider,
  revealDelay,
  revealStyles,
  usePortReveal,
} from "./PortBall";
import { usePickupLift } from "./usePickupLift";

const s = stylex.create({
  card: {
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
  cardActive: { transform: "translate3d(0, -2px, 0)" },
  cardDragged: { transform: "translate3d(0, -8px, 0)", cursor: "grabbing" },
  frame: {
    display: "grid",
    gridTemplateRows: "auto minmax(0, 1fr)",
    position: "relative",
  },
  body: { position: "relative", minWidth: 0 },
  // Every member's plug handle sits on the one input ball, so the edges of
  // all members meet there; only the spare's ring is drawn.
  stacked: { position: "absolute", top: 0, left: 0 },
  spare: { zIndex: 1 },
  // Stand-in tiles for members that are not pictures, or not produced yet.
  tiles: { position: "relative", width: "100%" },
  tile: {
    position: "absolute",
    display: "flex",
    alignItems: "center",
    gap: "8px",
    boxSizing: "border-box",
    height: "80px",
    padding: "8px 10px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusSm,
    backgroundColor: tokens.colorSurface,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    overflow: "hidden",
    transitionProperty: "box-shadow",
    transitionDuration: {
      default: "180ms",
      "@media (prefers-reduced-motion: reduce)": "0ms",
    },
  },
  tileRaised: { boxShadow: tokens.shadowNodeActive },
  tileDragged: { boxShadow: tokens.shadowNodeDragged },
  tileText: {
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  tileEmpty: {
    borderStyle: "dashed",
    justifyContent: "center",
    textAlign: "center",
  },
  spinner: {
    flexShrink: 0,
    color: tokens.colorInfo,
    animationName: "grafy-spin",
    animationDuration: "900ms",
    animationIterationCount: "infinite",
    animationTimingFunction: "linear",
  },
  error: {
    marginTop: "6px",
    color: tokens.colorDanger,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.4,
  },
  members: {
    display: "grid",
    gap: "2px",
    marginTop: "8px",
    padding: "6px",
    borderRadius: tokens.radiusMd,
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    backgroundColor: tokens.colorSurfaceRaised,
    boxShadow: tokens.shadowNode,
    cursor: "default",
  },
  membersHead: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "8px",
    padding: "0 2px 4px 4px",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
  },
  member: {
    display: "flex",
    alignItems: "center",
    gap: "7px",
    minHeight: "34px",
    paddingInline: "4px",
    borderRadius: tokens.radiusSm,
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
  },
  memberIndex: {
    width: "14px",
    flexShrink: 0,
    color: tokens.colorSubtle,
    fontSize: "10px",
    textAlign: "center",
  },
  memberThumb: {
    display: "grid",
    placeItems: "center",
    width: "26px",
    height: "26px",
    flexShrink: 0,
    borderRadius: "4px",
    objectFit: "cover",
    backgroundColor: tokens.colorSurfaceSunken,
    color: tokens.colorMuted,
  },
  memberCopy: { display: "grid", minWidth: 0, flex: 1 },
  memberName: {
    overflow: "hidden",
    color: tokens.colorText,
    fontSize: tokens.fontSizeXs,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  memberSource: {
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontSize: "10px",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  step: {
    display: "grid",
    placeItems: "center",
    width: "20px",
    height: "20px",
    flexShrink: 0,
    padding: 0,
    borderWidth: 0,
    borderRadius: "5px",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: { default: tokens.colorSubtle, ":hover": tokens.colorText },
    cursor: "pointer",
    ":disabled": { opacity: 0.35, cursor: "default" },
  },
  stepDanger: {
    color: { default: tokens.colorSubtle, ":hover": tokens.colorDanger },
  },
});

function memberRefs(member: CollectionMember): readonly ArtifactRef[] {
  if (member.kind === "library") return member.refs;
  if (member.kind === "output") return member.refs ?? [];
  return [];
}

/**
 * A collection on the canvas: the artifacts it gathers, shown as the stack
 * they pass on. Members join through its one input ball (a wire from an
 * output, a card, or a Library drop onto the stack) and leave through its
 * member list. It is the `sequence.collect` operator underneath.
 */
export function CollectionCard({
  id,
  data,
  selected,
  dragging,
}: {
  id: string;
  data: WorkflowNodeData;
  selected?: boolean;
  dragging?: boolean;
}) {
  const { workspace } = useWorkspaceContext();
  const updateNodeInternals = useUpdateNodeInternals();
  const { data: library } = useSWR(["library-tree", workspace.id], () =>
    libraryFoldersApi.listTree(workspace.id),
  );
  const itemsById = React.useMemo(
    () =>
      new Map<string, PlacedLibraryItem>(
        (library?.items ?? []).map((item) => [item.artifact.artifact_id, item]),
      ),
    [library],
  );
  const [menuOpen, setMenuOpen] = React.useState(false);
  const [managing, setManaging] = React.useState(false);
  const [imageSizes, setImageSizes] = React.useState<
    Record<string, { width: number; height: number }>
  >({});
  const [imagesFailed, setImagesFailed] = React.useState<
    Record<string, boolean>
  >({});
  const { tier, liftRef, holdHandlers } = usePickupLift({
    id,
    selected,
    dragging,
    updateNodeInternals,
  });
  const active = Boolean(selected) || menuOpen;
  const portReveal = usePortReveal({ id, active, updateNodeInternals });
  const grid = useOptionalCanvasGridSettings();

  const members = data.collectionMembers ?? [];
  const filled = members.filter((member) => member.kind !== "empty");
  const spare = collectionSparePlugId(members);
  const itemsPort = data.spec.inputs.find(
    (port) => port.name === COLLECTION_PORT,
  );
  const outputPort = data.spec.outputs[0];
  const artifactType = itemsPort
    ? resolvedPortArtifactType(itemsPort, data.artifactTypeBindings)
    : null;
  const artifactTypes = useArtifactTypeCatalog();
  const contract = artifactType
    ? formatArtifactTypeSequence(
        formatArtifactTypeLabel(artifactType, artifactTypes),
      )
    : "Sequence";
  const contractTooltip = artifactType
    ? formatArtifactTypeSequenceTooltip(artifactType)
    : undefined;
  const color = artifactType
    ? artifactTypeColor(artifactType.id, tokens.colorAccent)
    : tokens.colorAccent;
  const refs = filled.flatMap((member) => [...memberRefs(member)]);
  const pending = filled.filter(
    (member) => member.kind === "output" && member.refs === null,
  );
  const title = `${refs.length} ${refs.length === 1 ? "item" : "items"}${
    pending.length ? ` · ${pending.length} waiting` : ""
  }`;
  const nameOf = (ref: ArtifactRef) => {
    const item = itemsById.get(ref.artifact_id);
    return item ? libraryFileDisplayName(item) : null;
  };
  const first = refs[0] ?? null;
  const pictures =
    first !== null &&
    isImageArtifact(
      first,
      itemsById.get(first.artifact_id)?.artifact.content_type,
    );

  const width = gridAlignedWidth(
    data.layout?.width ?? DEFAULT_ARTIFACT_CARD_WIDTH,
    grid?.settings,
    grid?.bypassSnap,
    150,
  );
  const stackDepth = Math.min(refs.length, 3);
  const firstSize = first ? imageSizes[first.artifact_id] : undefined;
  const aspect = firstSize ? firstSize.width / firstSize.height : 4 / 3;
  const mediaHeight = Math.round(
    (width - Math.max(0, stackDepth - 1) * 12) / aspect,
  );

  const plugHandle = (plugId: string) =>
    itemsPort
      ? encodeHandleId(
          portMetaForPort(
            itemsPort,
            itemsPort.shape,
            plugId,
            data.artifactTypeBindings,
          ),
        )
      : "";
  const outputHandle = outputPort
    ? encodeHandleId(
        portMetaForPort(
          outputPort,
          outputPort.shape,
          undefined,
          data.artifactTypeBindings,
        ),
      )
    : "";

  const bindingRevision = JSON.stringify(data.artifactTypeBindings);
  const plugRevision = members.map((member) => member.plugId).join("|");
  const onHandlesMeasured = data.onHandlesMeasured;
  const measuredBindings = data.artifactTypeBindings;
  React.useLayoutEffect(() => {
    // Binding T renames every handle; publish readiness only after React Flow
    // has measured the renamed ones, as operator nodes do.
    updateNodeInternals(id);
    const frame = window.requestAnimationFrame(() =>
      onHandlesMeasured?.(id, measuredBindings),
    );
    return () => window.cancelAnimationFrame(frame);
  }, [
    bindingRevision,
    plugRevision,
    mediaHeight,
    managing,
    id,
    measuredBindings,
    onHandlesMeasured,
    updateNodeInternals,
  ]);

  const editable = Boolean(data.onRemoveInputPlug);
  // Members are listed without empty plugs, but plugs reorder by their own
  // index: move to where the neighbouring member's plug sits.
  const moveMember = (plugId: string, toMemberIndex: number) => {
    const neighbour = filled[toMemberIndex];
    if (!neighbour) return;
    const toPlugIndex = members.findIndex(
      (candidate) => candidate.plugId === neighbour.plugId,
    );
    if (toPlugIndex < 0) return;
    data.onReorderInputPlug?.(id, COLLECTION_PORT, plugId, toPlugIndex);
  };
  const libraryCount = filled.filter((m) => m.kind === "library").length;
  const outputCount = filled.length - libraryCount;
  const items: NodeMenuItem[] = [
    {
      id: "members",
      label: managing ? "Hide members" : "Reorder members",
      icon: <ArrowUpDown size={13} />,
      disabled: filled.length === 0,
      onClick: () => setManaging((open) => !open),
    },
    {
      id: "ungroup",
      label: "Ungroup",
      icon: <Ungroup size={13} />,
      disabled:
        !data.onUngroupCollection || Boolean(data.ungroupDisabledReason),
      onClick: () => data.onUngroupCollection?.(id),
    },
    {
      id: "remove",
      label: "Remove from canvas",
      icon: <Trash2 size={13} />,
      danger: true,
      disabled: !data.onRemoveNode,
      onClick: () => data.onRemoveNode?.(id),
    },
  ];

  const actions = stylex.props(
    artifactRail.actions,
    revealStyles(active, "output"),
  );
  // Every member's edge ends on the one input ball, so the ball stays out while
  // any member is wired in.
  const membersWired = filled.some((member) =>
    portReveal.connected.has(plugHandle(member.plugId)),
  );

  const tileStyle = [
    s.tile,
    tier === "active" ? s.tileRaised : null,
    tier === "dragged" ? s.tileDragged : null,
  ];

  return (
    <PortRevealProvider value={portReveal}>
      <div
        ref={liftRef}
        {...holdHandlers}
        data-collection-card-id={id}
        data-testid="collection-card"
        role="group"
        aria-label={`Collection ${contract}`}
        {...stylex.props(
          s.card,
          tier === "active" ? s.cardActive : null,
          tier === "dragged" ? s.cardDragged : null,
        )}
        style={{ width }}
      >
        <div {...stylex.props(s.frame)}>
          <ArtifactLabel
            title={title}
            contract={contract}
            contractTooltip={contractTooltip}
            selected={Boolean(selected)}
          />
          <div
            data-artifact-body="true"
            // A Library drop onto the stack lands on the spare plug.
            data-input-node-id={spare ? id : undefined}
            data-input-plug-port={spare ? COLLECTION_PORT : undefined}
            data-input-plug-id={spare ?? undefined}
            {...stylex.props(s.body)}
          >
            <div
              data-artifact-rail="left"
              {...stylex.props(artifactRail.rail, artifactRail.left)}
            >
              {spare ? (
                <span key={spare} {...stylex.props(s.stacked, s.spare)}>
                  <PortBall
                    nodeId={id}
                    handleId={plugHandle(spare)}
                    side="input"
                    color={color}
                    sequence
                    revealed={active || portReveal.connecting || membersWired}
                    isConnectable={editable}
                    ariaLabel="Add to collection"
                    title="Wire an output or a card here to add it to the collection"
                    slotProps={{ "data-collection-spare": "true" }}
                  />
                </span>
              ) : null}
              {filled.map((member, index) => (
                <span key={member.plugId} {...stylex.props(s.stacked)}>
                  <PortBall
                    nodeId={id}
                    handleId={plugHandle(member.plugId)}
                    side="input"
                    color={color}
                    sequence
                    revealed
                    // Its edge meets the spare's ring, drawn in the same place.
                    docked
                    isConnectable={false}
                    ariaLabel={`Collection member ${index + 1}`}
                  />
                </span>
              ))}
            </div>
            <div
              data-artifact-rail="right"
              {...stylex.props(artifactRail.rail, artifactRail.right)}
            >
              <div
                data-artifact-chrome={active ? "on" : "off"}
                {...actions}
                className={`nodrag nopan ${actions.className ?? ""}`}
                style={revealDelay(0)}
              >
                <NodeMenu
                  label={`Actions for ${contract}`}
                  title="Collection info and actions"
                  info={{
                    title: "Collection",
                    lines: [
                      contract,
                      `${libraryCount} from the Library · ${outputCount} from outputs`,
                      ...(pending.length
                        ? [`${pending.length} waiting for a run`]
                        : []),
                    ],
                  }}
                  items={items}
                  onOpenChange={setMenuOpen}
                />
              </div>
              <div {...stylex.props(artifactRail.output)}>
                {outputPort ? (
                  <PortBall
                    nodeId={id}
                    handleId={outputHandle}
                    side="output"
                    color={color}
                    sequence
                    order={1}
                    isConnectable={filled.length > 0}
                    idle={filled.length === 0}
                    ariaLabel={`Connect ${contract} to a node input`}
                    title="Connect the collection to a compatible input"
                  />
                ) : null}
              </div>
            </div>
            {!selected && data.remoteSelectionColor ? (
              <RemoteSelectionRing
                color={data.remoteSelectionColor}
                radius={5}
              />
            ) : null}
            {pictures ? (
              <ImageArtifactBody
                images={refs.map((ref, index) => ({
                  id: ref.artifact_id,
                  url: artifactInlineContentUrl(workspace.id, ref.artifact_id),
                  name: nameOf(ref) ?? `Item ${index + 1}`,
                  failed: imagesFailed[ref.artifact_id] ?? false,
                }))}
                sequence
                mediaHeight={mediaHeight}
                selected={Boolean(selected)}
                tier={tier}
                onSize={(artifactId, w, h) =>
                  setImageSizes((current) =>
                    current[artifactId]?.width === w &&
                    current[artifactId]?.height === h
                      ? current
                      : { ...current, [artifactId]: { width: w, height: h } },
                  )
                }
                onError={(artifactId) =>
                  setImagesFailed((current) => ({
                    ...current,
                    [artifactId]: true,
                  }))
                }
              />
            ) : (
              <div
                {...stylex.props(s.tiles)}
                style={{ height: 80 + Math.max(0, stackDepth - 1) * 8 }}
              >
                {refs.length === 0 ? (
                  <div
                    {...stylex.props(...tileStyle, s.tileEmpty)}
                    style={{ inset: 0 }}
                  >
                    {pending.length ? (
                      <>
                        <LoaderCircle size={13} {...stylex.props(s.spinner)} />
                        <span {...stylex.props(s.tileText)}>
                          Waiting for{" "}
                          {pending[0]?.kind === "output"
                            ? pending[0].label
                            : "outputs"}
                        </span>
                      </>
                    ) : (
                      <span>Wire outputs or drop artifacts here</span>
                    )}
                  </div>
                ) : (
                  refs.slice(0, 3).map((ref, index) => (
                    <div
                      key={`${index}:${ref.artifact_id}`}
                      {...stylex.props(...tileStyle)}
                      style={{
                        width: `calc(100% - ${(stackDepth - 1) * 12}px)`,
                        left: (stackDepth - 1 - index) * 12,
                        top: index * 8,
                        zIndex: stackDepth - index,
                      }}
                    >
                      <FileIcon size={20} />
                      <span {...stylex.props(s.tileText)}>
                        {nameOf(ref) ?? ref.artifact_type}
                      </span>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        </div>
        {data.execution.status === "failed" && data.execution.error ? (
          <p role="status" {...stylex.props(s.error)}>
            {data.execution.error}
          </p>
        ) : null}
        {managing && filled.length ? (
          <div
            className="nodrag nopan nowheel"
            {...stylex.props(s.members)}
            role="list"
            aria-label="Collection members"
          >
            <span {...stylex.props(s.membersHead)}>
              <span>{filled.length} members · in the order they pass on</span>
              <button
                type="button"
                aria-label="Close members"
                {...stylex.props(s.step)}
                onClick={() => setManaging(false)}
              >
                <X size={12} />
              </button>
            </span>
            {filled.map((member, index) => {
              const shown = memberRefs(member)[0];
              const picture =
                shown &&
                isImageArtifact(
                  shown,
                  itemsById.get(shown.artifact_id)?.artifact.content_type,
                ) &&
                !imagesFailed[shown.artifact_id];
              const name =
                member.kind === "library"
                  ? ((shown && nameOf(shown)) ??
                    (member.refs.length > 1
                      ? `${member.refs.length} artifacts`
                      : (shown?.artifact_type ?? "Artifact")))
                  : member.kind === "output"
                    ? member.label
                    : "";
              const source =
                member.kind === "library"
                  ? "Library"
                  : member.kind === "output" && member.refs === null
                    ? "Output · waiting for a run"
                    : "Output";
              return (
                <div
                  role="listitem"
                  key={member.plugId}
                  {...stylex.props(s.member)}
                >
                  <span {...stylex.props(s.memberIndex)}>{index + 1}</span>
                  {picture ? (
                    /* eslint-disable-next-line @next/next/no-img-element -- workspace artifact bytes bypass the public image optimizer */
                    <img
                      src={artifactInlineContentUrl(
                        workspace.id,
                        shown.artifact_id,
                      )}
                      alt=""
                      loading="lazy"
                      decoding="async"
                      draggable={false}
                      {...stylex.props(s.memberThumb)}
                    />
                  ) : (
                    <span {...stylex.props(s.memberThumb)}>
                      {member.kind === "output" && member.refs === null ? (
                        <LoaderCircle size={13} {...stylex.props(s.spinner)} />
                      ) : (
                        <FileIcon size={14} />
                      )}
                    </span>
                  )}
                  <span {...stylex.props(s.memberCopy)}>
                    <span title={name} {...stylex.props(s.memberName)}>
                      {name}
                    </span>
                    <span {...stylex.props(s.memberSource)}>{source}</span>
                  </span>
                  <button
                    type="button"
                    disabled={!editable || index === 0}
                    aria-label={`Move member ${index + 1} earlier`}
                    {...stylex.props(s.step)}
                    onClick={() => moveMember(member.plugId, index - 1)}
                  >
                    <ArrowUp size={11} />
                  </button>
                  <button
                    type="button"
                    disabled={!editable || index === filled.length - 1}
                    aria-label={`Move member ${index + 1} later`}
                    {...stylex.props(s.step)}
                    onClick={() => moveMember(member.plugId, index + 1)}
                  >
                    <ArrowDown size={11} />
                  </button>
                  <button
                    type="button"
                    disabled={!editable}
                    aria-label={`Remove member ${index + 1}`}
                    {...stylex.props(s.step, s.stepDanger)}
                    onClick={() => data.onRemoveInputPlug?.(id, member.plugId)}
                  >
                    <Trash2 size={11} />
                  </button>
                </div>
              );
            })}
          </div>
        ) : null}
      </div>
    </PortRevealProvider>
  );
}
