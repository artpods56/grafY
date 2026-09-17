"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Drawer } from "@base-ui/react/drawer";
import {
  FolderTree,
  Layers,
  LayoutTemplate,
  PanelLeftClose,
  type LucideIcon,
} from "lucide-react";

import { tokens } from "@/lib/stylex/tokens.stylex";
import {
  beginSidePanelResize,
  clampSidePanelWidth,
  endSidePanelResize,
  previewSidePanelWidth,
  SIDE_PANEL_DEFAULT_WIDTH,
  type SidePanelViewId,
  type WorkbenchSidePanelState,
} from "./workbench-side-panel-state";
import { LibraryPanel } from "./LibraryPanel";
import { TemplatesPanel } from "./TemplatesPanel";

const PANEL_BODY_ID = "grafy-side-panel-view";
const RESIZE_STEP = 16;

type PanelContext = {
  workspaceId: string;
  onOpenRun: (graphId: string, executionId: string) => void;
  onOpenGraph: (graphId: string) => void;
  /**
   * The Runs drawer, composed by the workbench because it needs the live canvas
   * — graph id, node titles, registry, edit rights. The panel only decides when
   * to show it, so the canvas types stay out of the panel's own vocabulary.
   */
  generatedView: React.ReactNode;
};

/**
 * The views the panel can host. This array is the whole extension surface: one
 * entry plus one component adds a tab. It is deliberately not a registry — see
 * `docs/design/workbench-side-panel.md`.
 */
const PANEL_VIEWS: readonly {
  id: SidePanelViewId;
  label: string;
  icon: LucideIcon;
  render: (context: PanelContext) => React.ReactNode;
}[] = [
  {
    id: "artifacts",
    label: "Artifacts",
    icon: FolderTree,
    render: (context) => (
      <LibraryPanel
        workspaceId={context.workspaceId}
        onOpenRun={context.onOpenRun}
      />
    ),
  },
  {
    id: "templates",
    label: "Templates",
    icon: LayoutTemplate,
    render: (context) => (
      <TemplatesPanel
        workspaceId={context.workspaceId}
        onOpenGraph={context.onOpenGraph}
      />
    ),
  },
  {
    id: "generated",
    label: "Generated",
    icon: Layers,
    render: (context) => context.generatedView,
  },
];

const s = stylex.create({
  /* The second pane of the sidebar: same surface and hairline as the rail, and
   * deliberately no shadow, because a docked pane never floats. */
  dock: {
    position: "fixed",
    zIndex: 45,
    insetBlock: 0,
    insetInlineStart: "var(--grafy-rail-width, 0px)",
    width: "var(--grafy-side-panel-expanded-width, 276px)",
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
    backgroundColor: tokens.colorBg,
    borderInlineEndWidth: 1,
    borderInlineEndStyle: "solid",
    borderInlineEndColor: tokens.colorDivider,
    color: tokens.colorText,
  },
  header: {
    flexShrink: 0,
    height: "52px",
    display: "flex",
    alignItems: "center",
    gap: "6px",
    padding: "0 6px 0 8px",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
  },
  tablist: {
    minWidth: 0,
    flex: 1,
    display: "flex",
    alignItems: "center",
    gap: "2px",
  },
  tab: {
    height: "26px",
    display: "inline-flex",
    alignItems: "center",
    gap: "5px",
    paddingInline: "8px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: "transparent",
    borderRadius: "6px",
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorSurfaceSunken,
    },
    color: { default: tokens.colorMuted, ":hover": tokens.colorText },
    cursor: "pointer",
    fontSize: tokens.fontSizeSm,
    fontWeight: 560,
    whiteSpace: "nowrap",
  },
  tabActive: {
    backgroundColor: {
      default: tokens.colorSurfaceRaised,
      ":hover": tokens.colorSurfaceRaised,
    },
    borderColor: {
      default: tokens.colorBorder,
      ":hover": tokens.colorBorder,
    },
    color: {
      default: tokens.colorTextEmphasis,
      ":hover": tokens.colorTextEmphasis,
    },
  },
  closeButton: {
    width: "26px",
    height: "26px",
    display: "grid",
    placeItems: "center",
    flexShrink: 0,
    borderWidth: 0,
    borderStyle: "none",
    borderRadius: "6px",
    backgroundColor: { default: "transparent", ":hover": tokens.colorSurfaceSunken },
    color: { default: tokens.colorMuted, ":hover": tokens.colorText },
    cursor: "pointer",
  },
  body: {
    minHeight: 0,
    flex: 1,
    display: "flex",
    flexDirection: "column",
  },
  resizer: {
    position: "absolute",
    insetBlock: 0,
    insetInlineEnd: "-3px",
    width: "7px",
    borderStyle: "none",
    backgroundColor: "transparent",
    cursor: "col-resize",
    outlineWidth: 0,
    touchAction: "none",
    ":hover": { backgroundColor: tokens.colorAccentSoft },
    ":focus-visible": { backgroundColor: tokens.colorAccentSoft },
  },
  drawerViewport: {
    position: "fixed",
    inset: 0,
    zIndex: 90,
  },
  drawerBackdrop: {
    position: "fixed",
    inset: 0,
    backgroundColor: "light-dark(rgba(17, 17, 17, 0.32), rgba(0, 0, 0, 0.55))",
  },
  drawerPopup: {
    position: "absolute",
    insetBlock: 0,
    insetInlineStart: 0,
    width: "min(320px, calc(100vw - 56px))",
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
    backgroundColor: tokens.colorBg,
    borderInlineEndWidth: 1,
    borderInlineEndStyle: "solid",
    borderInlineEndColor: tokens.colorDivider,
    color: tokens.colorText,
    transform: "translateX(var(--drawer-swipe-movement-x, 0px))",
  },
});

export function WorkbenchSidePanel({
  workspaceId,
  sidePanel,
  generatedView,
  onOpenRun,
  onOpenGraph,
}: {
  workspaceId: string;
  sidePanel: WorkbenchSidePanelState;
  generatedView?: React.ReactNode;
  onOpenRun: (graphId: string, executionId: string) => void;
  onOpenGraph: (graphId: string) => void;
}) {
  if (!sidePanel.open) return null;

  const body = (
    <SidePanelBody
      workspaceId={workspaceId}
      generatedView={generatedView}
      view={sidePanel.view}
      onViewChange={sidePanel.setView}
      onClose={() => sidePanel.setOpen(false)}
      onOpenRun={onOpenRun}
      onOpenGraph={onOpenGraph}
    />
  );

  if (!sidePanel.docked) {
    return (
      <Drawer.Root
        open
        modal
        swipeDirection="left"
        onOpenChange={(next) => sidePanel.setOpen(next)}
      >
        <Drawer.Portal>
          <Drawer.Viewport {...stylex.props(s.drawerViewport)}>
            <Drawer.Backdrop {...stylex.props(s.drawerBackdrop)} />
            <Drawer.Popup {...stylex.props(s.drawerPopup)}>{body}</Drawer.Popup>
          </Drawer.Viewport>
        </Drawer.Portal>
      </Drawer.Root>
    );
  }

  return (
    <aside aria-label="Workbench side panel" {...stylex.props(s.dock)}>
      {body}
      <SidePanelResizer
        width={sidePanel.width}
        onPreview={previewSidePanelWidth}
        onCommit={sidePanel.setWidth}
      />
    </aside>
  );
}

function SidePanelBody({
  workspaceId,
  generatedView,
  view,
  onViewChange,
  onClose,
  onOpenRun,
  onOpenGraph,
}: {
  workspaceId: string;
  generatedView: React.ReactNode;
  view: SidePanelViewId;
  onViewChange: (next: SidePanelViewId) => void;
  onClose: () => void;
  onOpenRun: (graphId: string, executionId: string) => void;
  onOpenGraph: (graphId: string) => void;
}) {
  const active = PANEL_VIEWS.find((entry) => entry.id === view) ?? PANEL_VIEWS[0]!;
  const context: PanelContext = {
    workspaceId,
    onOpenRun,
    onOpenGraph,
    generatedView,
  };

  function onTabKeyDown(event: React.KeyboardEvent<HTMLButtonElement>): void {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    event.preventDefault();
    const index = PANEL_VIEWS.findIndex((entry) => entry.id === active.id);
    const step = event.key === "ArrowRight" ? 1 : -1;
    const next =
      PANEL_VIEWS[(index + step + PANEL_VIEWS.length) % PANEL_VIEWS.length]!;
    onViewChange(next.id);
    document.getElementById(`grafy-side-panel-tab-${next.id}`)?.focus();
  }

  return (
    <>
      <header {...stylex.props(s.header)}>
        <div role="tablist" aria-label="Workbench panels" {...stylex.props(s.tablist)}>
          {PANEL_VIEWS.map((entry) => {
            const selected = entry.id === active.id;
            return (
              <button
                key={entry.id}
                type="button"
                role="tab"
                id={`grafy-side-panel-tab-${entry.id}`}
                aria-selected={selected}
                aria-controls={PANEL_BODY_ID}
                tabIndex={selected ? 0 : -1}
                title={entry.label}
                onKeyDown={onTabKeyDown}
                onClick={() => onViewChange(entry.id)}
                {...stylex.props(s.tab, selected ? s.tabActive : null)}
              >
                <entry.icon size={12} aria-hidden="true" />
                {entry.label}
              </button>
            );
          })}
        </div>
        <button
          type="button"
          aria-label="Collapse side panel"
          title="Collapse side panel"
          {...stylex.props(s.closeButton)}
          onClick={onClose}
        >
          <PanelLeftClose size={14} />
        </button>
      </header>
      <div
        id={PANEL_BODY_ID}
        role="tabpanel"
        aria-labelledby={`grafy-side-panel-tab-${active.id}`}
        tabIndex={-1}
        {...stylex.props(s.body)}
      >
        {active.render(context)}
      </div>
    </>
  );
}

function SidePanelResizer({
  width,
  onPreview,
  onCommit,
}: {
  width: number;
  onPreview: (width: number) => void;
  onCommit: (width: number) => void;
}) {
  const dragRef = React.useRef<{ pointerId: number; startX: number; startWidth: number } | null>(
    null,
  );

  React.useEffect(() => endSidePanelResize, []);

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize side panel"
      aria-valuenow={width}
      tabIndex={0}
      {...stylex.props(s.resizer)}
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        event.preventDefault();
        dragRef.current = {
          pointerId: event.pointerId,
          startX: event.clientX,
          startWidth: width,
        };
        event.currentTarget.setPointerCapture(event.pointerId);
        beginSidePanelResize();
      }}
      onPointerMove={(event) => {
        const drag = dragRef.current;
        if (!drag || drag.pointerId !== event.pointerId) return;
        onPreview(clampSidePanelWidth(drag.startWidth + (event.clientX - drag.startX)));
      }}
      onPointerUp={(event) => {
        const drag = dragRef.current;
        if (!drag || drag.pointerId !== event.pointerId) return;
        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
          event.currentTarget.releasePointerCapture(event.pointerId);
        }
        dragRef.current = null;
        endSidePanelResize();
        onCommit(clampSidePanelWidth(drag.startWidth + (event.clientX - drag.startX)));
      }}
      onKeyDown={(event) => {
        if (event.key === "ArrowLeft") {
          event.preventDefault();
          onCommit(clampSidePanelWidth(width - RESIZE_STEP));
        } else if (event.key === "ArrowRight") {
          event.preventDefault();
          onCommit(clampSidePanelWidth(width + RESIZE_STEP));
        } else if (event.key === "Home") {
          event.preventDefault();
          onCommit(SIDE_PANEL_DEFAULT_WIDTH);
        }
      }}
    />
  );
}
