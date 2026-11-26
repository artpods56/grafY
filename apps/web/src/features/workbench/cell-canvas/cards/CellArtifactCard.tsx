"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  BookmarkPlus,
  CopyPlus,
  Download,
  FileText,
  Layers,
  Link,
  Link2,
  Map as MapIcon,
  Pencil,
  Plus,
  ScanSearch,
  Ungroup,
  X,
} from "lucide-react";
import useSWR from "swr";

import { Button, IconButton } from "@/components/ui/button";
import { artifactTypeColor } from "@/features/workbench/config-ui/nodes.css";
import { COLLECTION_PORT } from "@/features/workbench/authoring/collection-spec";
import { artifactInlineContentUrl, type ArtifactRef } from "@/lib/api";
import { imagePath, imageThumbnailUrl } from "@/lib/api/images";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { GeoMapArtifactRenderer } from "../../artifacts/geo-map-artifact-renderer";
import { SafeMarkdown } from "../../artifacts/safe-markdown";
import { TiffArtifactView } from "../../artifacts/TiffArtifactView";
import {
  cardTextKey,
  cardTextLimit,
  fetchCardText,
  formatCardText,
} from "../../artifacts/artifact-renderers/card-text";
import { CardTextBody } from "../../artifacts/artifact-renderers/card-text-body";
import { HtmlPageFill } from "../../artifacts/artifact-renderers/html-page-fill";
import { useHtmlPage } from "../../artifacts/artifact-renderers/html-page";
import { ImageCardPreview } from "../../artifacts/artifact-renderers/image-card-preview";
import { TableArtifactRenderer } from "../../artifacts/artifact-renderers/table-renderer";
import { TiffTextArtifact } from "../../artifacts/artifact-renderers/tiff-text-renderer";
import type { ArtifactViewerInteractionContext } from "../../artifacts/artifact-interactions";
import {
  useSelectionLinksContext,
  type SelectionLinkMenuItem,
} from "../../artifacts/selection-links/SelectionLinksContext";

import type {
  ArtifactCardSurfaceData,
  CollectionCardSurfaceData,
  InlineArtifactEditingProps,
} from "../cell-contracts";
import { cellCornerRadius, type CellStackStyle } from "../cell-glass-stage";
import {
  ARTIFACT_CARD_OUTPUT_PORT_ID,
  artifactCardOutputRow,
  CARD_PLATE_BOTTOM_INSET,
  CARD_PLATE_INSET_X,
  CARD_PLATE_TOP,
  CELL_SIZE,
  collectionRowOffset,
  punchedPortCardCentre,
} from "../cell-model";
import { shouldAnimateMotion } from "../cell-transitions";
import { PUNCHED_LABEL_INSET } from "../punched-port";
import {
  CellCardShell,
  cellCardMarks as m,
  plateRowTop,
  punchedHoleMask,
  stopCardDrag,
  styled,
  useResolvedCardState,
  type CellCardBaseProps,
  type CellCardMenuItem,
} from "./CellOperatorCard";

/**
 * Artifact and collection cards on the cell canvas. Both are whole-cell
 * boxes with the shared card shell: their ports sit on the card's own edges,
 * in the glass stage's wells, with no rail floating outside the card. With
 * punched wells the shell drills each port through the plate instead: over an
 * artifact's preview the hole is cut clean through, so the canvas shows in
 * it, and a collection's rows start past it.
 */

const MONO_FONT =
  "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace";

/**
 * Card backs a sequence fans under its plate, pinned through the output's
 * corner hole like a swatch deck. Each turns counter-clockwise about the hole
 * by `maxDegrees`, or less on a wide card, so its far corner never swings more
 * than `swing` px out from under the plate.
 */
const STACK_BACKS = [
  { maxDegrees: 1.8, swing: 6 },
  { maxDegrees: 3.6, swing: 12 },
] as const;

/**
 * Card backs a `deck` stack lays straight under its plate: each steps down
 * and narrows a little about the plate's bottom centre, so its lower edge
 * shows below the plate and its sides tuck in.
 */
const DECK_BACKS = [
  { dropY: 6, scale: 0.96 },
  { dropY: 12, scale: 0.92 },
] as const;

/** How many backs a stack draws at most. */
export const STACK_BACK_COUNT = STACK_BACKS.length;

/** How long a back that is no longer needed folds back under the plate. */
export const STACK_BACK_EXIT_MS = 180;

/** How long a stack that took a card settles. */
const STACK_REBOUND_MS = 260;

const MOTION_EASE = "cubic-bezier(0.22, 1, 0.36, 1)";

const stackBackIn = stylex.keyframes({
  from: { transform: "none" },
});

const stackBackOut = stylex.keyframes({
  to: { transform: "none", opacity: 0 },
});

const stackRebound = stylex.keyframes({
  "0%": { transform: "none" },
  "35%": { transform: "translateY(1.5px) scale(0.992)" },
  "70%": { transform: "translateY(-0.5px) scale(1.002)" },
  "100%": { transform: "none" },
});

interface StackBackGeometry {
  plateWidth: number;
  plateHeight: number;
  /** The output's corner hole, in the plate's own box. */
  pin: { x: number; y: number };
}

function stackBackGeometry(
  card: Pick<CellArtifactCardProps["card"], "widthCells" | "heightCells">,
): StackBackGeometry {
  const plateWidth = card.widthCells * CELL_SIZE - CARD_PLATE_INSET_X * 2;
  const plateHeight =
    card.heightCells * CELL_SIZE - CARD_PLATE_TOP - CARD_PLATE_BOTTOM_INSET;
  const hole = punchedPortCardCentre(card, stackOutputPort(card));
  return {
    plateWidth,
    plateHeight,
    pin: { x: hole.x - CARD_PLATE_INSET_X, y: hole.y - CARD_PLATE_TOP },
  };
}

/** The same corner hole the output port is drawn in. */
function stackOutputPort(
  card: Pick<CellArtifactCardProps["card"], "heightCells">,
) {
  return {
    id: ARTIFACT_CARD_OUTPUT_PORT_ID,
    direction: "output",
    rowOffset: artifactCardOutputRow(card.heightCells),
  } as const;
}

/**
 * Where a card back lies at continuous depth `depth` in `[0, STACK_BACK_COUNT]`
 * (0 flush behind the top plate, 1 = back #1, 2 = back #2).
 */
export function stackDepthTransform(
  card: Pick<CellArtifactCardProps["card"], "widthCells" | "heightCells">,
  stackStyle: CellStackStyle,
  depth: number,
): { transform: string; transformOrigin: string } {
  const d = Math.max(0, Math.min(STACK_BACK_COUNT, depth));
  const geometry = stackBackGeometry(card);
  if (stackStyle === "deck") {
    const { dropY, scale } = DECK_BACKS[0];
    const y = Number((dropY * d).toFixed(2));
    const k = Number((1 - (1 - scale) * d).toFixed(4));
    return {
      transform: `translate3d(0px, ${y}px, 0) scale(${k})`,
      transformOrigin: "center bottom",
    };
  }
  const { maxDegrees, swing } = STACK_BACKS[0];
  const unitDegrees = Math.min(
    maxDegrees,
    (Math.atan(swing / geometry.plateWidth) * 180) / Math.PI,
  );
  return {
    transform: `rotate(${-Number((unitDegrees * d).toFixed(2))}deg)`,
    transformOrigin: `${geometry.pin.x}px ${geometry.pin.y}px`,
  };
}

/**
 * Where the `slot`th back (0 nearest the plate) lies under a plate of this
 * card's size, `progress` of the way out from rest (0) to its place (1): its
 * transform and the origin it turns or scales about, in the plate's box.
 */
export function stackBackTransform(
  card: Pick<CellArtifactCardProps["card"], "widthCells" | "heightCells">,
  stackStyle: CellStackStyle,
  slot: number,
  progress = 1,
): { transform: string; transformOrigin: string } {
  const t = Math.max(0, Math.min(1, progress));
  const targetDepth = slot <= 0 ? 1 : 2;
  return stackDepthTransform(card, stackStyle, targetDepth * t);
}

// StyleX evaluates these at build time, so they are plain strings, not calls.
const IMAGE_HAIRLINE =
  "inset 0 0 0 1px light-dark(color-mix(in srgb, black 9%, transparent), color-mix(in srgb, white 10%, transparent))";
const STACK_BACK_SHADOW =
  "0 1px 2px light-dark(color-mix(in srgb, black 10%, transparent), color-mix(in srgb, black 45%, transparent))";

const s = stylex.create({
  stripLabel: {
    flexShrink: 0,
    color: tokens.colorMuted,
    fontWeight: 500,
  },
  // The file name takes what the type's title leaves, flush right against
  // the "⋯", and is the one that ellipsizes.
  headerMeta: {
    flexGrow: 1,
    flexShrink: 1,
    flexBasis: 0,
    minWidth: 0,
    overflow: "hidden",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "flex-end",
    textAlign: "right",
    gap: "5px",
    paddingInline: "2px 4px",
    color: tokens.colorSubtle,
    fontFamily: MONO_FONT,
    fontSize: "10px",
    whiteSpace: "nowrap",
  },
  // Every kind fills the plate: no strip sits above it.
  preview: {
    position: "absolute",
    inset: 0,
    overflow: "hidden",
  },
  // Non-interactive faces (spread side stacks, transition clones) never capture pointers.
  previewStatic: {
    pointerEvents: "none",
  },
  // Sits in the plate, clear of the output well on the card's right edge.
  nextStep: {
    position: "absolute",
    left: "8px",
    bottom: "8px",
    zIndex: 2,
  },
  // A frame drawn over the picture, inside the plate's border, so a white
  // scan on a white plate still has an edge in both themes.
  imageFrame: {
    position: "absolute",
    inset: 0,
    borderRadius: "inherit",
    boxShadow: IMAGE_HAIRLINE,
    pointerEvents: "none",
  },
  stackBack: {
    position: "absolute",
    boxSizing: "border-box",
    overflow: "hidden",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    backgroundColor: tokens.colorSurfaceRaised,
    boxShadow: STACK_BACK_SHADOW,
    pointerEvents: "none",
  },
  stackPeek: {
    position: "absolute",
    inset: 0,
    width: "100%",
    height: "100%",
    objectFit: "cover",
    opacity: 0.55,
    pointerEvents: "none",
    userSelect: "none",
  },
  // A sequence's count sits in the header's right slot as quiet monospace
  // typography matching a single card's file name — bare at rest, softly
  // highlighted on hover when clickable.
  // A back that came in with a new item swings out from under the plate.
  stackBackEnter: {
    animationName: stackBackIn,
    animationDuration: {
      default: "200ms",
      "@media (prefers-reduced-motion: reduce)": "0s",
    },
    animationTimingFunction: MOTION_EASE,
  },
  // A back the stack no longer needs folds back under the plate and fades.
  stackBackExit: {
    animationName: stackBackOut,
    animationDuration: {
      default: `${STACK_BACK_EXIT_MS}ms`,
      "@media (prefers-reduced-motion: reduce)": "0s",
    },
    animationTimingFunction: MOTION_EASE,
    animationFillMode: "forwards",
  },
  // The plate lifts and lowers smoothly when a dragged card hovers over it.
  plateMotion: {
    transitionProperty: "transform",
    transitionDuration: {
      default: "200ms",
      "@media (prefers-reduced-motion: reduce)": "0ms",
    },
    transitionTimingFunction: MOTION_EASE,
  },
  plateRebound: {
    animationName: stackRebound,
    animationDuration: {
      default: `${STACK_REBOUND_MS}ms`,
      "@media (prefers-reduced-motion: reduce)": "0s",
    },
    animationTimingFunction: MOTION_EASE,
  },
  stackCount: {
    flexShrink: 0,
    display: "inline-flex",
    alignItems: "center",
    height: "18px",
    margin: 0,
    paddingInline: "5px",
    boxSizing: "border-box",
    borderWidth: 0,
    borderStyle: "none",
    borderRadius: tokens.radiusSm,
    backgroundColor: "transparent",
    color: tokens.colorSubtle,
    fontFamily: MONO_FONT,
    fontSize: "10px",
    fontWeight: 500,
    lineHeight: 1,
    whiteSpace: "nowrap",
  },
  // The count lays the sequence open, so it takes the pointer as a bare button.
  stackCountButton: {
    cursor: {
      default: "pointer",
      ":disabled": "not-allowed",
    },
    opacity: {
      default: 1,
      ":disabled": 0.48,
    },
    color: {
      default: tokens.colorSubtle,
      ":hover:not(:disabled)": tokens.colorText,
    },
    backgroundColor: {
      default: "transparent",
      ":hover:not(:disabled)": tokens.colorHover,
    },
    outline: {
      default: "none",
      ":focus-visible": `2px solid ${tokens.colorAccentBorder}`,
    },
    transitionProperty: "background-color, color",
    transitionDuration: {
      default: "120ms",
      "@media (prefers-reduced-motion: reduce)": "0ms",
    },
  },
  stackCountExpanded: {
    color: tokens.colorText,
    backgroundColor: tokens.colorAccentSoft,
  },
  checker: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: tokens.colorSurfaceSunken,
    backgroundImage: `repeating-conic-gradient(${tokens.colorSurfaceRaised} 0% 25%, transparent 0% 50%)`,
    backgroundSize: "14px 14px",
  },
  placeholderMeta: {
    fontFamily: MONO_FONT,
    fontSize: "9px",
  },
  table: {
    width: "100%",
    borderCollapse: "collapse",
    tableLayout: "fixed",
    fontFamily: MONO_FONT,
    fontSize: "9.5px",
    lineHeight: 1.4,
    color: tokens.colorText,
  },
  th: {
    position: "sticky",
    top: 0,
    paddingBlock: "3px",
    paddingInline: "6px",
    backgroundColor: tokens.colorSurfaceSunken,
    color: tokens.colorMuted,
    fontWeight: 600,
    textAlign: "left",
    borderBottomWidth: "1px",
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  td: {
    paddingBlock: "2px",
    paddingInline: "6px",
    borderBottomWidth: "1px",
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  cellDivider: {
    borderLeftWidth: "1px",
    borderLeftStyle: "solid",
    borderLeftColor: tokens.colorDivider,
  },
  reading: {
    boxSizing: "border-box",
    height: "100%",
    paddingBlock: "8px",
    paddingInline: "10px",
    color: tokens.colorText,
    fontSize: "10.5px",
    lineHeight: 1.5,
    overflowWrap: "anywhere",
  },
  readingLine: { margin: 0, minHeight: "1em" },
  readingHeading: { fontWeight: 600, fontSize: "11.5px" },
  readingBullet: { paddingLeft: "10px" },
  fileBody: {
    boxSizing: "border-box",
    height: "100%",
    display: "flex",
    alignItems: "center",
    gap: "10px",
    paddingInline: "12px",
  },
  fileIcon: {
    flexShrink: 0,
    width: "34px",
    height: "40px",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    borderRadius: tokens.radiusSm,
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    backgroundColor: tokens.colorSurfaceSunken,
    color: tokens.colorMuted,
  },
  fileText: {
    minWidth: 0,
    display: "flex",
    flexDirection: "column",
    gap: "2px",
  },
  fileName: {
    fontSize: tokens.fontSizeXs,
    fontWeight: 500,
    color: tokens.colorText,
  },
  fileMeta: {
    fontFamily: MONO_FONT,
    fontSize: "9.5px",
    color: tokens.colorSubtle,
  },
  map: {
    position: "relative",
    backgroundColor: tokens.colorSurfaceSunken,
  },
  mapArt: {
    position: "absolute",
    inset: 0,
    width: "100%",
    height: "100%",
  },
  mapLegend: {
    position: "absolute",
    left: "8px",
    right: "8px",
    bottom: "6px",
    display: "flex",
    alignItems: "center",
    gap: "6px",
    color: tokens.colorMuted,
    fontSize: "9.5px",
  },
  mapCaption: {
    position: "absolute",
    top: "6px",
    left: "8px",
    right: "8px",
    color: tokens.colorSubtle,
    fontSize: "9.5px",
  },

  memberRow: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
    paddingInline: "10px 6px",
    borderBottomWidth: "1px",
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
    fontSize: tokens.fontSizeXs,
  },
  memberText: {
    minWidth: 0,
    flexGrow: 1,
    flexBasis: 0,
    display: "flex",
    flexDirection: "column",
    gap: "1px",
  },
  memberLabel: { color: tokens.colorText },
  memberType: { color: tokens.colorSubtle, fontSize: "9.5px" },
  memberMeta: {
    flexShrink: 0,
    color: tokens.colorSubtle,
    fontFamily: MONO_FONT,
    fontSize: "9.5px",
  },
  spareRow: {
    display: "flex",
    alignItems: "center",
    paddingBlock: "8px",
    paddingInline: "10px",
  },
  spareSlot: {
    flexGrow: 1,
    height: "100%",
    boxSizing: "border-box",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "4px",
    borderWidth: "1px",
    borderStyle: "dashed",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusSm,
    color: tokens.colorSubtle,
    fontSize: "10px",
  },
});

function TypeDot({ artifactTypeId }: { artifactTypeId: string }) {
  return (
    <span
      aria-hidden="true"
      {...styled(
        {
          backgroundColor: artifactTypeColor(artifactTypeId, tokens.colorMuted),
        },
        m.dot,
      )}
    />
  );
}

// --- Artifact card ---------------------------------------------------------

export interface CellArtifactCardProps
  extends CellCardBaseProps, InlineArtifactEditingProps {
  surface: ArtifactCardSurfaceData;
  onInspect?: (cardId: string) => void;
  onDownload?: (cardId: string, format: string | null) => void;
  onSaveToLibrary?: (cardId: string) => void;
  /** Opens the editor for a standalone authorable artifact. */
  onEdit?: (cardId: string) => void;
  /** Opens duplicate-and-edit for a producer-linked authorable artifact. */
  onDuplicateAndEdit?: (cardId: string) => void;
  /** Opens the list of steps this card's one output can feed. */
  onNextStep?: () => void;
  /** Lays a sequence open in place, from its count or its menu. */
  onExpandSequence?: (cardId: string) => void;
  /** Adds "Ungroup" to a sequence's menu: each item onto its own card. */
  onUngroup?: (cardId: string) => void;
  /** The sequence is laid open over this card. */
  sequenceExpanded?: boolean;
  /**
   * False when the card is boxed in too tightly to spread its items: the
   * count and the menu item stay, disabled, and say why. Defaults to true.
   */
  canExpandSequence?: boolean;
  /** How the stack draws its backs; defaults to `fan`. */
  stackStyle?: CellStackStyle;
  /** A dragged card would join this one if released now: its plate lifts. */
  mergeHover?: boolean;
  /** This card is held over another it would join: it readies to tuck under. */
  merging?: boolean;
  /** Reports an image's natural pixel dimensions once decoded, for auto-fit sizing. */
  onImageLoad?: (
    imageUrl: string,
    size: { width: number; height: number },
  ) => void;
}

const BOXED_IN_HINT = "Move card into open space to spread";

function CellArtifactCardImpl(props: CellArtifactCardProps) {
  const {
    card,
    surface,
    onInspect,
    onEdit,
    onDuplicateAndEdit,
    onExpandSequence,
    onUngroup,
  } = props;
  const sequenceExpanded = props.sequenceExpanded ?? false;
  const canExpandSequence = props.canExpandSequence ?? true;
  const state = useResolvedCardState(card.id, props);
  const selectionLinks = useSelectionLinksContext();
  const image = surface.previewKind === "image";
  const stackable = image || surface.previewKind === "tiff";
  const itemCount = surface.itemCount ?? 1;
  const sequence = itemCount > 1;
  const stacked = stackable && sequence;
  const stackStyle = props.stackStyle ?? "fan";
  const rebounding = useStackRebound(itemCount);
  // The title names the type; the header's right side names the file, or
  // failing that its one measure. A sequence says its count there instead,
  // so the picture itself stays clean.
  const measure = surface.dimensionsLabel ?? surface.byteSizeLabel;
  const headerLabel = surface.filename ?? measure ?? null;
  const artifactItems = artifactMenuItems({
    cardId: card.id,
    surface,
    sequence,
    canExpandSequence,
    authoringAction: artifactCardAuthoringAction({
      authorable: surface.authorable === true,
      producerLinked: surface.producerLinked === true,
      itemCount,
      hasArtifact: surface.artifact != null,
    }),
    onInspect,
    onDownload: props.onDownload,
    onSaveToLibrary: props.onSaveToLibrary,
    onEdit,
    onDuplicateAndEdit,
    onExpandSequence,
    onUngroup,
  });
  const linkItems: CellCardMenuItem[] = (
    selectionLinks?.menuItemsFor(card.id) ?? []
  ).map((item: SelectionLinkMenuItem): CellCardMenuItem => ({
    id: item.id,
    label: item.label,
    onSelect: item.onSelect,
    icon:
      item.id === "selection-link-new" ? (
        <Link2 size={13} />
      ) : (
        <Link size={13} />
      ),
  }));

  let headerMeta: React.ReactNode = null;
  if (sequence) {
    headerMeta = (
      <span data-card-meta="true" {...stylex.props(s.headerMeta)}>
        <StackCount
          cardId={card.id}
          itemCount={itemCount}
          expanded={sequenceExpanded}
          canExpand={canExpandSequence}
          onExpand={onExpandSequence}
        />
      </span>
    );
  } else if (headerLabel) {
    headerMeta = (
      <span
        data-card-meta="true"
        title={headerLabel}
        {...stylex.props(s.headerMeta)}
      >
        <span {...stylex.props(m.ellipsis)}>{headerLabel}</span>
      </span>
    );
  }

  return (
    <CellCardShell
      {...props}
      kind="artifact"
      state={state}
      resizable={card.resizable ?? true}
      headerMeta={headerMeta}
      plateStyle={plateLift(card, stackStyle, props.mergeHover, props.merging)}
      plateXstyle={[s.plateMotion, rebounding && s.plateRebound]}
      rootData={{
        "data-artifact-type": surface.artifactTypeId,
        "data-stack-style": stackStyle,
        "data-merge-hover": props.mergeHover ? "true" : "false",
        "data-merging": props.merging ? "true" : "false",
        "data-stack-rebound": rebounding ? "true" : "false",
      }}
      behindPlate={
        // Drawn for every picture, so a back that leaves can fold away.
        stackable ? (
          <ArtifactStackBacks
            card={card}
            corners={props.corners ?? "rounded"}
            punched={props.well === "punched"}
            peeks={surface.stackImageUrls ?? []}
            backs={stacked ? Math.min(STACK_BACKS.length, itemCount - 1) : 0}
            stackStyle={stackStyle}
          />
        ) : null
      }
      menuDetail={surface.typeLabel}
      menuItems={
        linkItems.length > 0
          ? [...(artifactItems ?? []), ...linkItems]
          : artifactItems
      }
    >
      <ArtifactPlatePreview
        card={card}
        surface={surface}
        selected={state.selected}
        interaction={
          (surface.itemCount ?? 1) <= 1
            ? selectionLinks?.interactionFor(card.id)
            : undefined
        }
        onImageLoad={props.onImageLoad}
        inlineEditingCardId={props.inlineEditingCardId}
        onSetInlineEditingCardId={props.onSetInlineEditingCardId}
        onInlineArtifactSaved={props.onInlineArtifactSaved}
      />
      {props.onNextStep ? (
        <Button
          type="button"
          variant="secondary"
          size="xs"
          xstyle={s.nextStep}
          onPointerDown={stopCardDrag}
          onClick={(event) => {
            event.stopPropagation();
            props.onNextStep?.();
          }}
        >
          + Next step
        </Button>
      ) : null}
    </CellCardShell>
  );
}

/**
 * The plate's pose while a drag hovers: lifted as a target (opened about its
 * pin in a fan, raised off a deck), or drawn in to tuck under as the card
 * being dropped.
 */
function plateLift(
  card: CellArtifactCardProps["card"],
  stackStyle: CellStackStyle,
  mergeHover: boolean | undefined,
  merging: boolean | undefined,
): React.CSSProperties | undefined {
  const { pin } = stackBackGeometry(card);
  const pinOrigin = `${pin.x}px ${pin.y}px`;
  if (mergeHover) {
    return stackStyle === "deck"
      ? { transform: "translateY(-5px) scale(1.01)" }
      : {
          transform: "rotate(1.4deg) translateY(-2px)",
          transformOrigin: pinOrigin,
        };
  }
  if (merging) {
    return stackStyle === "deck"
      ? { transform: "scale(0.95)" }
      : {
          transform: "rotate(-1.6deg) scale(0.95)",
          transformOrigin: pinOrigin,
        };
  }
  return undefined;
}

/** True for a moment after the stack grows, while its plate settles. */
function useStackRebound(itemCount: number): boolean {
  const [seen, setSeen] = React.useState(itemCount);
  const [rebounding, setRebounding] = React.useState(false);
  if (itemCount !== seen) {
    setSeen(itemCount);
    setRebounding(itemCount > seen && shouldAnimateMotion());
  }
  React.useEffect(() => {
    if (!rebounding) return;
    const timer = window.setTimeout(
      () => setRebounding(false),
      STACK_REBOUND_MS,
    );
    return () => window.clearTimeout(timer);
  }, [rebounding]);
  return rebounding;
}

/**
 * A sequence's count in the header: the button that lays it open, disabled
 * with the reason when the card has no room to, or a quiet label when the
 * canvas offers no spread at all.
 */
function StackCount({
  cardId,
  itemCount,
  expanded,
  canExpand,
  onExpand,
}: {
  cardId: string;
  itemCount: number;
  expanded: boolean;
  canExpand: boolean;
  onExpand?: (cardId: string) => void;
}) {
  if (!onExpand) {
    return (
      <span
        data-artifact-stack-count={itemCount}
        data-sequence-expanded={expanded ? "true" : "false"}
        aria-label={`${itemCount} items`}
        {...stylex.props(s.stackCount)}
      >
        {itemCount} items
      </span>
    );
  }
  return (
    <button
      type="button"
      data-artifact-stack-count={itemCount}
      data-sequence-expanded={expanded ? "true" : "false"}
      aria-label={`Expand sequence (${itemCount} items)`}
      aria-expanded={expanded}
      disabled={!canExpand}
      title={
        canExpand ? "Spread to reorder, pull out or remove" : BOXED_IN_HINT
      }
      {...stylex.props(
        s.stackCount,
        s.stackCountButton,
        expanded && s.stackCountExpanded,
      )}
      onPointerDown={stopCardDrag}
      onClick={(event) => {
        event.stopPropagation();
        onExpand(cardId);
      }}
    >
      {itemCount} items
    </button>
  );
}

/** Edit vs duplicate-and-edit for a single authorable artifact on a card. */
export function artifactCardAuthoringAction(input: {
  authorable: boolean;
  producerLinked: boolean;
  itemCount: number;
  hasArtifact: boolean;
}): "edit" | "duplicate" | null {
  if (!input.authorable || !input.hasArtifact || input.itemCount !== 1) {
    return null;
  }
  return input.producerLinked ? "duplicate" : "edit";
}

/** What an artifact card's "⋯" menu offers beyond what every card has. */
export function artifactMenuItems({
  cardId,
  surface,
  sequence,
  canExpandSequence,
  authoringAction,
  onInspect,
  onDownload,
  onSaveToLibrary,
  onEdit,
  onDuplicateAndEdit,
  onExpandSequence,
  onUngroup,
}: {
  cardId: string;
  surface: ArtifactCardSurfaceData;
  sequence: boolean;
  canExpandSequence: boolean;
  authoringAction: "edit" | "duplicate" | null;
  onInspect?: (cardId: string) => void;
  onDownload?: (cardId: string, format: string | null) => void;
  onSaveToLibrary?: (cardId: string) => void;
  onEdit?: (cardId: string) => void;
  onDuplicateAndEdit?: (cardId: string) => void;
  onExpandSequence?: (cardId: string) => void;
  onUngroup?: (cardId: string) => void;
}): CellCardMenuItem[] | undefined {
  const items: CellCardMenuItem[] = [];
  if (authoringAction === "edit" && onEdit) {
    items.push({
      id: "edit",
      label: "Edit",
      icon: <Pencil size={13} />,
      onSelect: () => onEdit(cardId),
    });
  }
  if (authoringAction === "duplicate" && onDuplicateAndEdit) {
    items.push({
      id: "duplicate-edit",
      label: "Duplicate & Edit",
      icon: <CopyPlus size={13} />,
      onSelect: () => onDuplicateAndEdit(cardId),
    });
  }
  if (onInspect) {
    items.push({
      id: "inspect",
      label: "Inspect",
      icon: <ScanSearch size={13} />,
      onSelect: () => onInspect(cardId),
    });
  }
  const singleArtifact = surface.artifact && (surface.itemCount ?? 1) === 1;
  if (singleArtifact && surface.workspaceId && onDownload) {
    const formats = surface.downloadFormats;
    if (formats?.length) {
      for (const { format, label } of formats) {
        items.push({
          id: `download-${format}`,
          label: `Download ${label}`,
          icon: <Download size={13} />,
          onSelect: () => onDownload(cardId, format),
        });
      }
    } else {
      items.push({
        id: "download",
        label: "Download",
        icon: <Download size={13} />,
        onSelect: () => onDownload(cardId, null),
      });
    }
  }
  if (singleArtifact && onSaveToLibrary) {
    items.push({
      id: "save-to-library",
      label: surface.inLibrary ? "Saved in Library" : "Save to Library",
      icon: <BookmarkPlus size={13} />,
      disabled: surface.inLibrary,
      onSelect: () => onSaveToLibrary(cardId),
    });
  }
  if (sequence && onExpandSequence) {
    items.push({
      id: "expand-sequence",
      label: "Expand sequence",
      icon: <Layers size={13} />,
      disabled: !canExpandSequence,
      onSelect: () => onExpandSequence(cardId),
    });
  }
  if (sequence && onUngroup) {
    items.push({
      id: "ungroup",
      label: "Ungroup",
      icon: <Ungroup size={13} />,
      onSelect: () => onUngroup(cardId),
    });
  }
  return items.length ? items : undefined;
}

/**
 * The next items of a sequence, as card backs the plate's size under it. In a
 * `fan` they are pinned through the bottom-right punched hole and turned
 * counter-clockwise about it, so they peek out along the plate's left and
 * lower edges while the corner at the hole stays shared. In a `deck` they lie
 * straight, each a step lower and a little narrower, so their lower edges
 * show. A back shows a sliver of its own picture when one resolved.
 *
 * A back that arrives swings out from rest; one that is no longer needed
 * folds back under the plate before it goes.
 */
export function ArtifactStackBacks({
  card,
  corners,
  punched,
  peeks,
  backs,
  stackStyle = "fan",
  depthOffset = 0,
  depthScale = 1,
}: {
  card: CellArtifactCardProps["card"];
  corners: NonNullable<CellArtifactCardProps["corners"]>;
  /** The hole is real: it goes through every back too, at the pin. */
  punched: boolean;
  peeks: readonly string[];
  backs: number;
  stackStyle?: CellStackStyle;
  /** Continuous depth shift during a synced step glide (e.g. `p` or `1 - p`). */
  depthOffset?: number;
  /** Continuous depth scale in `[0, 1]` during a synced resize glide. */
  depthScale?: number;
}) {
  // Backs below `enterFrom` were there when the stack mounted: they do not
  // swing in. One that comes later, or comes back, does.
  const [enterFrom, setEnterFrom] = React.useState(backs);
  if (backs < enterFrom) setEnterFrom(backs);
  const drawn = useLingeringBackCount(backs);

  const springDriven = depthOffset !== 0 || depthScale !== 1;
  const clampedScale = Math.max(0, Math.min(1, depthScale));
  const { plateWidth, plateHeight } = stackBackGeometry(card);
  const output = stackOutputPort(card);
  const radius = cellCornerRadius(corners);
  const holeOrigin = { x: CARD_PLATE_INSET_X, y: CARD_PLATE_TOP };
  // The farthest back paints first, so the nearer one covers it.
  const slots = Array.from({ length: drawn }, (_, index) => index).reverse();
  return slots.map((index) => {
    const rawDepth = (index + 1) * clampedScale + depthOffset;
    const pose = springDriven
      ? stackDepthTransform(card, stackStyle, rawDepth)
      : stackBackTransform(card, stackStyle, index);
    const overflowOpacity =
      springDriven && rawDepth > STACK_BACK_COUNT
        ? Number(Math.max(0, 1 - (rawDepth - STACK_BACK_COUNT)).toFixed(3))
        : undefined;
    const exiting = !springDriven && index >= backs;
    const entering = !springDriven && index >= enterFrom;
    return (
      <span
        key={index}
        aria-hidden="true"
        data-artifact-stack-back={index + 1}
        data-stack-back-state={
          exiting ? "exiting" : entering ? "entering" : "rest"
        }
        {...styled(
          {
            top: CARD_PLATE_TOP,
            left: CARD_PLATE_INSET_X,
            width: plateWidth,
            height: plateHeight,
            borderRadius: radius,
            ...pose,
            ...(overflowOpacity !== undefined
              ? { opacity: overflowOpacity }
              : null),
            ...(punched
              ? punchedHoleMask(
                  card,
                  [output],
                  holeOrigin,
                  stackStyle === "deck"
                    ? deckHolePlacement(card, index)
                    : undefined,
                )
              : null),
          },
          s.stackBack,
          exiting ? s.stackBackExit : entering ? s.stackBackEnter : null,
        )}
      >
        {peeks[index] ? (
          // eslint-disable-next-line @next/next/no-img-element -- artifact bytes have no predictable size for the image optimizer
          <img
            src={peeks[index]}
            alt=""
            draggable={false}
            {...stylex.props(s.stackPeek)}
          />
        ) : null}
      </span>
    );
  });
}

/**
 * A fan turns each back about the hole, so in its own box the hole stays put.
 * A deck moves and scales its backs, so the hole is cut where the plate's hole
 * lands in the back's own (untransformed) box, wider by the scale.
 */
function deckHolePlacement(card: CellArtifactCardProps["card"], slot: number) {
  const { dropY, scale } = slot <= 0 ? DECK_BACKS[0] : DECK_BACKS[1];
  const { plateWidth, plateHeight } = stackBackGeometry(card);
  // Card-box coordinates of the deck's origin, the plate's bottom centre.
  const originX = CARD_PLATE_INSET_X + plateWidth / 2;
  const originY = CARD_PLATE_TOP + plateHeight;
  return {
    scale,
    centre: (hole: { x: number; y: number }) => ({
      x: originX + (hole.x - originX) / scale,
      y: originY + (hole.y - dropY - originY) / scale,
    }),
  };
}

/**
 * How many backs to draw: `backs`, or for a moment after it drops, the ones
 * that are leaving too, so they can fold away instead of vanishing.
 */
function useLingeringBackCount(backs: number): number {
  const [drawn, setDrawn] = React.useState(backs);
  if (backs > drawn || (backs < drawn && !shouldAnimateMotion())) {
    setDrawn(backs);
  }
  React.useEffect(() => {
    if (drawn <= backs) return;
    const timer = window.setTimeout(() => setDrawn(backs), STACK_BACK_EXIT_MS);
    return () => window.clearTimeout(timer);
  }, [backs, drawn]);
  return Math.max(backs, drawn);
}

function FileTile({
  card,
  surface,
}: {
  card: CellArtifactCardProps["card"];
  surface: ArtifactCardSurfaceData;
}) {
  return (
    <div {...stylex.props(s.fileBody)}>
      <span aria-hidden="true" {...stylex.props(s.fileIcon)}>
        <FileText size={18} />
      </span>
      <span {...stylex.props(s.fileText)}>
        <span {...stylex.props(s.fileName, m.ellipsis)}>
          {surface.filename ?? card.title}
        </span>
        <span {...stylex.props(s.fileMeta, m.ellipsis)}>
          {surface.typeLabel}
          {surface.byteSizeLabel ? ` · ${surface.byteSizeLabel}` : ""}
        </span>
      </span>
    </div>
  );
}

function LiveHtmlPage({
  workspaceId,
  artifactId,
  plateHeight,
  selected,
}: {
  workspaceId: string;
  artifactId: string;
  plateHeight: number;
  selected: boolean;
}) {
  const { data, mutate } = useHtmlPage(workspaceId, artifactId);
  return (
    <div
      onPointerDown={selected ? stopCardDrag : undefined}
      style={{ width: "100%", height: "100%" }}
    >
      <HtmlPageFill
        load={data}
        height={plateHeight}
        selected={selected}
        view="html"
        onRetry={() => void mutate()}
      />
    </div>
  );
}

function LiveCardText({
  workspaceId,
  artifact,
  plateHeight,
  selected,
  rendered,
}: {
  workspaceId: string;
  artifact: ArtifactRef;
  plateHeight: number;
  selected: boolean;
  rendered: boolean;
}) {
  const { data } = useSWR(
    cardTextKey(workspaceId, artifact.artifact_id, cardTextLimit(artifact)),
    fetchCardText,
  );
  const shownText = data ? formatCardText(data, artifact.artifact_type) : "";
  if (!shownText) return <ReadingPreview text="" />;
  return (
    <div
      onPointerDown={selected ? stopCardDrag : undefined}
      style={{
        width: "100%",
        height: "100%",
        padding: "8px 10px",
        boxSizing: "border-box",
      }}
    >
      <CardTextBody
        height={Math.max(40, plateHeight - 16)}
        rendered={rendered}
        interactive={selected}
      >
        {rendered ? <SafeMarkdown>{shownText}</SafeMarkdown> : shownText}
      </CardTextBody>
    </div>
  );
}

/**
 * Shared artifact plate body for both `CellArtifactCard` and open items in
 * `CellArtifactSequenceSpread`. Every `ArtifactPreviewKind` resolves here so
 * expanded sequence items use the same renderers as single cards.
 */
export function ArtifactPlatePreview({
  card,
  surface,
  selected,
  interactive = true,
  interaction,
  onImageLoad,
  inlineEditingCardId,
  onSetInlineEditingCardId,
  onInlineArtifactSaved,
}: {
  card: CellArtifactCardProps["card"];
  surface: ArtifactCardSurfaceData;
  selected: boolean;
  /**
   * False for non-interactive spread faces (side stacks, under-cards, tuck
   * animations): disables pointer hit-testing and tab stops so the outer
   * control or animation owns every interaction.
   */
  interactive?: boolean;
  interaction?: ArtifactViewerInteractionContext;
  onImageLoad?: (
    imageUrl: string,
    size: { width: number; height: number },
  ) => void;
} & InlineArtifactEditingProps) {
  const image = surface.previewKind === "image";
  return (
    <>
      <div
        data-artifact-preview={surface.previewKind}
        inert={!interactive}
        {...stylex.props(
          s.preview,
          image && s.checker,
          surface.previewKind === "map" && s.map,
          !interactive && s.previewStatic,
        )}
      >
        <ArtifactPreview
          card={card}
          surface={surface}
          selected={interactive && selected}
          interactive={interactive}
          interaction={interaction}
          onImageLoad={onImageLoad}
          inlineEditingCardId={inlineEditingCardId}
          onSetInlineEditingCardId={onSetInlineEditingCardId}
          onInlineArtifactSaved={onInlineArtifactSaved}
        />
      </div>
      {image && surface.imageUrl ? (
        <span
          aria-hidden="true"
          data-artifact-image-frame="true"
          {...stylex.props(s.imageFrame)}
        />
      ) : null}
    </>
  );
}

function ArtifactPreview({
  card,
  surface,
  selected,
  interactive = true,
  interaction,
  onImageLoad,
  inlineEditingCardId,
  onSetInlineEditingCardId,
  onInlineArtifactSaved,
}: {
  card: CellArtifactCardProps["card"];
  surface: ArtifactCardSurfaceData;
  selected: boolean;
  interactive?: boolean;
  interaction?: ArtifactViewerInteractionContext;
  onImageLoad?: (
    imageUrl: string,
    size: { width: number; height: number },
  ) => void;
} & InlineArtifactEditingProps) {
  const plateHeight =
    card.heightCells * CELL_SIZE - CARD_PLATE_TOP - CARD_PLATE_BOTTOM_INSET;
  const alt = surface.filename ?? card.title;
  switch (surface.previewKind) {
    case "image":
      return (
        <ImageCardPreview
          imageUrl={surface.imageUrl}
          alt={alt}
          dimensionsLabel={surface.dimensionsLabel}
          showDimensions={(surface.itemCount ?? 1) <= 1}
          onImageLoad={onImageLoad}
        />
      );
    case "tiff": {
      const { workspaceId, artifact } = surface;
      if (interactive && workspaceId && artifact) {
        return (
          <div
            data-cell-interactive-viewport="true"
            onPointerDown={stopCardDrag}
            style={{ width: "100%", height: "100%" }}
          >
            <TiffArtifactView
              workspaceId={workspaceId}
              artifactId={artifact.artifact_id}
              name={alt}
              selection={surface.tiffWindow?.selection}
              onSize={(width, height) =>
                onImageLoad?.(
                  imageThumbnailUrl(
                    imagePath(workspaceId, artifact.artifact_id),
                    0,
                  ),
                  { width, height },
                )
              }
            />
          </div>
        );
      }
      return (
        <ImageCardPreview
          imageUrl={surface.imageUrl}
          alt={alt}
          dimensionsLabel={surface.dimensionsLabel}
          showDimensions={(surface.itemCount ?? 1) <= 1}
          onImageLoad={onImageLoad}
        />
      );
    }
    case "tiff-text": {
      const { workspaceId, tiffText } = surface;
      const scanId = tiffText?.linkedWindow?.artifactId;
      if (workspaceId && tiffText) {
        return (
          <div
            data-cell-interactive-viewport={interactive ? "true" : undefined}
            onPointerDown={interactive ? stopCardDrag : undefined}
            style={{ width: "100%", height: "100%" }}
          >
            <TiffTextArtifact
              url={tiffText.url}
              workspaceId={workspaceId}
              height={plateHeight}
              linkedWindow={tiffText.linkedWindow}
              recognized={tiffText.recognized}
              artifactRef={surface.artifact}
              canEdit={Boolean(
                interactive &&
                surface.authorable &&
                !surface.producerLinked &&
                surface.artifact?.schema_version === 1 &&
                (surface.itemCount ?? 1) === 1 &&
                onSetInlineEditingCardId &&
                onInlineArtifactSaved,
              )}
              editing={interactive && inlineEditingCardId === card.id}
              onEditingChange={(next) =>
                onSetInlineEditingCardId?.(next ? card.id : null)
              }
              onSaveArtifact={(nextRef) =>
                onInlineArtifactSaved?.(card.id, nextRef)
              }
              onSize={
                scanId
                  ? (width, height) =>
                      onImageLoad?.(
                        imageThumbnailUrl(imagePath(workspaceId, scanId), 0),
                        { width, height },
                      )
                  : undefined
              }
            />
          </div>
        );
      }
      return <FileTile card={card} surface={surface} />;
    }
    case "table": {
      const { workspaceId, artifact } = surface;
      if (workspaceId && artifact) {
        return (
          <div
            onPointerDown={interactive ? stopCardDrag : undefined}
            style={{ width: "100%", height: "100%" }}
          >
            <TableArtifactRenderer
              artifact={{
                artifact_id: artifact.artifact_id,
                content_url: artifactInlineContentUrl(
                  workspaceId,
                  artifact.artifact_id,
                ),
              }}
              mode="table"
              presentation="canvas"
              availableHeight={plateHeight}
              interaction={interaction}
            />
          </div>
        );
      }
      const headers = surface.tableHeaders ?? [];
      const rows = surface.tableRows ?? [];
      return (
        <table {...stylex.props(s.table)}>
          {headers.length ? (
            <thead>
              <tr>
                {headers.map((header, index) => (
                  <th
                    key={index}
                    scope="col"
                    {...stylex.props(s.th, index > 0 && s.cellDivider)}
                  >
                    {header}
                  </th>
                ))}
              </tr>
            </thead>
          ) : null}
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((value, index) => (
                  <td
                    key={index}
                    {...stylex.props(s.td, index > 0 && s.cellDivider)}
                  >
                    {value}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      );
    }
    case "map": {
      const { workspaceId, artifact } = surface;
      if (workspaceId && artifact) {
        return (
          <div
            data-cell-interactive-viewport={interactive ? "true" : undefined}
            onPointerDown={interactive ? stopCardDrag : undefined}
            style={{ width: "100%", height: "100%" }}
          >
            <GeoMapArtifactRenderer
              artifact={artifact}
              mode="map"
              autoLoad
              presentation="canvas"
              availableHeight={Math.max(120, plateHeight - 2)}
              interaction={interaction}
            />
          </div>
        );
      }
      return (
        <>
          <MapMotif />
          {surface.previewText ? (
            <span {...stylex.props(s.mapCaption, m.ellipsis)}>
              {surface.previewText}
            </span>
          ) : null}
          <span {...stylex.props(s.mapLegend)}>
            <MapIcon size={11} aria-hidden="true" />
            <span {...stylex.props(m.ellipsis, m.grow)}>
              {surface.typeLabel}
            </span>
            {surface.dimensionsLabel ? (
              <span {...stylex.props(s.placeholderMeta)}>
                {surface.dimensionsLabel}
              </span>
            ) : null}
          </span>
        </>
      );
    }
    case "html-page": {
      const { workspaceId, artifact } = surface;
      if (workspaceId && artifact) {
        return (
          <LiveHtmlPage
            workspaceId={workspaceId}
            artifactId={artifact.artifact_id}
            plateHeight={plateHeight}
            selected={selected}
          />
        );
      }
      return <FileTile card={card} surface={surface} />;
    }
    case "markdown":
    case "text": {
      const { workspaceId, artifact, previewText } = surface;
      if (workspaceId && artifact && previewText == null) {
        return (
          <LiveCardText
            workspaceId={workspaceId}
            artifact={artifact}
            plateHeight={plateHeight}
            selected={selected}
            rendered={surface.previewKind === "markdown"}
          />
        );
      }
      return <ReadingPreview text={previewText ?? ""} />;
    }
    case "file":
      return <FileTile card={card} surface={surface} />;
    default: {
      const _exhaustive: never = surface.previewKind;
      return _exhaustive;
    }
  }
}

/**
 * Markdown read as plain text: `#` lines set as headings and `-` / `*` lines as
 * bullets. The card shows a glance, not a rendered document.
 */
function ReadingPreview({ text }: { text: string }) {
  const lines = text.split("\n");
  return (
    <div {...stylex.props(s.reading)}>
      {lines.map((line, index) => {
        const heading = /^#{1,6}\s+/.exec(line);
        if (heading) {
          return (
            <p key={index} {...stylex.props(s.readingLine, s.readingHeading)}>
              {line.slice(heading[0].length)}
            </p>
          );
        }
        const bullet = /^\s*[-*]\s+/.exec(line);
        if (bullet) {
          return (
            <p key={index} {...stylex.props(s.readingLine, s.readingBullet)}>
              • {line.slice(bullet[0].length)}
            </p>
          );
        }
        return (
          <p key={index} {...stylex.props(s.readingLine)}>
            {line}
          </p>
        );
      })}
    </div>
  );
}

/** A coordinate grid with contour lines: a map layer's mark, not its data. */
function MapMotif() {
  const grid = [20, 40, 60, 80];
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
      {...stylex.props(s.mapArt)}
    >
      <g
        style={{ stroke: tokens.colorDivider }}
        strokeWidth={0.4}
        vectorEffect="non-scaling-stroke"
      >
        {grid.map((at) => (
          <React.Fragment key={at}>
            <line x1={at} y1={0} x2={at} y2={100} />
            <line x1={0} y1={at} x2={100} y2={at} />
          </React.Fragment>
        ))}
      </g>
      <g
        fill="none"
        style={{ stroke: tokens.colorBorderStrong }}
        strokeOpacity={0.45}
        strokeWidth={0.8}
      >
        <path d="M8 70 C 22 52, 40 60, 52 44 S 82 30, 94 38" />
        <path d="M14 82 C 30 66, 46 74, 60 58 S 84 50, 96 54" />
        <path d="M30 30 C 40 22, 54 24, 58 32 S 46 46, 36 42 S 24 36, 30 30 Z" />
      </g>
    </svg>
  );
}

export const CellArtifactCard = React.memo(CellArtifactCardImpl);

// --- Collection card -------------------------------------------------------

export interface CellCollectionCardProps extends CellCardBaseProps {
  surface: CollectionCardSurfaceData;
  onRemoveMember?: (cardId: string, memberId: string) => void;
}

function CellCollectionCardImpl(props: CellCollectionCardProps) {
  const { card, surface, onRemoveMember } = props;
  const state = useResolvedCardState(card.id, props);
  const count = surface.members.length;
  // Each member row is two cells tall, starting cleanly under the 23px strip
  // on its port's row. Punched, it runs between the member's hole and the
  // output's, so every row keeps one column.
  const rowBand = (index: number) => ({
    top: plateRowTop(collectionRowOffset(index)),
    height: CELL_SIZE * 2,
    paddingInline: props.well === "punched" ? PUNCHED_LABEL_INSET : undefined,
  });

  return (
    <CellCardShell
      {...props}
      kind="collection"
      state={state}
      resizable={card.resizable ?? true}
      rootData={{ "data-artifact-type": surface.artifactTypeId }}
      headerExtra={
        <span data-collection-count={count} {...stylex.props(m.chip)}>
          {count === 1 ? "1 item" : `${count} items`}
        </span>
      }
      strip={
        <>
          <TypeDot artifactTypeId={surface.artifactTypeId} />
          <span {...stylex.props(s.stripLabel, m.ellipsis)}>
            {surface.typeLabel}
          </span>
        </>
      }
    >
      {surface.members.map((member, index) => (
        <div
          key={member.id}
          data-collection-member={member.id}
          data-input-node-id={card.id}
          data-input-plug-port={COLLECTION_PORT}
          data-input-plug-id={member.id}
          {...styled(rowBand(index), m.band, s.memberRow)}
        >
          <span {...stylex.props(m.indexBadge)}>{index + 1}</span>
          <TypeDot artifactTypeId={member.artifactTypeId} />
          <span {...stylex.props(s.memberText)}>
            <span {...stylex.props(s.memberLabel, m.ellipsis)}>
              {member.label}
            </span>
            <span {...stylex.props(s.memberType, m.ellipsis)}>
              {member.typeLabel}
            </span>
          </span>
          {member.meta ? (
            <span {...stylex.props(s.memberMeta)}>{member.meta}</span>
          ) : null}
          {onRemoveMember ? (
            <IconButton
              size="2xs"
              variant="ghost"
              label={`Remove ${member.label}`}
              onPointerDown={stopCardDrag}
              onClick={() => onRemoveMember(card.id, member.id)}
            >
              <X size={11} />
            </IconButton>
          ) : null}
        </div>
      ))}
      {surface.showSparePlug ? (
        <div
          data-collection-spare-plug="true"
          data-input-node-id={surface.sparePlugId ? card.id : undefined}
          data-input-plug-port={
            surface.sparePlugId ? COLLECTION_PORT : undefined
          }
          data-input-plug-id={surface.sparePlugId ?? undefined}
          {...styled(rowBand(count), m.band, s.spareRow)}
        >
          <span {...stylex.props(s.spareSlot)}>
            <Plus size={11} aria-hidden="true" />
            Drop / wire item
          </span>
        </div>
      ) : null}
    </CellCardShell>
  );
}

export const CellCollectionCard = React.memo(CellCollectionCardImpl);
