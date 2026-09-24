"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  NodeToolbar,
  Position,
  useViewport,
  type NodeProps,
} from "@xyflow/react";
import { X } from "lucide-react";

import { tokens } from "@/lib/stylex/tokens.stylex";
import { RemoteSelectionRing } from "../../room/RemoteSelectionRing";
import {
  ANNOTATION_COLOR_SWATCHES,
  normalizeAnnotationColor,
  type AnnotationColor,
  type AnnotationLayout,
  type AnnotationNode as AnnotationNodeType,
} from "../annotations";
import { useOptionalCanvasGridSettings } from "../canvas-grid-settings";
import { gridShellOutset, shouldSnapSize, snapLength } from "../grid-layout";
import { SafeMarkdown } from "../safe-markdown";

const s = stylex.create({
  shell: {
    position: "relative",
    boxSizing: "border-box",
    overflow: "visible",
  },
  selectedShape: {
    // Soft selection cue — shapes are background plates, not bordered boxes.
    outlineWidth: "1.5px",
    outlineStyle: "dashed",
    outlineColor: tokens.colorAccentBorder,
    outlineOffset: "2px",
  },
  selectedText: {
    outlineWidth: "1.5px",
    outlineStyle: "dashed",
    outlineColor: tokens.colorAccentBorder,
    outlineOffset: "4px",
  },
  toolbar: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
    padding: "4px 6px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorChrome,
    boxShadow: tokens.shadowNode,
  },
  colorPicker: {
    position: "relative",
  },
  colorTrigger: {
    width: "28px",
    height: "22px",
    padding: 0,
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "6px",
    cursor: "pointer",
  },
  colorPopover: {
    position: "absolute",
    // Open above the trigger so the menu isn't buried under the node body.
    bottom: "calc(100% + 6px)",
    left: "50%",
    transform: "translateX(-50%)",
    zIndex: 20,
    display: "grid",
    gridTemplateColumns: "repeat(4, 22px)",
    gap: "6px",
    padding: "8px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorChrome,
    boxShadow: tokens.shadowNode,
  },
  colorSwatch: {
    width: "22px",
    height: "22px",
    padding: 0,
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "6px",
    cursor: "pointer",
  },
  colorSwatchActive: {
    outlineWidth: "2px",
    outlineStyle: "solid",
    outlineColor: tokens.colorAccentBorder,
    outlineOffset: "1px",
  },
  removeButton: {
    width: "22px",
    height: "22px",
    display: "grid",
    placeItems: "center",
    padding: 0,
    borderWidth: 0,
    borderRadius: "9999px",
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorDangerHover,
    },
    color: tokens.colorText,
    cursor: "pointer",
  },
  textSurface: {
    width: "100%",
    height: "100%",
    margin: 0,
    paddingTop: "2px",
    paddingRight: "10px",
    paddingBottom: "2px",
    paddingLeft: "10px",
    borderWidth: 0,
    boxSizing: "border-box",
    backgroundColor: "transparent",
    color: "inherit",
    overflow: "auto",
  },
  textPreview: {
    cursor: "grab",
  },
  textEditor: {
    resize: "none",
    fontFamily: "ui-sans-serif, system-ui, sans-serif",
    fontSize: "14px",
    lineHeight: 1.45,
    outline: "none",
    whiteSpace: "pre-wrap",
  },
  textPlaceholder: {
    opacity: 0.45,
    fontStyle: "italic",
  },
  shape: {
    position: "relative",
    boxSizing: "border-box",
  },
  resizeHandle: {
    position: "absolute",
    width: "14px",
    height: "14px",
    padding: 0,
    borderWidth: 0,
    borderRadius: "3px",
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorHoverStrong,
    },
    cursor: "nwse-resize",
    touchAction: "none",
  },
  resizeGlyph: {
    position: "absolute",
    right: "3px",
    bottom: "3px",
    width: "7px",
    height: "7px",
    borderRightWidth: 2,
    borderRightStyle: "solid",
    borderBottomWidth: 2,
    borderBottomStyle: "solid",
    borderColor: tokens.colorSubtle,
    opacity: 0.75,
    pointerEvents: "none",
  },
});

function nodragProps(props: ReturnType<typeof stylex.props>) {
  return {
    ...props,
    className: `nodrag nopan nowheel${props.className ? ` ${props.className}` : ""}`,
  };
}

function AnnotationColorPicker({
  color,
  onChange,
}: {
  color: AnnotationColor;
  onChange: (color: AnnotationColor) => void;
}) {
  const [open, setOpen] = React.useState(false);
  const rootRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    // Defer so the opening click doesn't immediately dismiss the popover.
    const timer = window.setTimeout(() => {
      document.addEventListener("pointerdown", onPointerDown, true);
      document.addEventListener("keydown", onKeyDown);
    }, 0);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const stopToolbarEvent = (event: React.SyntheticEvent) => {
    event.stopPropagation();
  };

  return (
    <div
      ref={rootRef}
      {...nodragProps(stylex.props(s.colorPicker))}
      onPointerDown={stopToolbarEvent}
      onMouseDown={stopToolbarEvent}
      onClick={stopToolbarEvent}
    >
      <button
        type="button"
        aria-label="Annotation color"
        aria-expanded={open}
        aria-haspopup="dialog"
        title="Color"
        {...stylex.props(s.colorTrigger)}
        style={{ backgroundColor: color }}
        onPointerDown={(event) => {
          // pointerdown is more reliable than click inside RF portals.
          event.preventDefault();
          event.stopPropagation();
          setOpen((current) => !current);
        }}
      />
      {open ? (
        <div
          role="dialog"
          aria-label="Choose annotation color"
          {...stylex.props(s.colorPopover)}
        >
          {ANNOTATION_COLOR_SWATCHES.map((swatch) => {
            const active = swatch === color;
            return (
              <button
                key={swatch}
                type="button"
                aria-label={`Color ${swatch}`}
                aria-pressed={active}
                title={swatch}
                {...stylex.props(
                  s.colorSwatch,
                  active ? s.colorSwatchActive : null,
                )}
                style={{ backgroundColor: swatch }}
                onPointerDown={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  onChange(swatch);
                  setOpen(false);
                }}
              />
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

function AnnotationResizeHandle({
  layout,
  onDraft,
  onCommit,
  outset = 0,
}: {
  layout: AnnotationLayout;
  onDraft: (layout: AnnotationLayout) => void;
  onCommit: (layout: AnnotationLayout) => void;
  /** Pull the handle out to the painted shape corner when shapes outset. */
  outset?: number;
}) {
  const { zoom } = useViewport();
  const grid = useOptionalCanvasGridSettings();
  const dragRef = React.useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    start: AnnotationLayout;
  } | null>(null);

  return (
    <button
      type="button"
      aria-label="Resize annotation"
      {...nodragProps(stylex.props(s.resizeHandle))}
      style={{ right: 2 - outset, bottom: 2 - outset }}
      onPointerDown={(event) => {
        event.stopPropagation();
        event.currentTarget.setPointerCapture(event.pointerId);
        dragRef.current = {
          pointerId: event.pointerId,
          startX: event.clientX,
          startY: event.clientY,
          start: layout,
        };
      }}
      onPointerMove={(event) => {
        const drag = dragRef.current;
        if (!drag || drag.pointerId !== event.pointerId) return;
        const scale = zoom > 0 ? zoom : 1;
        let next: AnnotationLayout = {
          width: drag.start.width + (event.clientX - drag.startX) / scale,
          height: drag.start.height + (event.clientY - drag.startY) / scale,
        };
        const settings = grid?.settings;
        if (
          settings &&
          shouldSnapSize(settings, { drafting: true, bypass: false })
        ) {
          next = {
            width: snapLength(next.width, settings.cellSize, 24),
            height: snapLength(next.height, settings.cellSize, 24),
          };
        }
        onDraft({
          width: Math.max(24, next.width),
          height: Math.max(24, next.height),
        });
      }}
      onPointerUp={(event) => {
        const drag = dragRef.current;
        if (!drag || drag.pointerId !== event.pointerId) return;
        dragRef.current = null;
        onCommit(layout);
      }}
    >
      <span {...stylex.props(s.resizeGlyph)} />
    </button>
  );
}

function FloatingTextAnnotation({
  id,
  text,
  color,
  onTextChange,
}: {
  id: string;
  text: string;
  color: string;
  onTextChange?: (nodeId: string, text: string) => void;
}) {
  const [editing, setEditing] = React.useState(false);
  const editorRef = React.useRef<HTMLTextAreaElement | null>(null);

  React.useEffect(() => {
    if (!editing) return;
    const node = editorRef.current;
    if (!node) return;
    node.focus();
    node.select();
  }, [editing]);

  if (editing) {
    return (
      <textarea
        ref={editorRef}
        aria-label="Edit annotation markdown"
        value={text}
        {...nodragProps(stylex.props(s.textSurface, s.textEditor))}
        style={{ color }}
        onChange={(event) => onTextChange?.(id, event.target.value)}
        onBlur={() => setEditing(false)}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.stopPropagation();
            setEditing(false);
          }
        }}
        onPointerDown={(event) => event.stopPropagation()}
      />
    );
  }

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label="Annotation text"
      {...stylex.props(s.textSurface, s.textPreview)}
      style={{ color }}
      onDoubleClick={(event) => {
        event.stopPropagation();
        setEditing(true);
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === "F2") {
          event.preventDefault();
          event.stopPropagation();
          setEditing(true);
        }
      }}
    >
      {text.trim() ? (
        <SafeMarkdown>{text}</SafeMarkdown>
      ) : (
        <span {...stylex.props(s.textPlaceholder)}>Double-click to write…</span>
      )}
    </div>
  );
}

export default function AnnotationNodeCard({
  id,
  data,
  selected,
}: NodeProps<AnnotationNodeType>) {
  const [draftLayout, setDraftLayout] = React.useState<AnnotationLayout | null>(
    null,
  );
  const grid = useOptionalCanvasGridSettings();
  const layout = draftLayout ?? data.layout;
  const color = normalizeAnnotationColor(data.color);
  const isText = data.kind === "text";
  // Borderless tinted plate — reads as a background, not a framed container.
  const shapeFill = `color-mix(in oklab, canvas 86%, ${color})`;
  // Opposite of workflow card inset: bleed past occupied cells into the gutter.
  const outset = isText
    ? 0
    : gridShellOutset(grid?.settings, grid?.bypassSnap ?? false);
  const shapeStyle: React.CSSProperties = {
    width: layout.width + outset * 2,
    height: layout.height + outset * 2,
    margin: outset ? -outset : 0,
    borderWidth: 0,
    backgroundColor: shapeFill,
  };

  return (
    <div
      data-testid="annotation-node"
      data-annotation-kind={data.kind}
      {...stylex.props(s.shell, selected && isText ? s.selectedText : null)}
      style={{ width: layout.width, height: layout.height }}
    >
      {isText && data.remoteSelectionColor ? (
        <RemoteSelectionRing color={data.remoteSelectionColor} />
      ) : null}

      <NodeToolbar
        isVisible={selected}
        position={Position.Top}
        offset={12 + outset}
        className="nodrag nopan nowheel"
        // Annotations sit at a negative z; RF would place this toolbar at z≈0
        // and clicks fall through to the pane. Keep it above the canvas chrome.
        style={{ zIndex: 1001 }}
      >
        <div
          {...nodragProps(stylex.props(s.toolbar))}
          onPointerDown={(event) => event.stopPropagation()}
          onMouseDown={(event) => event.stopPropagation()}
        >
          <AnnotationColorPicker
            color={color}
            onChange={(next) => {
              data.onColorChange?.(id, normalizeAnnotationColor(next));
            }}
          />
          <button
            type="button"
            aria-label="Remove annotation"
            {...stylex.props(s.removeButton)}
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => {
              event.stopPropagation();
              data.onRemoveNode?.(id);
            }}
          >
            <X size={12} />
          </button>
        </div>
      </NodeToolbar>

      {isText ? (
        <FloatingTextAnnotation
          key={selected ? "selected" : "unselected"}
          id={id}
          text={data.text}
          color={color}
          onTextChange={data.onTextChange}
        />
      ) : (
        <div
          {...stylex.props(s.shape, selected ? s.selectedShape : null)}
          style={{
            ...shapeStyle,
            borderRadius: data.kind === "rectangle" ? 8 : "9999px",
          }}
        >
          {data.remoteSelectionColor ? (
            <RemoteSelectionRing color={data.remoteSelectionColor} />
          ) : null}
        </div>
      )}

      {selected ? (
        <AnnotationResizeHandle
          layout={layout}
          outset={outset}
          onDraft={setDraftLayout}
          onCommit={(next) => {
            setDraftLayout(null);
            data.onLayoutChange?.(id, next);
          }}
        />
      ) : null}
    </div>
  );
}
