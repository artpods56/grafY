"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { ChevronDown, Grid3x3, RotateCcw, X } from "lucide-react";

import { useTheme, type ThemePreference } from "@/components/theme";
import { Button, IconButton } from "@/components/ui/button";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { phoneTouch } from "@/components/ui/touch-target";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { useCanvasGridSettings } from "../canvas/canvas-grid-settings";
import type { WorkbenchCanvasEngineKind } from "../canvas/canvas-surface-port";
import {
  GRID_CELL_SIZE_DEFAULT,
  GRID_CELL_SIZE_MAX,
  GRID_CELL_SIZE_MIN,
  GRID_CELL_SIZE_PRESETS,
  STANDARD_NODE_WIDTH_CELLS,
  lengthFromSpan,
} from "../canvas/grid-layout";
import type {
  CellCorners,
  CellGlassMaterial,
  CellStackStyle,
  CellWellStyle,
} from "../cell-canvas/cell-glass-stage";
import {
  CELL_BLUR_MAX,
  CELL_BLUR_MIN,
  CELL_CARD_FILL_MAX,
  CELL_CARD_FILL_MIN,
  CELL_FROST_MAX,
  CELL_FROST_MIN,
} from "../cell-canvas/cell-look";
import type { CellExits, UnderCardsMode } from "../cell-canvas/cell-model";
import { PIPE_FAMILIES, type PipeFamily } from "../cell-canvas/pipe-visuals";

type OnOff = "on" | "off";

const ON_OFF = [
  { value: "on", label: "On" },
  { value: "off", label: "Off" },
] satisfies { value: OnOff; label: string }[];

function stopPropagation(event: React.SyntheticEvent) {
  event.stopPropagation();
}

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
      default: "min(680px, calc(100% - 96px))",
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
    /**
     * A fixed-height row. `phoneTouch` grows `min-height`, the one property a
     * call site may not also set: StyleX keeps only the last `min-height`, so a
     * `minHeight` here would disappear and the summary would fall to its text
     * height on a desktop. The disclosure holds one line, so a height is the
     * same box, and the kit still supplies the 44px phone target.
     */
    height: "34px",
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
  section: {
    display: "grid",
    gap: "7px",
  },
  dividerSection: {
    display: "grid",
    gap: "9px",
    paddingTop: "8px",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
  },
  controlRow: {
    display: "grid",
    gap: "4px",
  },
  controlLabel: {
    color: tokens.colorMuted,
    fontSize: "10px",
    fontWeight: 700,
    letterSpacing: "0.06em",
    textTransform: "uppercase",
  },
  /**
   * A setting row: the name the kit's `Switch` draws, then the track at the far
   * end, which is how this panel read before the control moved into the kit.
   */
  switchRow: {
    width: "100%",
    justifyContent: "space-between",
  },
  hint: {
    fontSize: tokens.fontSizeXs,
    color: tokens.colorSubtle,
    lineHeight: 1.35,
  },
  sliderRow: {
    display: "grid",
    gap: "6px",
  },
  /** Preset chips take their look from `Button`; the phone target is the kit's. */
  presets: {
    display: "flex",
    flexWrap: "wrap",
    gap: "4px",
  },
  actions: {
    display: "grid",
    gap: "6px",
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
    <Switch
      // This panel is a page surface, not a canvas card, so its switches take the
      // phone target the hand-built toggle carried.
      phoneTouch
      size="md"
      label={label}
      checked={checked}
      disabled={disabled}
      onCheckedChange={onChange}
      xstyle={s.switchRow}
    />
  );
}

function ControlRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div {...stylex.props(s.controlRow)}>
      <span {...stylex.props(s.controlLabel)}>{label}</span>
      {children}
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
    cellLook,
    patchCellLook,
    cellRouting,
    patchCellRouting,
    resetSettings,
    canvasEngine,
    setCanvasEngine,
    bypassSnap,
    panelOpen,
    setPanelOpen,
  } = useCanvasGridSettings();
  const { preference, setPreference } = useTheme();

  if (!panelOpen) return null;

  const isCellCanvas = canvasEngine === "cell-canvas";
  const exampleCols = STANDARD_NODE_WIDTH_CELLS;
  const exampleRows = 2;
  const exampleWidth = lengthFromSpan(exampleCols, settings.cellSize);
  const exampleHeight = lengthFromSpan(exampleRows, settings.cellSize);

  return (
    <aside
      aria-label="Canvas lab"
      data-cell-canvas-chrome="true"
      onPointerDown={stopPropagation}
      onWheel={stopPropagation}
      {...stylex.props(s.panel)}
    >
      <header {...stylex.props(s.header)}>
        <Grid3x3 size={16} {...stylex.props(s.icon)} />
        <div {...stylex.props(s.titleBlock)}>
          <h2 {...stylex.props(s.title)}>Canvas lab</h2>
          <p {...stylex.props(s.subtitle)}>
            {isCellCanvas
              ? "Glass, pipe and routing controls"
              : "Grid and snapping controls"}
          </p>
        </div>
        <IconButton
          label="Reset canvas settings"
          title="Reset to defaults"
          size="md"
          xstyle={phoneTouch.square}
          onClick={resetSettings}
        >
          <RotateCcw size={14} />
        </IconButton>
        <IconButton
          label="Close canvas lab"
          size="md"
          xstyle={phoneTouch.square}
          onClick={() => setPanelOpen(false)}
        >
          <X size={14} />
        </IconButton>
      </header>

      <div {...stylex.props(s.section)}>
        <span {...stylex.props(s.hint)}>Canvas engine</span>
        <SegmentedControl<WorkbenchCanvasEngineKind>
          aria-label="Canvas engine"
          size="md"
          value={canvasEngine}
          onValueChange={setCanvasEngine}
          options={[
            { value: "cell-canvas", label: "Cell canvas" },
            { value: "react-flow", label: "React Flow" },
          ]}
        />
        <p {...stylex.props(s.hint)}>
          {isCellCanvas
            ? "25px cell-lattice canvas. Switch back to React Flow anytime."
            : "Legacy React Flow canvas. Switch back to Cell canvas anytime."}
        </p>
      </div>

      <ControlRow label="Theme">
        <SegmentedControl<ThemePreference>
          aria-label="Theme"
          size="sm"
          value={preference}
          onValueChange={setPreference}
          options={[
            { value: "light", label: "Light" },
            { value: "dark", label: "Dark" },
            { value: "system", label: "System" },
          ]}
        />
      </ControlRow>

      {isCellCanvas ? (
        <>
          <div {...stylex.props(s.dividerSection)}>
            <ControlRow label="Glass">
              <SegmentedControl<CellGlassMaterial>
                aria-label="Glass"
                size="sm"
                value={cellLook.material}
                onValueChange={(material) => patchCellLook({ material })}
                options={[
                  { value: "frost", label: "Frost" },
                  { value: "liquid", label: "Liquid" },
                ]}
              />
            </ControlRow>
            <Slider
              label="Blur"
              min={CELL_BLUR_MIN}
              max={CELL_BLUR_MAX}
              step={0.1}
              format={(blur) => blur.toFixed(1)}
              value={cellLook.blur}
              onValueChange={(blur) => patchCellLook({ blur })}
            />
            <Slider
              label="Frost"
              min={CELL_FROST_MIN}
              max={CELL_FROST_MAX}
              step={0.05}
              value={cellLook.frost}
              onValueChange={(frost) => patchCellLook({ frost })}
            />
            <Slider
              label="Card fill"
              min={CELL_CARD_FILL_MIN}
              max={CELL_CARD_FILL_MAX}
              step={0.02}
              format={(fill) => `${Math.round(fill * 100)}%`}
              value={cellLook.cardFill}
              onValueChange={(cardFill) => patchCellLook({ cardFill })}
            />
            <ControlRow label="Wells">
              <SegmentedControl<CellWellStyle>
                aria-label="Wells"
                size="sm"
                value={cellLook.well}
                onValueChange={(well) => patchCellLook({ well })}
                options={[
                  { value: "recessed", label: "Recessed" },
                  { value: "flat", label: "Flat" },
                  { value: "punched", label: "Punched" },
                ]}
              />
            </ControlRow>
            <ControlRow label="Pipe">
              <SegmentedControl<PipeFamily>
                aria-label="Pipe"
                size="sm"
                value={cellLook.pipe}
                onValueChange={(pipe) => patchCellLook({ pipe })}
                options={PIPE_FAMILIES}
              />
            </ControlRow>
            <ControlRow label="Corners">
              <SegmentedControl<CellCorners>
                aria-label="Corners"
                size="sm"
                value={cellLook.corners}
                onValueChange={(corners) => patchCellLook({ corners })}
                options={[
                  { value: "rounded", label: "Rounded" },
                  { value: "sharp", label: "Sharp" },
                ]}
              />
            </ControlRow>
            <ControlRow label="Stack style">
              <SegmentedControl<CellStackStyle>
                aria-label="Stack style"
                size="sm"
                value={cellLook.stackStyle}
                onValueChange={(stackStyle) => patchCellLook({ stackStyle })}
                options={[
                  { value: "fan", label: "Fan" },
                  { value: "deck", label: "Deck" },
                ]}
              />
            </ControlRow>
            <ControlRow label="Cell grid">
              <SegmentedControl<OnOff>
                aria-label="Cell grid"
                size="sm"
                value={cellLook.grid ? "on" : "off"}
                onValueChange={(value) =>
                  patchCellLook({ grid: value === "on" })
                }
                options={[
                  { value: "on", label: "Subtle" },
                  { value: "off", label: "Off" },
                ]}
              />
            </ControlRow>
          </div>

          <div {...stylex.props(s.dividerSection)}>
            <ControlRow label="Exit">
              <SegmentedControl<CellExits>
                aria-label="Exit"
                size="sm"
                value={cellRouting.exits}
                onValueChange={(exits) => patchCellRouting({ exits })}
                options={[
                  { value: "side", label: "Side" },
                  { value: "free", label: "Free" },
                ]}
              />
            </ControlRow>
            <ControlRow label="Under cards">
              <SegmentedControl<UnderCardsMode>
                aria-label="Under cards"
                size="sm"
                value={cellRouting.underCards}
                onValueChange={(underCards) => patchCellRouting({ underCards })}
                options={[
                  { value: "free", label: "Free" },
                  { value: "gaps", label: "Prefer gaps" },
                  { value: "avoid", label: "Avoid" },
                ]}
              />
            </ControlRow>
            <ControlRow label="Depth layers">
              <SegmentedControl<OnOff>
                aria-label="Depth layers"
                size="sm"
                value={cellRouting.depth ? "on" : "off"}
                onValueChange={(value) =>
                  patchCellRouting({ depth: value === "on" })
                }
                options={ON_OFF}
              />
            </ControlRow>
            <p {...stylex.props(s.hint)}>
              Drag cards to snap cell by cell; Shift+drag to marquee or
              group-drag. Hover a pipe or pill to wipe frost; drag a corner grip
              to resize.
            </p>
          </div>
        </>
      ) : (
        <>
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
            <Slider
              label="Cell size"
              min={GRID_CELL_SIZE_MIN}
              max={GRID_CELL_SIZE_MAX}
              step={1}
              value={settings.cellSize}
              format={(cellSize) => `${cellSize}px`}
              onValueChange={(cellSize) => patchSettings({ cellSize })}
            />
            <div {...stylex.props(s.presets)}>
              {GRID_CELL_SIZE_PRESETS.map((preset) => (
                <Button
                  key={preset}
                  variant={
                    settings.cellSize === preset ? "primary" : "secondary"
                  }
                  size="xs"
                  xstyle={phoneTouch.on}
                  onClick={() => patchSettings({ cellSize: preset })}
                >
                  {preset}
                </Button>
              ))}
            </div>
            <p {...stylex.props(s.example)}>
              {exampleCols}×{exampleRows} cells = {exampleWidth}×{exampleHeight}
              px
              {settings.cellSize === GRID_CELL_SIZE_DEFAULT
                ? " (standard workflow width)"
                : null}
            </p>
          </div>

          <div {...stylex.props(s.actions)}>
            <Button
              variant="secondary"
              size="md"
              xstyle={phoneTouch.on}
              disabled={!selectedCount || !settings.enabled}
              title={
                selectedCount
                  ? `Snap ${selectedCount} selected node${selectedCount === 1 ? "" : "s"} to the grid`
                  : "Select nodes to snap"
              }
              onClick={onSnapSelection}
            >
              Snap selection now
              {selectedCount ? ` (${selectedCount})` : ""}
            </Button>
          </div>

          <details {...stylex.props(s.advanced)}>
            <summary {...stylex.props(s.advancedSummary, phoneTouch.on)}>
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
                Improves large-canvas performance. Offscreen view state may
                reset.
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
        </>
      )}
    </aside>
  );
}
