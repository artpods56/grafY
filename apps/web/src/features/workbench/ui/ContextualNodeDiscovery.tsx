"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { LoaderCircle, Search, Sparkles } from "lucide-react";
import { useStore, ViewportPortal } from "@xyflow/react";

import type { ArtifactTypeKey, NodeRegistry, Port } from "@/lib/api";
import {
  FINE_POINTER_QUERY,
  useMediaQuery,
} from "@/hooks/use-media-query";
import { overlay } from "@/lib/stylex/overlay.stylex";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { schemaFields } from "../canvas/config-schema";
import { DEFAULT_NODE_PLACEMENT_HEIGHT, DEFAULT_NODE_WIDTH } from "../canvas/node-layout";
import { artifactTypeColor } from "../canvas/nodes.css";
import { portArtifactType } from "../canvas/types";
import {
  connectionRouteTitle,
} from "../model/graph-authoring";
import {
  catalogNodeKey,
  catalogNodePortSummary,
  catalogNodeProviderLabel,
  type ContextualCandidate,
  type ContextualRouteChoice,
} from "../model/node-catalog";
import {
  CATALOG_PREVIEW_WIDTH,
  CatalogNodePreview,
  catalogPreviewInputHandleOffset,
  catalogPreviewOutputHandleOffset,
  portKey,
} from "./CatalogNodePreview";

export type ContextualDiscoveryDirection = "downstream" | "upstream";

export interface ContextualDiscoverySession {
  graphId: string | null;
  /** The port the drag started from, always on an existing node. */
  sourceNodeId: string;
  sourceHandle: string;
  sourcePortTitle: string;
  sourceArtifactType: ArtifactTypeKey | null;
  sourceShape: Port["shape"];
  direction: ContextualDiscoveryDirection;
  clientAnchor: { x: number; y: number };
  flowPosition: { x: number; y: number };
  candidates: readonly ContextualCandidate[];
}

export interface ContextualAgentEnvironment {
  id: string;
  name: string;
  profile: string;
}

export interface ContextualAgentThread {
  id: string;
  environmentId: string;
  environmentName: string;
}

export interface ContextualGenerationRequest {
  prompt: string;
  threadId: string | null;
  environmentId: string | null;
  createEnvironment: boolean;
}

export interface ContextualNodeDiscoveryProps {
  session: ContextualDiscoverySession | null;
  registry: NodeRegistry;
  canInsert: boolean;
  insertDisabledReason?: string;
  onClose: () => void;
  onConfirm: (
    candidate: ContextualCandidate,
    choice: ContextualRouteChoice,
  ) => void;
  environments?: readonly ContextualAgentEnvironment[];
  activeThread?: ContextualAgentThread | null;
  onGenerate?: (
    request: ContextualGenerationRequest,
    signal: AbortSignal,
  ) => Promise<void>;
}

const POPUP_WIDTH = 340;
const POPUP_MAX_HEIGHT = 480;
const POPUP_GAP = 16;
const POPUP_MARGIN = 12;
const MOBILE_OVERLAY_TOP = "var(--grafy-mobile-overlay-top)";
const SAFE_AREA_TOP = "env(safe-area-inset-top, 0px)";
const SAFE_AREA_BOTTOM = "env(safe-area-inset-bottom, 0px)";
const SAFE_AREA_LEFT = "env(safe-area-inset-left, 0px)";
const SAFE_AREA_RIGHT = "env(safe-area-inset-right, 0px)";

interface ViewportGeometry {
  layoutWidth: number;
  visualTop: number;
  visualHeight: number;
  mobileOverlayTop: number;
}

function readViewportGeometry(): ViewportGeometry {
  if (typeof window === "undefined") {
    return {
      layoutWidth: POPUP_WIDTH + POPUP_MARGIN * 2,
      visualTop: 0,
      visualHeight: POPUP_MAX_HEIGHT + POPUP_MARGIN * 2,
      mobileOverlayTop: 0,
    };
  }
  const layoutWidth = window.innerWidth;
  const layoutHeight = window.innerHeight;
  const mobileOverlayTop = Number.parseFloat(
    window
      .getComputedStyle(document.documentElement)
      .getPropertyValue("--grafy-mobile-overlay-top"),
  );
  if (!Number.isFinite(mobileOverlayTop)) {
    throw new Error("--grafy-mobile-overlay-top must resolve to a pixel length");
  }
  return {
    layoutWidth,
    visualTop: window.visualViewport?.offsetTop ?? 0,
    visualHeight: window.visualViewport?.height ?? layoutHeight,
    mobileOverlayTop,
  };
}

const s = stylex.create({
  popup: {
    position: "fixed",
    zIndex: {
      default: 40,
      "@media (max-width: 620px)": 85,
    },
    width: {
      default: `min(${POPUP_WIDTH}px, calc(100vw - ${POPUP_MARGIN * 2}px))`,
      "@media (max-width: 620px)":
        `min(${POPUP_WIDTH}px, calc(100vw - ${POPUP_MARGIN * 2}px - ${SAFE_AREA_LEFT} - ${SAFE_AREA_RIGHT}))`,
    },
    maxHeight: {
      default: `min(${POPUP_MAX_HEIGHT}px, calc(100svh - ${POPUP_MARGIN * 2}px))`,
      "@media (max-width: 620px)":
        `min(${POPUP_MAX_HEIGHT}px, calc(100svh - ${MOBILE_OVERLAY_TOP} - ${POPUP_MARGIN}px - ${SAFE_AREA_TOP}))`,
    },
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
  },
  header: {
    display: "grid",
    gap: "10px",
    padding: "14px 14px 12px",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorBorder,
  },
  title: {
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeSm,
    fontWeight: 740,
  },
  subtitle: {
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
  },
  searchWrap: { position: "relative" },
  searchIcon: {
    position: "absolute",
    top: {
      default: "10px",
      "@media (max-width: 620px)": "14px",
    },
    left: "11px",
    color: tokens.colorSubtle,
    pointerEvents: "none",
  },
  search: {
    width: "100%",
    height: {
      default: "36px",
      "@media (max-width: 620px)": "44px",
    },
    padding: "0 10px 0 32px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: {
      default: tokens.colorBorder,
      ":focus": tokens.colorBorderStrong,
    },
    borderRadius: tokens.radiusSm,
    outline: "none",
    backgroundColor: tokens.colorSurfaceSunken,
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
  },
  list: {
    minHeight: 0,
    overflowY: "auto",
    display: "flex",
    flexDirection: "column",
    gap: "6px",
    padding: "10px",
  },
  item: {
    width: "100%",
    minHeight: "58px",
    display: "grid",
    gap: "4px",
    padding: "12px 14px",
    borderRadius: "8px",
    color: tokens.colorText,
    cursor: "pointer",
    fontFamily: "inherit",
    textAlign: "left",
    outlineColor: tokens.colorAccent,
    outlineStyle: "solid",
    outlineOffset: "-3px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
    transitionProperty: "background-color",
    transitionDuration: "120ms",
  },
  itemTitle: {
    overflow: "hidden",
    fontSize: tokens.fontSizeSm,
    fontWeight: 730,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  itemDescription: {
    display: "-webkit-box",
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.4,
    WebkitBoxOrient: "vertical",
    WebkitLineClamp: 2,
  },
  generateItem: {
    gridTemplateColumns: "30px minmax(0, 1fr)",
    alignItems: "center",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorderStrong,
    backgroundColor: {
      default: tokens.colorSurfaceRaised,
      ":hover": tokens.colorHover,
    },
  },
  generateIcon: {
    display: "grid",
    placeItems: "center",
    width: "28px",
    height: "28px",
    borderRadius: tokens.radiusSm,
    backgroundColor: tokens.colorAccentSoft,
    color: tokens.colorAccent,
  },
  form: {
    display: "grid",
    gap: "12px",
    padding: "14px",
    overflowY: "auto",
  },
  field: {
    display: "grid",
    gap: "6px",
  },
  label: {
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeXs,
    fontWeight: 700,
  },
  textarea: {
    width: "100%",
    minHeight: "120px",
    resize: "vertical",
    padding: "10px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: {
      default: tokens.colorBorder,
      ":focus": tokens.colorBorderStrong,
    },
    borderRadius: tokens.radiusSm,
    outline: "none",
    backgroundColor: tokens.colorSurfaceSunken,
    color: tokens.colorText,
    fontFamily: "inherit",
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.45,
  },
  select: {
    width: "100%",
    height: "38px",
    paddingInline: "10px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusSm,
    backgroundColor: tokens.colorSurfaceSunken,
    color: tokens.colorText,
    fontFamily: "inherit",
    fontSize: tokens.fontSizeSm,
  },
  contract: {
    padding: "9px 10px",
    borderRadius: tokens.radiusSm,
    backgroundColor: tokens.colorSurfaceSunken,
    color: tokens.colorMuted,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: tokens.fontSizeXs,
  },
  error: {
    color: tokens.colorDanger,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.4,
  },
  empty: {
    padding: "28px 16px",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
    textAlign: "center",
  },
  footer: {
    display: "flex",
    justifyContent: "space-between",
    gap: "8px",
    padding: {
      default: "8px 12px",
      "@media (max-width: 620px)":
        "8px 12px calc(8px + env(safe-area-inset-bottom, 0px))",
    },
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorBorder,
  },
  ghostButton: {
    minHeight: {
      default: "28px",
      "@media (max-width: 620px)": "44px",
    },
    paddingInline: "8px",
    borderWidth: 0,
    borderRadius: tokens.radiusSm,
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: tokens.colorMuted,
    cursor: "pointer",
    fontSize: tokens.fontSizeXs,
    fontWeight: 680,
  },
  primaryButton: {
    minHeight: {
      default: "32px",
      "@media (max-width: 620px)": "44px",
    },
    display: "inline-flex",
    alignItems: "center",
    gap: "6px",
    paddingInline: "12px",
    borderWidth: 0,
    borderRadius: tokens.radiusSm,
    backgroundColor: {
      default: tokens.colorAccent,
      ":disabled": tokens.colorBorder,
    },
    color: tokens.colorOnAccent,
    cursor: { default: "pointer", ":disabled": "not-allowed" },
    fontFamily: "inherit",
    fontSize: tokens.fontSizeXs,
    fontWeight: 730,
  },
  spinner: {
    animationName: stylex.keyframes({ to: { transform: "rotate(360deg)" } }),
    animationDuration: "700ms",
    animationIterationCount: "infinite",
    animationTimingFunction: "linear",
  },
  hint: {
    alignSelf: "center",
    color: tokens.colorSubtle,
    fontSize: "10px",
  },
  canvasPreview: {
    position: "absolute",
    pointerEvents: "none",
  },
  canvasEdge: {
    position: "absolute",
    overflow: "visible",
    pointerEvents: "none",
  },
});

export function popupPositionBesidePreview(
  preview: { left: number; top: number; right: number; width: number } | null,
  fallback: { x: number; y: number },
  width: number,
  height: number,
  viewport: { width: number; height: number },
): { left: number; top: number } {
  const maxLeft = Math.max(POPUP_MARGIN, viewport.width - width - POPUP_MARGIN);
  const maxTop = Math.max(POPUP_MARGIN, viewport.height - height - POPUP_MARGIN);

  if (!preview) {
    return {
      left: Math.min(Math.max(POPUP_MARGIN, fallback.x), maxLeft),
      top: Math.min(Math.max(POPUP_MARGIN, fallback.y), maxTop),
    };
  }

  const rightLeft = preview.right + POPUP_GAP;
  const leftLeft = preview.left - POPUP_GAP - width;
  const left =
    rightLeft + width + POPUP_MARGIN <= viewport.width
      ? rightLeft
      : leftLeft >= POPUP_MARGIN
        ? leftLeft
        : Math.min(Math.max(POPUP_MARGIN, rightLeft), maxLeft);

  return {
    left,
    top: Math.min(Math.max(POPUP_MARGIN, preview.top), maxTop),
  };
}

function choiceLabel(
  direction: ContextualDiscoveryDirection,
  sourcePortTitle: string,
  choice: ContextualRouteChoice,
): string {
  const candidateTitle =
    choice.candidatePort.title ?? choice.candidatePort.name;
  const transport =
    choice.collectionMode === "map" ? "map each item" : "direct";
  const route = connectionRouteTitle(choice.route);
  return [
    direction === "upstream"
      ? `${candidateTitle} → ${sourcePortTitle}`
      : `${sourcePortTitle} → ${candidateTitle}`,
    transport,
    route === "Whole output" ? null : route,
  ]
    .filter(Boolean)
    .join(" · ");
}

function previewFlowPosition(flowPosition: { x: number; y: number }): {
  x: number;
  y: number;
} {
  return {
    x: flowPosition.x,
    y: flowPosition.y - DEFAULT_NODE_PLACEMENT_HEIGHT / 2,
  };
}

export function ContextualNodeDiscovery({
  session,
  registry,
  canInsert,
  insertDisabledReason = "You do not have permission to edit this graph.",
  onClose,
  onConfirm,
  environments = [],
  activeThread = null,
  onGenerate,
}: ContextualNodeDiscoveryProps) {
  const finePointer = useMediaQuery(FINE_POINTER_QUERY);
  const [query, setQuery] = React.useState("");
  const [pendingCandidate, setPendingCandidate] =
    React.useState<ContextualCandidate | null>(null);
  const [previewedKey, setPreviewedKey] = React.useState<string | null>(null);
  const [hoveredChoiceIndex, setHoveredChoiceIndex] = React.useState(0);
  const [view, setView] = React.useState<"discovery" | "generation">(
    "discovery",
  );
  const [generationPrompt, setGenerationPrompt] = React.useState("");
  const [selectedEnvironmentId, setSelectedEnvironmentId] = React.useState(
    environments[0]?.id ?? "__new__",
  );
  const [continueActiveThread, setContinueActiveThread] = React.useState(true);
  const [generationPending, setGenerationPending] = React.useState(false);
  const [generationError, setGenerationError] = React.useState<string | null>(
    null,
  );
  const [previewBox, setPreviewBox] = React.useState<DOMRect | null>(null);
  const [viewport, setViewport] = React.useState(readViewportGeometry);
  const rootRef = React.useRef<HTMLDivElement>(null);
  const searchRef = React.useRef<HTMLInputElement>(null);
  const previewRef = React.useRef<HTMLDivElement>(null);
  const resultRefs = React.useRef(new Map<string, HTMLButtonElement>());
  const autoFocusSessionKeyRef = React.useRef<string | null>(null);
  const generationControllerRef = React.useRef<AbortController | null>(null);

  const closeDiscovery = React.useCallback(() => {
    generationControllerRef.current?.abort();
    generationControllerRef.current = null;
    onClose();
  }, [onClose]);

  React.useEffect(
    () => () => generationControllerRef.current?.abort(),
    [],
  );

  const sourcePoint = useStore((state) => {
    if (!session) return null;
    const node = state.nodeLookup.get(session.sourceNodeId);
    if (!node) return null;
    const origin = node.internals.positionAbsolute;
    const downstream = session.direction === "downstream";
    const handle = (downstream
      ? node.internals.handleBounds?.source
      : node.internals.handleBounds?.target
    )?.find((candidate) => candidate.id === session.sourceHandle);
    if (!handle) {
      return downstream
        ? {
            x: origin.x + (node.measured.width ?? DEFAULT_NODE_WIDTH),
            y: origin.y + (node.measured.height ?? DEFAULT_NODE_PLACEMENT_HEIGHT) / 2,
          }
        : {
            x: origin.x,
            y: origin.y + (node.measured.height ?? DEFAULT_NODE_PLACEMENT_HEIGHT) / 2,
          };
    }
    return {
      x: origin.x + handle.x + handle.width / 2,
      y: origin.y + handle.y + handle.height / 2,
    };
  });

  const autoFocusSessionKey = session
    ? JSON.stringify([
        session.graphId,
        session.sourceNodeId,
        session.sourceHandle,
        session.direction,
        session.flowPosition.x,
        session.flowPosition.y,
      ])
    : null;

  React.useEffect(() => {
    if (!autoFocusSessionKey) {
      autoFocusSessionKeyRef.current = null;
      return;
    }
    if (autoFocusSessionKeyRef.current === autoFocusSessionKey) return;
    autoFocusSessionKeyRef.current = autoFocusSessionKey;
    if (!finePointer) return;
    const focusFrame = window.requestAnimationFrame(() =>
      searchRef.current?.focus(),
    );
    return () => window.cancelAnimationFrame(focusFrame);
  }, [autoFocusSessionKey, finePointer]);

  React.useEffect(() => {
    if (!session) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        if (generationPending) {
          generationControllerRef.current?.abort();
          closeDiscovery();
        } else if (view === "generation") {
          setView("discovery");
          setGenerationError(null);
        } else if (pendingCandidate) {
          setPendingCandidate(null);
          setHoveredChoiceIndex(0);
        } else closeDiscovery();
      }
    };
    const onPointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) closeDiscovery();
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("mousedown", onPointerDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("mousedown", onPointerDown);
    };
  }, [closeDiscovery, generationPending, pendingCandidate, session, view]);

  React.useLayoutEffect(() => {
    const box = previewRef.current?.getBoundingClientRect() ?? null;
    setPreviewBox((current) => {
      if (
        current?.left === box?.left &&
        current?.top === box?.top &&
        current?.right === box?.right
      ) {
        return current;
      }
      return box;
    });
  }, [hoveredChoiceIndex, pendingCandidate, previewedKey, query, session]);

  React.useLayoutEffect(() => {
    if (!session) return;
    const updateViewport = () => setViewport(readViewportGeometry());
    const visualViewport = window.visualViewport;
    updateViewport();
    window.addEventListener("resize", updateViewport);
    visualViewport?.addEventListener("resize", updateViewport);
    visualViewport?.addEventListener("scroll", updateViewport);
    return () => {
      window.removeEventListener("resize", updateViewport);
      visualViewport?.removeEventListener("resize", updateViewport);
      visualViewport?.removeEventListener("scroll", updateViewport);
    };
  }, [session]);

  if (!session) return null;

  const normalized = query.trim().toLowerCase();
  const candidates = session.candidates.filter((candidate) => {
    if (!normalized) return true;
    const haystack = [
      candidate.spec.title,
      candidate.spec.description,
      catalogNodeProviderLabel(candidate.spec, registry),
      catalogNodePortSummary(candidate.spec, registry),
      ...candidate.choices.map((choice) =>
        choiceLabel(session.direction, session.sourcePortTitle, choice),
      ),
    ]
      .join(" ")
      .toLowerCase();
    return haystack.includes(normalized);
  });

  const previewedCandidate =
    pendingCandidate ??
    candidates.find((candidate) => catalogNodeKey(candidate.spec) === previewedKey) ??
    candidates[0] ??
    null;
  const previewedChoice =
    previewedCandidate?.choices[
      Math.min(
        hoveredChoiceIndex,
        Math.max(0, (previewedCandidate?.choices.length ?? 1) - 1),
      )
    ] ?? previewedCandidate?.choices[0] ??
    null;
  const previewPosition = previewFlowPosition(session.flowPosition);
  const targetOffset = previewedCandidate
    ? session.direction === "upstream"
      ? catalogPreviewOutputHandleOffset(
          previewedCandidate.spec,
          previewedChoice?.candidatePort.name,
        )
      : catalogPreviewInputHandleOffset(
          previewedCandidate.spec,
          previewedChoice?.candidatePort.name,
        )
    : { x: 0, y: 0 };
  const targetPoint = {
    x: previewPosition.x + targetOffset.x,
    y: previewPosition.y + targetOffset.y,
  };
  const representativePort =
    previewedChoice?.candidatePort ??
    (session.direction === "upstream"
      ? previewedCandidate?.spec.outputs[0] ?? previewedCandidate?.spec.inputs[0]
      : previewedCandidate?.spec.inputs[0] ?? previewedCandidate?.spec.outputs[0]);
  const representativeArtifact = representativePort
    ? portArtifactType(representativePort)
    : null;
  const accent = representativeArtifact
    ? artifactTypeColor(representativeArtifact.id, tokens.colorAccent)
    : tokens.colorAccent;

  const viewportBottom = viewport.visualTop + viewport.visualHeight;
  const compactViewport = viewport.layoutWidth <= 620;
  const popupWidth = Math.min(
    POPUP_WIDTH,
    viewport.layoutWidth - POPUP_MARGIN * 2,
  );
  const popupTopOffset = compactViewport
    ? viewport.mobileOverlayTop
    : POPUP_MARGIN;
  const popupTopMargin = viewport.visualTop + popupTopOffset;
  const popupHeight = Math.max(
    0,
    Math.min(
      POPUP_MAX_HEIGHT,
      viewportBottom - popupTopMargin - POPUP_MARGIN,
    ),
  );
  const unclampedPosition = popupPositionBesidePreview(
    previewBox,
    session.clientAnchor,
    popupWidth,
    popupHeight,
    { width: viewport.layoutWidth, height: viewportBottom },
  );
  const position = {
    left: unclampedPosition.left,
    top: Math.max(popupTopMargin, unclampedPosition.top),
  };
  const compactPopupTop =
    `max(${position.top}px, calc(${MOBILE_OVERLAY_TOP} + ${SAFE_AREA_TOP}))`;
  const compactPopupLeft =
    `max(${position.left}px, calc(${POPUP_MARGIN}px + ${SAFE_AREA_LEFT}))`;
  const compactPopupMaxHeight =
    `min(${popupHeight}px, calc(100dvh - ${MOBILE_OVERLAY_TOP} - ${POPUP_MARGIN}px - ${SAFE_AREA_TOP} - ${SAFE_AREA_BOTTOM}))`;

  const selectCandidate = (candidate: ContextualCandidate) => {
    if (!canInsert) return;
    if (candidate.choices.length === 1) {
      const choice = candidate.choices[0]!;
      if (
        candidate.spec.publication_state === "deprecated" &&
        !window.confirm(
          `Insert deprecated Module “${candidate.spec.title}”? New inserts are discouraged. Existing pinned calls keep working.`,
        )
      ) {
        return;
      }
      onConfirm(candidate, choice);
      return;
    }
    setPendingCandidate(candidate);
    setHoveredChoiceIndex(0);
  };

  const selectChoice = (choice: ContextualRouteChoice) => {
    if (!pendingCandidate || !canInsert) return;
    if (
      pendingCandidate.spec.publication_state === "deprecated" &&
      !window.confirm(
        `Insert deprecated Module “${pendingCandidate.spec.title}”? New inserts are discouraged. Existing pinned calls keep working.`,
      )
    ) {
      return;
    }
    onConfirm(pendingCandidate, choice);
  };

  const submitGeneration = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const prompt = generationPrompt.trim();
    if (
      !onGenerate ||
      !prompt ||
      !session.sourceArtifactType ||
      generationPending
    ) {
      return;
    }
    const controller = new AbortController();
    generationControllerRef.current?.abort();
    generationControllerRef.current = controller;
    setGenerationPending(true);
    setGenerationError(null);
    const activeThreadId =
      activeThread && continueActiveThread ? activeThread.id : null;
    const activeEnvironmentId = activeThread?.environmentId ?? null;
    try {
      await onGenerate(
        {
          prompt,
          threadId: activeThreadId,
          environmentId: activeEnvironmentId
            ? activeEnvironmentId
            : selectedEnvironmentId === "__new__"
              ? null
              : selectedEnvironmentId,
          createEnvironment:
            !activeThread && selectedEnvironmentId === "__new__",
        },
        controller.signal,
      );
    } catch (error) {
      if (!controller.signal.aborted) {
        setGenerationError(
          error instanceof Error ? error.message : "Could not create the draft node.",
        );
      }
    } finally {
      if (generationControllerRef.current === controller) {
        generationControllerRef.current = null;
        setGenerationPending(false);
      }
    }
  };

  const focusCandidateAt = (index: number) => {
    const candidate = candidates[index];
    if (!candidate) return;
    const key = catalogNodeKey(candidate.spec);
    setPreviewedKey(key);
    resultRefs.current.get(key)?.focus();
  };

  const dx = Math.max(48, Math.abs(targetPoint.x - (sourcePoint?.x ?? 0)) * 0.45);
  const edgePath =
    sourcePoint && previewedCandidate
      ? `M ${sourcePoint.x} ${sourcePoint.y} C ${sourcePoint.x + dx} ${sourcePoint.y}, ${targetPoint.x - dx} ${targetPoint.y}, ${targetPoint.x} ${targetPoint.y}`
      : null;

  return (
    <>
      <ViewportPortal>
        {previewedCandidate ? (
          <>
            {edgePath ? (
              <svg
                aria-hidden="true"
                width={1}
                height={1}
                {...stylex.props(s.canvasEdge)}
                style={{ left: 0, top: 0 }}
              >
                <path
                  d={edgePath}
                  fill="none"
                  stroke={accent}
                  strokeDasharray="7 6"
                  strokeWidth={2}
                  strokeLinecap="round"
                  opacity={0.72}
                />
              </svg>
            ) : null}
            <div
              key={catalogNodeKey(previewedCandidate.spec)}
              ref={previewRef}
              className="grafy-discovery-preview"
              {...stylex.props(s.canvasPreview)}
              style={{
                left: previewPosition.x,
                top: previewPosition.y,
                width: CATALOG_PREVIEW_WIDTH,
              }}
            >
              <CatalogNodePreview
                spec={previewedCandidate.spec}
                registry={registry}
                fields={schemaFields(previewedCandidate.spec.config_schema)}
                selectedPortKey={
                  previewedChoice
                    ? portKey(previewedChoice.candidatePort)
                    : null
                }
              />
            </div>
          </>
        ) : null}
      </ViewportPortal>

      <div
        ref={rootRef}
        role="dialog"
        aria-label={`Continue from ${session.sourcePortTitle}`}
        {...stylex.props(overlay.popup, s.popup)}
        style={{
          left: compactViewport ? compactPopupLeft : position.left,
          top: compactViewport ? compactPopupTop : position.top,
          maxHeight: compactViewport ? compactPopupMaxHeight : popupHeight,
        }}
      >
        <div {...stylex.props(s.header)}>
          <div>
            <div {...stylex.props(s.title)}>
              {view === "generation"
                ? `Generate from ${session.sourcePortTitle}`
                : pendingCandidate
                ? `Connect ${pendingCandidate.spec.title}`
                : `Continue from ${session.sourcePortTitle}`}
            </div>
            <div {...stylex.props(s.subtitle)}>
              {view === "generation"
                ? "Create a durable draft and continue in an agent environment"
                : pendingCandidate
                ? session.direction === "upstream"
                  ? "Choose which output feeds this input"
                  : "Choose how this output arrives"
                : `${candidates.length} compatible ${candidates.length === 1 ? "node" : "nodes"}`}
            </div>
          </div>
          {view === "discovery" && !pendingCandidate ? (
            <div {...stylex.props(s.searchWrap)}>
              <Search size={13} {...stylex.props(s.searchIcon)} />
              <input
                ref={searchRef}
                aria-label="Search compatible nodes"
                value={query}
                placeholder="Search compatible nodes…"
                {...stylex.props(s.search)}
                onChange={(event) => {
                  setQuery(event.currentTarget.value);
                  setPreviewedKey(null);
                }}
              />
            </div>
          ) : null}
        </div>

        {view === "generation" ? (
          <form {...stylex.props(s.form)} onSubmit={(event) => void submitGeneration(event)}>
            <div {...stylex.props(s.contract)}>
              {session.direction === "upstream"
                ? `Generated node → ${session.sourceShape === "many" ? "Sequence<" : ""}${session.sourceArtifactType?.id ?? "Unbound"}${session.sourceShape === "many" ? ">" : ""}`
                : `${session.sourceShape === "many" ? "Sequence<" : ""}${session.sourceArtifactType?.id ?? "Unbound"}${session.sourceShape === "many" ? ">" : ""} → Generated node`}
            </div>
            <label {...stylex.props(s.field)}>
              <span {...stylex.props(s.label)}>Describe the node</span>
              <textarea
                autoFocus
                aria-label="Describe what this node should do"
                value={generationPrompt}
                placeholder="For example: call the enrichment API for every text value and append the returned category"
                disabled={generationPending}
                {...stylex.props(s.textarea)}
                onChange={(event) => setGenerationPrompt(event.currentTarget.value)}
              />
            </label>
            <label {...stylex.props(s.field)}>
              <span {...stylex.props(s.label)}>Agent environment</span>
              {activeThread ? (
                <>
                  <select
                    aria-label="Agent thread"
                    value={continueActiveThread ? "current" : "new"}
                    disabled={generationPending}
                    {...stylex.props(s.select)}
                    onChange={(event) =>
                      setContinueActiveThread(event.currentTarget.value === "current")
                    }
                  >
                    <option value="current">Continue current thread</option>
                    <option value="new">Start a new thread</option>
                  </select>
                  <div {...stylex.props(s.contract)}>
                    {activeThread.environmentName} · {continueActiveThread
                      ? "current thread"
                      : "new thread"}
                  </div>
                </>
              ) : (
                <select
                  aria-label="Agent environment"
                  value={selectedEnvironmentId}
                  disabled={generationPending}
                  {...stylex.props(s.select)}
                  onChange={(event) =>
                    setSelectedEnvironmentId(event.currentTarget.value)
                  }
                >
                  <option value="__new__">New Python environment</option>
                  {environments.map((environment) => (
                    <option key={environment.id} value={environment.id}>
                      {environment.name} · {environment.profile}
                    </option>
                  ))}
                </select>
              )}
            </label>
            {!session.sourceArtifactType ? (
              <div role="alert" {...stylex.props(s.error)}>
                Bind this generic port to a concrete artifact type before generating.
              </div>
            ) : null}
            {generationError ? (
              <div role="alert" {...stylex.props(s.error)}>{generationError}</div>
            ) : null}
            <div {...stylex.props(s.footer)}>
              <button
                type="button"
                disabled={generationPending}
                {...stylex.props(s.ghostButton)}
                onClick={() => {
                  setView("discovery");
                  setGenerationError(null);
                }}
              >
                Back
              </button>
              <button
                type="submit"
                disabled={
                  generationPending ||
                  !generationPrompt.trim() ||
                  !session.sourceArtifactType ||
                  !onGenerate
                }
                aria-busy={generationPending}
                {...stylex.props(s.primaryButton)}
              >
                {generationPending ? (
                  <LoaderCircle size={13} {...stylex.props(s.spinner)} />
                ) : (
                  <Sparkles size={13} />
                )}
                {generationPending ? "Creating draft…" : "Create draft"}
              </button>
            </div>
          </form>
        ) : (
        <div {...stylex.props(s.list)} role="listbox">
          {!pendingCandidate ? (
            <button
              type="button"
              role="option"
              aria-selected={false}
              disabled={!canInsert || !onGenerate}
              {...stylex.props(overlay.item, s.item, s.generateItem)}
              onClick={() => {
                setView("generation");
                setGenerationError(null);
              }}
            >
              <span {...stylex.props(s.generateIcon)}><Sparkles size={15} /></span>
              <span>
                <span {...stylex.props(s.itemTitle)}>Generate a new node</span>
                <span {...stylex.props(s.itemDescription)}>
                  Ask the coding agent to implement and test a Python node.
                </span>
              </span>
            </button>
          ) : null}
          {pendingCandidate ? (
            pendingCandidate.choices.map((choice, index) => {
              const active = index === hoveredChoiceIndex;
              return (
                <button
                  key={`${choice.candidatePort.name}-${index}-${connectionRouteTitle(choice.route)}`}
                  type="button"
                  role="option"
                  aria-selected={active}
                  disabled={!canInsert}
                  {...stylex.props(overlay.item, s.item, active ? overlay.itemActive : null)}
                  onMouseEnter={() => setHoveredChoiceIndex(index)}
                  onFocus={() => setHoveredChoiceIndex(index)}
                  onClick={() => selectChoice(choice)}
                >
                  <span {...stylex.props(s.itemTitle)}>
                    {choice.candidatePort.title ?? choice.candidatePort.name}
                  </span>
                  <span {...stylex.props(s.itemDescription)}>
                    {choiceLabel(session.direction, session.sourcePortTitle, choice)}
                  </span>
                </button>
              );
            })
          ) : candidates.length ? (
            candidates.map((candidate, index) => {
              const key = catalogNodeKey(candidate.spec);
              const active =
                catalogNodeKey(previewedCandidate?.spec ?? candidate.spec) ===
                key;
              return (
                <button
                  key={key}
                  type="button"
                  role="option"
                  aria-selected={active}
                  disabled={!canInsert}
                  {...stylex.props(overlay.item, s.item, active ? overlay.itemActive : null)}
                  ref={(element) => {
                    if (element) resultRefs.current.set(key, element);
                    else resultRefs.current.delete(key);
                  }}
                  onMouseEnter={() => setPreviewedKey(key)}
                  onFocus={() => setPreviewedKey(key)}
                  onClick={() => selectCandidate(candidate)}
                  onKeyDown={(event) => {
                    if (event.key === "ArrowDown") {
                      event.preventDefault();
                      focusCandidateAt(index + 1);
                    } else if (event.key === "ArrowUp") {
                      event.preventDefault();
                      focusCandidateAt(index - 1);
                    } else if (event.key === "Home") {
                      event.preventDefault();
                      focusCandidateAt(0);
                    } else if (event.key === "End") {
                      event.preventDefault();
                      focusCandidateAt(candidates.length - 1);
                    } else if (event.key === "Enter") {
                      event.preventDefault();
                      if (previewedCandidate) selectCandidate(previewedCandidate);
                    }
                  }}
                >
                  <span {...stylex.props(s.itemTitle)}>{candidate.spec.title}</span>
                  <span {...stylex.props(s.itemDescription)}>
                    {candidate.spec.description || "No description is available."}
                    {candidate.choices.length > 1
                      ? ` · ${candidate.choices.length} ways to connect`
                      : ""}
                  </span>
                </button>
              );
            })
          ) : (
            <div {...stylex.props(s.empty)}>
              No compatible nodes match this {session.direction === "upstream" ? "input" : "output"}
              {normalized ? " and search" : ""}.
            </div>
          )}
        </div>
        )}

        {view === "discovery" ? <div {...stylex.props(s.footer)}>
          {pendingCandidate ? (
            <button
              type="button"
              {...stylex.props(s.ghostButton)}
              onClick={() => {
                setPendingCandidate(null);
                setHoveredChoiceIndex(0);
              }}
            >
              Back
            </button>
          ) : (
            <button type="button" {...stylex.props(s.ghostButton)} onClick={closeDiscovery}>
              Cancel
            </button>
          )}
          <span {...stylex.props(s.hint)}>
            {canInsert
              ? finePointer
                ? "Hover to preview · Enter adds"
                : "Tap to choose a node"
              : insertDisabledReason}
          </span>
        </div> : null}
      </div>
    </>
  );
}

export type {
  ContextualCandidate,
  ContextualRouteChoice,
} from "../model/node-catalog";
