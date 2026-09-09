"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { ChevronDown, Grid3x3, RotateCcw, X } from "lucide-react";

import { tokens } from "@/lib/stylex/tokens.stylex";
import { useCanvasGridSettings } from "../canvas/canvas-grid-settings";
import {
  GRID_CELL_SIZE_DEFAULT,
  GRID_CELL_SIZE_MAX,
  GRID_CELL_SIZE_MIN,
  GRID_CELL_SIZE_PRESETS,
  STANDARD_NODE_WIDTH_CELLS,
  lengthFromSpan,
} from "../canvas/grid-layout";

const s = stylex.create({
  panel: {
    position: "absolute",
    zIndex: 40,
    top: {
      default: "70px",
      "@media (max-width: 620px)":
        "calc(var(--grafy-mobile-overlay-top, 68px) + env(safe-area-inset-top, 0px))",
    },
    right: {
      default: "13px",
      "@media (max-width: 620px)":
        "calc(12px + env(safe-area-inset-right, 0px))",
    },
    left: {
      default: "auto",
    },
    width: {
      default: "min(272px, calc(100% - 26px))",
      "@media (max-width: 620px)": "min(296px, calc(100% - 24px))",
    },
    maxHeight: {
      default: "min(560px, calc(100% - 96px))",
      "@media (max-width: 620px)":
        "min(480px, calc(100% - 92px - env(safe-area-inset-top, 0px) - env(safe-area-inset-bottom, 0px)))",
    },
    display: "grid",
    gap: "9px",
    padding: "10px",
    overflowY: "auto",
    overscrollBehaviorY: "contain",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "14px",
    backgroundColor: tokens.colorChrome,
    boxShadow: tokens.shadowNodeRaised,
    color: tokens.colorText,
  },
  header: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
  },
  titleBlock: {
    flex: 1,
    minWidth: 0,
    display: "grid",
    gap: "2px",
  },
  title: {
    margin: 0,
    fontSize: tokens.fontSizeMd,
    fontWeight: 700,
    color: tokens.colorTextEmphasis,
  },
  subtitle: {
    margin: 0,
    fontSize: tokens.fontSizeXs,
    color: tokens.colorMuted,
    lineHeight: 1.35,
  },
  advanced: {
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
  },
  advancedSummary: {
    minHeight: {
      default: "34px",
      "@media (max-width: 620px)": "44px",
    },
    display: "flex",
    listStyle: "none",
    alignItems: "center",
    gap: "7px",
    color: tokens.colorMuted,
    cursor: "pointer",
    fontSize: tokens.fontSizeSm,
    fontWeight: 650,
  },
  advancedChevron: {
    marginLeft: "auto",
    color: tokens.colorSubtle,
  },
  advancedBody: {
    display: "grid",
    gap: "7px",
    paddingBlock: "2px 4px",
  },
  icon: {
    color: tokens.colorAccent,
    flexShrink: 0,
  },
  iconButton: {
    width: {
      default: "28px",
      "@media (max-width: 620px)": "44px",
    },
    height: {
      default: "28px",
      "@media (max-width: 620px)": "44px",
    },
    display: "grid",
    placeItems: "center",
    borderWidth: 0,
    borderRadius: "8px",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: tokens.colorMuted,
    cursor: "pointer",
    flexShrink: 0,
  },
  section: {
    display: "grid",
    gap: "7px",
  },
  row: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "10px",
    minHeight: "28px",
  },
  label: {
    fontSize: tokens.fontSizeSm,
    color: tokens.colorText,
    userSelect: "none",
  },
  hint: {
    fontSize: tokens.fontSizeXs,
    color: tokens.colorSubtle,
    lineHeight: 1.35,
  },
  switch: {
    width: {
      default: "36px",
      "@media (max-width: 620px)": "44px",
    },
    height: {
      default: "20px",
      "@media (max-width: 620px)": "44px",
    },
    display: "grid",
    placeItems: "center",
    flexShrink: 0,
    borderWidth: 0,
    backgroundColor: "transparent",
    cursor: "pointer",
    padding: 0,
  },
  switchTrack: {
    position: "relative",
    width: "100%",
    height: {
      default: "20px",
      "@media (max-width: 620px)": "28px",
    },
    display: "block",
    borderRadius: "999px",
    backgroundColor: tokens.colorSurfaceSunken,
  },
  switchOn: {
    backgroundColor: tokens.colorAccent,
  },
  switchThumb: {
    position: "absolute",
    top: "2px",
    left: "2px",
    width: {
      default: "16px",
      "@media (max-width: 620px)": "24px",
    },
    height: {
      default: "16px",
      "@media (max-width: 620px)": "24px",
    },
    borderRadius: "999px",
    backgroundColor: tokens.colorOnAccent,
    transitionProperty: "transform",
    transitionDuration: "120ms",
  },
  switchThumbOn: {
    transform: "translateX(16px)",
  },
  sliderRow: {
    display: "grid",
    gap: "6px",
  },
  sliderMeta: {
    display: "flex",
    alignItems: "baseline",
    justifyContent: "space-between",
    gap: "8px",
  },
  sliderValue: {
    fontSize: tokens.fontSizeSm,
    fontWeight: 700,
    color: tokens.colorAccent,
    fontVariantNumeric: "tabular-nums",
  },
  slider: {
    width: "100%",
    accentColor: tokens.colorAccent,
    cursor: "pointer",
  },
  presets: {
    display: "flex",
    flexWrap: "wrap",
    gap: "4px",
  },
  preset: {
    height: {
      default: "26px",
      "@media (max-width: 620px)": "44px",
    },
    paddingInline: "8px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "7px",
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorHover,
    },
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    fontWeight: 650,
    cursor: "pointer",
  },
  presetActive: {
    borderColor: tokens.colorAccentBorder,
    backgroundColor: tokens.colorAccentSoft,
    color: tokens.colorAccent,
  },
  actions: {
    display: "grid",
    gap: "6px",
  },
  actionButton: {
    height: {
      default: "32px",
      "@media (max-width: 620px)": "44px",
    },
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "6px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "8px",
    backgroundColor: {
      default: tokens.colorSurfaceMuted,
      ":hover": tokens.colorHover,
      ":disabled": tokens.colorSurfaceMuted,
    },
    color: {
      default: tokens.colorText,
      ":disabled": tokens.colorTextDisabled,
    },
    cursor: { default: "pointer", ":disabled": "not-allowed" },
    fontSize: tokens.fontSizeSm,
    fontWeight: 650,
  },
  bypass: {
    padding: "6px 8px",
    borderRadius: "8px",
    backgroundColor: tokens.colorAccentSoft,
    color: tokens.colorAccent,
    fontSize: tokens.fontSizeXs,
    fontWeight: 650,
  },
  example: {
    fontSize: tokens.fontSizeXs,
    color: tokens.colorMuted,
    fontVariantNumeric: "tabular-nums",
  },
});

function Toggle({
  checked,
  label,
  onChange,
  disabled,
}: {
  checked: boolean;
  label: string;
  onChange: (next: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <div {...stylex.props(s.row)}>
      <span {...stylex.props(s.label)}>{label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        {...stylex.props(s.switch)}
        onClick={() => onChange(!checked)}
      >
        <span {...stylex.props(s.switchTrack, checked ? s.switchOn : null)}>
          <span
            {...stylex.props(s.switchThumb, checked ? s.switchThumbOn : null)}
          />
        </span>
      </button>
    </div>
  );
}

export function CanvasGridSettingsPanel({
  selectedCount,
  onSnapSelection,
}: {
  selectedCount: number;
  onSnapSelection: () => void;
}) {
  const {
    settings,
    patchSettings,
    resetSettings,
    bypassSnap,
    panelOpen,
    setPanelOpen,
  } = useCanvasGridSettings();

  if (!panelOpen) return null;

  const exampleCols = STANDARD_NODE_WIDTH_CELLS;
  const exampleRows = 2;
  const exampleWidth = lengthFromSpan(exampleCols, settings.cellSize);
  const exampleHeight = lengthFromSpan(exampleRows, settings.cellSize);

  return (
    <aside aria-label="Canvas lab" {...stylex.props(s.panel)}>
      <header {...stylex.props(s.header)}>
        <Grid3x3 size={16} {...stylex.props(s.icon)} />
        <div {...stylex.props(s.titleBlock)}>
          <h2 {...stylex.props(s.title)}>Canvas lab</h2>
          <p {...stylex.props(s.subtitle)}>Grid and snapping controls</p>
        </div>
        <button
          type="button"
          aria-label="Reset canvas settings"
          title="Reset to defaults"
          {...stylex.props(s.iconButton)}
          onClick={resetSettings}
        >
          <RotateCcw size={14} />
        </button>
        <button
          type="button"
          aria-label="Close canvas lab"
          {...stylex.props(s.iconButton)}
          onClick={() => setPanelOpen(false)}
        >
          <X size={14} />
        </button>
      </header>

      <div {...stylex.props(s.section)}>
        <Toggle
          label="Enable snapping"
          checked={settings.enabled}
          onChange={(enabled) => patchSettings({ enabled })}
        />
        <Toggle
          label="Show grid lines"
          checked={settings.showBackground}
          onChange={(showBackground) => patchSettings({ showBackground })}
        />
      </div>

      <div {...stylex.props(s.sliderRow)}>
        <div {...stylex.props(s.sliderMeta)}>
          <span {...stylex.props(s.label)}>Cell size</span>
          <span {...stylex.props(s.sliderValue)}>{settings.cellSize}px</span>
        </div>
        <input
          type="range"
          min={GRID_CELL_SIZE_MIN}
          max={GRID_CELL_SIZE_MAX}
          step={1}
          value={settings.cellSize}
          aria-label="Grid cell size"
          {...stylex.props(s.slider)}
          onChange={(event) =>
            patchSettings({ cellSize: Number(event.target.value) })
          }
        />
        <div {...stylex.props(s.presets)}>
          {GRID_CELL_SIZE_PRESETS.map((preset) => (
            <button
              key={preset}
              type="button"
              {...stylex.props(
                s.preset,
                settings.cellSize === preset ? s.presetActive : null,
              )}
              onClick={() => patchSettings({ cellSize: preset })}
            >
              {preset}
            </button>
          ))}
        </div>
        <p {...stylex.props(s.example)}>
          {exampleCols}×{exampleRows} cells = {exampleWidth}×{exampleHeight}px
          {settings.cellSize === GRID_CELL_SIZE_DEFAULT
            ? " (standard workflow width)"
            : null}
        </p>
      </div>

      <div {...stylex.props(s.actions)}>
        <button
          type="button"
          disabled={!selectedCount || !settings.enabled}
          title={
            selectedCount
              ? `Snap ${selectedCount} selected node${selectedCount === 1 ? "" : "s"} to the grid`
              : "Select nodes to snap"
          }
          {...stylex.props(s.actionButton)}
          onClick={onSnapSelection}
        >
          Snap selection now
          {selectedCount ? ` (${selectedCount})` : ""}
        </button>
      </div>

      <details {...stylex.props(s.advanced)}>
        <summary {...stylex.props(s.advancedSummary)}>
          Advanced
          <ChevronDown
            aria-hidden="true"
            size={14}
            {...stylex.props(s.advancedChevron)}
          />
        </summary>
        <div {...stylex.props(s.advancedBody)}>
          <Toggle
            label="Render visible elements only"
            checked={settings.onlyRenderVisibleElements}
            onChange={(onlyRenderVisibleElements) =>
              patchSettings({ onlyRenderVisibleElements })
            }
          />
          <p {...stylex.props(s.hint)}>
            Improves large-canvas performance. Offscreen view state may reset.
          </p>
          <Toggle
            label="Snap position"
            checked={settings.snapPosition}
            disabled={!settings.enabled}
            onChange={(snapPosition) => patchSettings({ snapPosition })}
          />
          <Toggle
            label="Snap size"
            checked={settings.snapSize}
            disabled={!settings.enabled}
            onChange={(snapSize) => patchSettings({ snapSize })}
          />
          <Toggle
            label="Snap while dragging"
            checked={settings.snapWhileDragging}
            disabled={!settings.enabled || !settings.snapPosition}
            onChange={(snapWhileDragging) =>
              patchSettings({ snapWhileDragging })
            }
          />
          <Toggle
            label="Snap while resizing"
            checked={settings.snapWhileResizing}
            disabled={!settings.enabled || !settings.snapSize}
            onChange={(snapWhileResizing) =>
              patchSettings({ snapWhileResizing })
            }
          />
          <Toggle
            label="Workflow corner resize"
            checked={settings.allowWorkflowCornerResize}
            onChange={(allowWorkflowCornerResize) =>
              patchSettings({ allowWorkflowCornerResize })
            }
          />
          <p {...stylex.props(s.hint)}>
            Hold Alt while moving or resizing for free placement.
          </p>
          {bypassSnap ? (
            <p role="status" {...stylex.props(s.bypass)}>
              Alt held — free placement
            </p>
          ) : null}
        </div>
      </details>
    </aside>
  );
}
