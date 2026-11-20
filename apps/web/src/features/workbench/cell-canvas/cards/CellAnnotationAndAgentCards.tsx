"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";

import { IconButton } from "@/components/ui/button";
import { tokens } from "@/lib/stylex/tokens.stylex";

import {
  CellCardToolbar,
  CellResizeGrip,
  useCellInteractionStore,
} from "../CellCanvasContext";
import { annotationColorVars } from "../cell-card-geometry";
import type {
  AgentCardSurfaceData,
  AgentToolRowSpec,
  AnnotationCardSurfaceData,
  AnnotationColorToken,
} from "../cell-contracts";
import { cellCornerRadius } from "../cell-glass-stage";
import { CELL_SIZE } from "../cell-model";
import {
  CellCardShell,
  cellCardMarks as m,
  stopCardDrag,
  styled,
  useResolvedCardState,
  type CellCardBaseProps,
} from "./CellOperatorCard";

/**
 * Annotation and agent cards on the cell canvas.
 *
 * A frame annotation is not a card plate: it tints the glass under the cards
 * (render it in a `CellViewportLayer` with `layer="under-cards"`). A note
 * annotation and the agent card stand on the card plane with the shared shell.
 */

const MONO_FONT =
  "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace";

const ANNOTATION_COLORS: readonly AnnotationColorToken[] = [
  "slate",
  "blue",
  "emerald",
  "amber",
  "violet",
  "rose",
];

const pulse = stylex.keyframes({
  "0%": { opacity: 1 },
  "50%": { opacity: 0.35 },
  "100%": { opacity: 1 },
});

const s = stylex.create({
  frame: {
    position: "absolute",
    top: 0,
    left: 0,
    boxSizing: "border-box",
    borderWidth: "1px",
    borderStyle: "solid",
    pointerEvents: "auto",
    touchAction: "none",
    userSelect: "none",
    willChange: "transform",
  },
  frameSelected: {
    outlineWidth: "1.5px",
    outlineStyle: "dashed",
    outlineColor: tokens.colorAccentBorder,
    outlineOffset: "2px",
  },
  frameLabel: {
    position: "absolute",
    top: "8px",
    left: "8px",
    maxWidth: "calc(100% - 16px)",
    boxSizing: "border-box",
    height: "18px",
    display: "inline-flex",
    alignItems: "center",
    paddingInline: "7px",
    borderRadius: "9999px",
    borderWidth: "1px",
    borderStyle: "solid",
    backgroundColor: tokens.colorChrome,
    fontSize: "9px",
    fontWeight: 600,
    letterSpacing: "0.06em",
    textTransform: "uppercase",
  },
  frameCaption: {
    position: "absolute",
    top: "32px",
    left: "10px",
    right: "10px",
    margin: 0,
    fontSize: "10px",
    lineHeight: 1.4,
    opacity: 0.85,
    overflow: "hidden",
    display: "-webkit-box",
    WebkitBoxOrient: "vertical",
    WebkitLineClamp: 2,
  },
  noteBody: {
    position: "absolute",
    inset: 0,
    margin: 0,
    paddingBlock: "8px",
    paddingInline: "10px",
    overflow: "hidden",
    color: tokens.colorText,
    fontSize: "11px",
    lineHeight: 1.45,
    whiteSpace: "pre-wrap",
    overflowWrap: "anywhere",
  },
  swatch: {
    display: "block",
    width: "10px",
    height: "10px",
    borderRadius: "9999px",
    borderWidth: "1px",
    borderStyle: "solid",
  },

  modelPill: {
    fontFamily: MONO_FONT,
    maxWidth: "96px",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  pulsing: {
    animationName: {
      default: pulse,
      "@media (prefers-reduced-motion: reduce)": "none",
    },
    animationDuration: "1.2s",
    animationIterationCount: "infinite",
    animationTimingFunction: "ease-in-out",
  },
  dotIdle: { backgroundColor: tokens.colorSubtle },
  dotThinking: { backgroundColor: tokens.colorWarning },
  dotStreaming: { backgroundColor: tokens.colorInfo },
  dotError: { backgroundColor: tokens.colorDanger },
  dotPending: { backgroundColor: tokens.colorBorderStrong },
  dotDone: { backgroundColor: tokens.colorSuccess },
  // Below the 23px strip, to the plate's lower edge.
  agentBody: {
    position: "absolute",
    top: "23px",
    left: 0,
    right: 0,
    bottom: 0,
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
  },
  toolRows: {
    flexShrink: 1,
    minHeight: 0,
    overflow: "hidden",
    paddingBlock: "3px",
  },
  toolRow: {
    boxSizing: "border-box",
    height: "25px",
    display: "flex",
    alignItems: "center",
    gap: "6px",
    paddingInline: "10px",
    fontSize: "10px",
  },
  toolName: {
    flexShrink: 0,
    maxWidth: "40%",
    color: tokens.colorText,
    fontFamily: MONO_FONT,
    fontSize: "9.5px",
  },
  toolSummary: { color: tokens.colorSubtle },
  snippet: {
    flexShrink: 0,
    marginTop: "auto",
    marginInline: "6px",
    marginBottom: "6px",
    paddingBlock: "5px",
    paddingInline: "7px",
    borderRadius: tokens.radiusSm,
    backgroundColor: tokens.colorSurfaceSunken,
    color: tokens.colorMuted,
    fontSize: "10px",
    lineHeight: 1.4,
    overflow: "hidden",
    display: "-webkit-box",
    WebkitBoxOrient: "vertical",
    WebkitLineClamp: 2,
  },
});

// --- Annotation card -------------------------------------------------------

export interface CellAnnotationCardProps extends CellCardBaseProps {
  surface: AnnotationCardSurfaceData;
  onColorChange?: (cardId: string, color: AnnotationColorToken) => void;
}

function CellAnnotationCardImpl(props: CellAnnotationCardProps) {
  const { card, surface, onColorChange } = props;
  const state = useResolvedCardState(card.id, props);
  const colors = annotationColorVars(surface.color);
  const annotationData = {
    "data-annotation-variant": surface.variant,
    "data-annotation-color": surface.color,
  } as const;

  if (surface.variant === "frame") {
    return <AnnotationFrame {...props} state={state} />;
  }

  return (
    <CellCardShell
      {...props}
      kind="annotation"
      state={state}
      resizable={card.resizable ?? true}
      rootData={annotationData}
      // The tint lies over an opaque plate, so a note reads on any glass.
      plateStyle={{
        backgroundImage: `linear-gradient(${colors.fill}, ${colors.fill})`,
        borderColor: colors.border,
      }}
      toolbar={
        onColorChange ? (
          <CellCardToolbar visible={state.selected} position="top">
            {ANNOTATION_COLORS.map((color) => {
              const swatch = annotationColorVars(color);
              return (
                <IconButton
                  key={color}
                  size="2xs"
                  variant="ghost"
                  label={`Colour ${color}`}
                  pressed={color === surface.color}
                  data-annotation-swatch={color}
                  onPointerDown={stopCardDrag}
                  onClick={() => onColorChange(card.id, color)}
                >
                  <span
                    aria-hidden="true"
                    {...styled(
                      {
                        backgroundColor: swatch.fill,
                        borderColor: swatch.border,
                      },
                      s.swatch,
                    )}
                  />
                </IconButton>
              );
            })}
          </CellCardToolbar>
        ) : null
      }
    >
      <p data-annotation-body="true" {...stylex.props(s.noteBody)}>
        {surface.bodyText}
      </p>
    </CellCardShell>
  );
}

/** A tinted region of the glass, labelled in its top-left corner. */
function AnnotationFrame({
  card,
  surface,
  state,
  visualOffset,
  corners = "rounded",
  onCardPointerDown,
  onResizeStart,
  onResizeMove,
  onResizeEnd,
}: CellAnnotationCardProps & {
  state: ReturnType<typeof useResolvedCardState>;
}) {
  const store = useCellInteractionStore();
  const colors = annotationColorVars(surface.color);
  const x = card.col * CELL_SIZE + (visualOffset?.x ?? 0);
  const y = card.row * CELL_SIZE + (visualOffset?.y ?? 0);
  return (
    <div
      data-cell-card="true"
      data-card-id={card.id}
      data-card-kind="annotation"
      data-annotation-variant="frame"
      data-annotation-color={surface.color}
      data-selected={state.selected ? "true" : "false"}
      data-dragging={state.dragging ? "true" : "false"}
      onPointerDown={(event) => onCardPointerDown?.(card.id, event)}
      onPointerEnter={() => store?.setHoveredCard(card.id)}
      onPointerLeave={() => store?.setHoveredCard(null)}
      {...styled(
        {
          width: card.widthCells * CELL_SIZE,
          height: card.heightCells * CELL_SIZE,
          transform: `translate3d(${x}px, ${y}px, 0)`,
          backgroundColor: colors.fill,
          borderColor: colors.border,
          color: colors.text,
          borderRadius: cellCornerRadius(corners),
          cursor: state.dragging ? "grabbing" : "grab",
        },
        s.frame,
        state.selected && s.frameSelected,
      )}
    >
      <span
        data-annotation-label="true"
        {...styled({ borderColor: colors.border }, s.frameLabel)}
      >
        <span {...stylex.props(m.ellipsis)}>{card.title}</span>
      </span>
      {surface.bodyText ? (
        <p {...stylex.props(s.frameCaption)}>{surface.bodyText}</p>
      ) : null}
      {(card.resizable ?? true) ? (
        <CellResizeGrip
          cardId={card.id}
          edge="se"
          visible={state.selected && !state.dragging}
          onResizeStart={onResizeStart}
          onResizeMove={onResizeMove}
          onResizeEnd={onResizeEnd}
        />
      ) : null}
    </div>
  );
}

export const CellAnnotationCard = React.memo(CellAnnotationCardImpl);

// --- Agent card ------------------------------------------------------------

export interface CellAgentCardProps extends CellCardBaseProps {
  surface: AgentCardSurfaceData;
}

const AGENT_STATUS_TEXT: Record<AgentCardSurfaceData["agentStatus"], string> = {
  idle: "Idle",
  thinking: "Thinking",
  streaming: "Streaming",
  error: "Error",
};

function agentDotStyle(
  status: AgentCardSurfaceData["agentStatus"],
): stylex.StyleXStyles {
  switch (status) {
    case "idle":
      return s.dotIdle;
    case "thinking":
      return [s.dotThinking, s.pulsing];
    case "streaming":
      return [s.dotStreaming, s.pulsing];
    case "error":
      return s.dotError;
  }
}

function toolDotStyle(status: AgentToolRowSpec["status"]): stylex.StyleXStyles {
  switch (status) {
    case "pending":
      return s.dotPending;
    case "running":
      return [s.dotStreaming, s.pulsing];
    case "done":
      return s.dotDone;
    case "error":
      return s.dotError;
  }
}

function CellAgentCardImpl(props: CellAgentCardProps) {
  const { card, surface } = props;
  const state = useResolvedCardState(card.id, props);
  const toolRows = surface.recentToolRows ?? [];

  return (
    <CellCardShell
      {...props}
      kind="agent"
      state={state}
      resizable={card.resizable ?? true}
      rootData={{ "data-agent-status": surface.agentStatus }}
      headerExtra={
        <>
          <span
            title={surface.modelLabel}
            {...stylex.props(m.chip, s.modelPill)}
          >
            {surface.modelLabel}
          </span>
          <span
            data-agent-status-indicator={surface.agentStatus}
            {...stylex.props(m.status)}
          >
            <span
              aria-hidden="true"
              {...stylex.props(m.dot, agentDotStyle(surface.agentStatus))}
            />
            {AGENT_STATUS_TEXT[surface.agentStatus]}
          </span>
        </>
      }
      strip={
        <>
          <span {...stylex.props(m.ellipsis, m.grow)}>{card.subtitle}</span>
          <span data-agent-tool-count="true" {...stylex.props(m.chip)}>
            {surface.linkedToolCount === 1
              ? "1 tool"
              : `${surface.linkedToolCount} tools`}
          </span>
        </>
      }
    >
      <div {...stylex.props(s.agentBody)}>
        {toolRows.length ? (
          <div {...stylex.props(s.toolRows)}>
            {toolRows.map((row) => (
              <div
                key={row.id}
                data-agent-tool-row={row.id}
                data-tool-status={row.status}
                {...stylex.props(s.toolRow)}
              >
                <span {...stylex.props(s.toolName, m.ellipsis)}>
                  {row.toolName}
                </span>
                <span {...stylex.props(s.toolSummary, m.ellipsis, m.grow)}>
                  {row.summary}
                </span>
                <span data-tool-status-badge="true" {...stylex.props(m.chip)}>
                  <span
                    aria-hidden="true"
                    {...stylex.props(m.dot, toolDotStyle(row.status))}
                  />
                  {row.status}
                </span>
              </div>
            ))}
          </div>
        ) : null}
        {surface.lastMessageSnippet ? (
          <p data-agent-message-snippet="true" {...stylex.props(s.snippet)}>
            {surface.lastMessageSnippet}
          </p>
        ) : null}
      </div>
    </CellCardShell>
  );
}

export const CellAgentCard = React.memo(CellAgentCardImpl);
