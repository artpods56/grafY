"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Tabs } from "@base-ui/react/tabs";

import { Button } from "@/components/ui/button";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Slider } from "@/components/ui/slider";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { CANVAS_LAB_SECTIONS, canvasLabHelp } from "./canvas-lab";
import { useCanvasLab } from "./CanvasLabProvider";

/*
 * A detached instrument panel: one rounded shell, the Canvas/Nodes switch pinned
 * at the top, a scrolling body, and Reset/Copy link pinned at the foot so neither
 * scrolls out of reach on a short screen. Hosts place and size it through `xstyle`.
 */
const s = stylex.create({
  panel: {
    display: "flex",
    flexDirection: "column",
    gap: "10px",
    boxSizing: "border-box",
    width: { default: "244px", "@media (max-width: 620px)": "100%" },
    maxHeight: {
      default: "calc(100svh - 110px)",
      "@media (max-width: 620px)": "100%",
    },
    padding: "10px",
    overflow: "hidden",
    border: `1px solid ${tokens.colorBorder}`,
    borderRadius: "12px",
    backgroundColor: tokens.colorChrome,
    boxShadow: "0 8px 24px rgba(0, 0, 0, 0.18)",
    color: tokens.colorText,
  },
  tabsRoot: {
    display: "flex",
    flexDirection: "column",
    gap: "10px",
    flex: "1 1 auto",
    minHeight: 0,
  },
  body: {
    display: "grid",
    alignContent: "start",
    gap: "12px",
    flex: "1 1 auto",
    minHeight: 0,
    overflowY: "auto",
    overscrollBehavior: "contain",
    scrollbarWidth: "thin",
    // Keeps focus rings of edge-to-edge controls inside the scrollport.
    paddingInline: "2px",
    marginInline: "-2px",
  },
  group: { display: "grid", gap: "12px" },
  tabList: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)",
    flexShrink: 0,
    gap: "2px",
    padding: "2px",
    borderRadius: tokens.radiusLg,
    backgroundColor: tokens.colorSurfaceRaised,
  },
  tab: {
    minHeight: {
      default: "30px",
      "@media (max-width: 620px), (pointer: coarse)": "40px",
    },
    borderWidth: 0,
    borderStyle: "none",
    borderRadius: tokens.radiusMd,
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorHover,
      ":is([data-active])": tokens.colorChrome,
    },
    boxShadow: {
      default: "none",
      ":is([data-active])": tokens.shadowNode,
    },
    color: {
      default: tokens.colorMuted,
      ":hover": tokens.colorText,
      ":is([data-active])": tokens.colorTextEmphasis,
    },
    fontSize: tokens.fontSizeSm,
    fontWeight: 600,
    cursor: "pointer",
    outline: {
      default: "none",
      ":focus-visible": `2px solid ${tokens.colorAccentBorder}`,
    },
    outlineOffset: "-2px",
  },
  row: { display: "grid", gap: "5px" },
  label: {
    color: tokens.colorMuted,
    fontSize: "10px",
    fontWeight: 800,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
  },
  slider: { fontWeight: 600 },
  summary: {
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    fontWeight: 700,
    cursor: "pointer",
    paddingBlock: "4px",
    borderRadius: tokens.radiusSm,
    outline: {
      default: "none",
      ":focus-visible": `2px solid ${tokens.colorAccentBorder}`,
    },
  },
  footer: {
    display: "grid",
    flexShrink: 0,
    gap: "6px",
    paddingTop: "10px",
    borderTop: `1px solid ${tokens.colorDivider}`,
  },
  actions: {
    display: "flex",
    gap: "6px",
    alignItems: "center",
    flexWrap: "wrap",
  },
  mobileControl: {
    minHeight: {
      default: null,
      "@media (max-width: 620px), (pointer: coarse)": "44px",
    },
  },
  help: {
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    overflowWrap: "anywhere",
  },
});

export function CanvasLabRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div {...stylex.props(s.row)}>
      <span {...stylex.props(s.label)}>{label}</span>
      {children}
    </div>
  );
}

type SidebarTabs = {
  value: "canvas" | "nodes";
  onChange: (value: "canvas" | "nodes") => void;
  nodes: React.ReactNode;
};

export function CanvasLabPanel({
  canvasControls,
  tabs,
  close,
  reset,
  help,
  id,
  xstyle,
}: {
  canvasControls?: React.ReactNode;
  tabs?: SidebarTabs;
  close?: () => void;
  reset?: () => void;
  help?: React.ReactNode;
  id?: string;
  xstyle?: stylex.StyleXStyles;
}) {
  const lab = useCanvasLab();
  const [copyStatus, setCopyStatus] = React.useState("");
  if (!lab.enabled) return null;

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopyStatus("Link copied");
    } catch {
      setCopyStatus("Copy the link from the address bar");
    }
  }

  const canvasContent = (
    <>
      {canvasControls}
      {CANVAS_LAB_SECTIONS.filter((section) => !section.dev || lab.enabled).map(
        (section) => (
          <details
            key={section.id}
            open={section.id === "appearance" || undefined}
          >
            <summary {...stylex.props(s.summary)}>{section.title}</summary>
            <div {...stylex.props(s.group)}>
              {section.controls.map((control) =>
                control.kind === "choice" ? (
                  <CanvasLabRow key={control.key} label={control.label}>
                    <SegmentedControl
                      aria-label={control.label}
                      value={control.encode(lab.settings)}
                      options={control.options}
                      onValueChange={(value) =>
                        lab.change(control.decode(value))
                      }
                    />
                  </CanvasLabRow>
                ) : (
                  <Slider
                    key={control.key}
                    label={control.label}
                    xstyle={s.slider}
                    min={control.range.min}
                    max={control.range.max}
                    step={control.range.step}
                    format={
                      control.range.scale === 100
                        ? (value) => `${Math.round(value)}%`
                        : undefined
                    }
                    value={Number(control.encode(lab.settings))}
                    onValueChange={(value) =>
                      lab.change(control.decode(String(value)))
                    }
                  />
                ),
              )}
            </div>
          </details>
        ),
      )}
    </>
  );

  const helpContent = lab.showHelp && (
    <div {...stylex.props(s.help)}>
      <p>
        <code>lab=1:{canvasLabHelp()}</code>
      </p>
      {help}
    </div>
  );

  return (
    <aside
      id={id}
      aria-label="Canvas lab"
      data-cell-canvas-chrome="true"
      data-canvas-lab-panel="true"
      {...stylex.props(s.panel, xstyle)}
      onPointerDown={(event) => event.stopPropagation()}
      onWheel={(event) => event.stopPropagation()}
      onKeyDown={(event) => {
        if (close && event.key === "Escape") {
          event.stopPropagation();
          close();
        }
      }}
    >
      {tabs ? (
        <Tabs.Root
          value={tabs.value}
          onValueChange={(value) => {
            if (value === "canvas" || value === "nodes") tabs.onChange(value);
          }}
          {...stylex.props(s.tabsRoot)}
        >
          <Tabs.List
            aria-label="Canvas lab settings"
            {...stylex.props(s.tabList)}
          >
            <Tabs.Tab value="canvas" {...stylex.props(s.tab)}>
              Canvas
            </Tabs.Tab>
            <Tabs.Tab value="nodes" {...stylex.props(s.tab)}>
              Nodes
            </Tabs.Tab>
          </Tabs.List>
          <div {...stylex.props(s.body)}>
            <Tabs.Panel value="canvas" {...stylex.props(s.group)}>
              {canvasContent}
            </Tabs.Panel>
            <Tabs.Panel value="nodes" {...stylex.props(s.group)}>
              {tabs.nodes}
            </Tabs.Panel>
            {helpContent}
          </div>
        </Tabs.Root>
      ) : (
        <div {...stylex.props(s.body)}>
          {canvasContent}
          {helpContent}
        </div>
      )}
      <div {...stylex.props(s.footer)}>
        <div {...stylex.props(s.actions)}>
          <Button
            size="xs"
            variant="secondary"
            xstyle={s.mobileControl}
            onClick={reset ?? lab.reset}
          >
            Reset
          </Button>
          <Button
            size="xs"
            variant="secondary"
            xstyle={s.mobileControl}
            onClick={copyLink}
          >
            Copy link
          </Button>
          {close && (
            <Button
              size="xs"
              variant="secondary"
              xstyle={s.mobileControl}
              onClick={close}
            >
              Close
            </Button>
          )}
        </div>
        {copyStatus && (
          <p role="status" {...stylex.props(s.help)}>
            {copyStatus}
          </p>
        )}
      </div>
    </aside>
  );
}
