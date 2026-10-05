"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Drawer } from "@base-ui/react/drawer";
import { PanelLeftClose } from "lucide-react";

import { tokens } from "@/lib/stylex/tokens.stylex";
import {
  beginSidePanelResize,
  clampSidePanelWidth,
  endSidePanelResize,
  previewSidePanelWidth,
  SIDE_PANEL_DEFAULT_WIDTH,
  SIDE_PANEL_ELEMENT_ID,
  SIDE_PANEL_MOTION_MS,
  type WorkbenchSidePanelState,
} from "./workbench-side-panel-state";
import { LibraryPanel } from "./LibraryPanel";
import { panelStyles } from "./panel-styles";
import { GeneratedDrawer } from "../GeneratedDrawer";
import type { NodeRegistry } from "@/lib/api";

const RESIZE_STEP = 16;

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
    // Parked behind the rail (which paints above it) until it slides out, and
    // hidden once it is back there. Its left edge follows the rail when the
    // rail folds, on the rail's own clock.
    transform: "translateX(-100%)",
    visibility: "hidden",
    transitionProperty: "transform, visibility, inset-inline-start",
    transitionDuration:
      "var(--grafy-side-panel-duration, 0ms), var(--grafy-side-panel-duration, 0ms), 180ms",
    transitionTimingFunction:
      "var(--grafy-side-panel-ease, ease), linear, ease",
  },
  dockOpen: { transform: "none", visibility: "visible" },
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
    opacity: {
      default: 1,
      ":is([data-starting-style], [data-ending-style])": 0,
    },
    transitionProperty: "opacity",
    transitionDuration: "var(--grafy-side-panel-duration, 0ms)",
    transitionTimingFunction: "ease",
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
    boxShadow: tokens.shadowNode,
    // It follows the finger while swiped and eases in and out otherwise.
    transform: {
      default: "translateX(var(--drawer-swipe-movement-x, 0px))",
      ":is([data-starting-style], [data-ending-style])": "translateX(-100%)",
    },
    transitionProperty: "transform",
    transitionDuration: {
      default: "var(--grafy-side-panel-duration, 0ms)",
      ":is([data-swiping])": "0ms",
    },
    transitionTimingFunction: "var(--grafy-side-panel-ease, ease)",
  },
});

/**
 * The second pane of the sidebar: docked beside the canvas on a wide viewport,
 * a slide-over drawer on a narrow one. It hosts the Workspace Library, or this
 * canvas's Generated Run artifacts, whichever the rail last asked for. Either
 * way it slides in from behind the rail and back out, rather than blinking.
 */
export function WorkbenchSidePanel({
  workspaceId,
  sidePanel,
  onOpenRun,
  graphId,
  nodeTitles,
  registry,
  canSave,
  executionRunning,
}: {
  workspaceId: string;
  sidePanel: WorkbenchSidePanelState;
  onOpenRun: (graphId: string, executionId: string) => void;
  graphId: string | null;
  nodeTitles: Readonly<Record<string, string>>;
  registry: NodeRegistry | null;
  canSave: boolean;
  executionRunning: boolean;
}) {
  const collapse = (
    <button
      type="button"
      aria-label="Collapse side panel"
      title="Collapse side panel"
      onClick={() => sidePanel.setOpen(false)}
      {...stylex.props(panelStyles.iconButton)}
    >
      <PanelLeftClose size={14} />
    </button>
  );
  const body =
    sidePanel.view === "generated" ? (
      <GeneratedDrawer
        workspaceId={workspaceId}
        graphId={graphId}
        nodeTitles={nodeTitles}
        registry={registry}
        canSave={canSave}
        executionRunning={executionRunning}
        headerEnd={collapse}
      />
    ) : (
      <LibraryPanel
        workspaceId={workspaceId}
        onOpenRun={onOpenRun}
        headerEnd={collapse}
      />
    );

  if (!sidePanel.docked) {
    // Base UI keeps the popup mounted through its exit transition.
    return (
      <Drawer.Root
        open={sidePanel.open}
        modal
        swipeDirection="left"
        onOpenChange={(next) => sidePanel.setOpen(next)}
      >
        <Drawer.Portal>
          <Drawer.Viewport {...stylex.props(s.drawerViewport)}>
            <Drawer.Backdrop {...stylex.props(s.drawerBackdrop)} />
            <Drawer.Popup
              id={SIDE_PANEL_ELEMENT_ID}
              aria-label="Workbench side panel"
              {...stylex.props(s.drawerPopup)}
            >
              {body}
            </Drawer.Popup>
          </Drawer.Viewport>
        </Drawer.Portal>
      </Drawer.Root>
    );
  }

  return (
    <DockedSidePanel open={sidePanel.open}>
      {body}
      <SidePanelResizer
        width={sidePanel.width}
        onPreview={previewSidePanelWidth}
        onCommit={sidePanel.setWidth}
      />
    </DockedSidePanel>
  );
}

/**
 * True while `open`, and for as long as the closing motion runs after it — the
 * time the panel's contents stay mounted so they slide out rather than vanish.
 */
function useStaysForExit(open: boolean): boolean {
  const [exiting, setExiting] = React.useState(false);
  const [wasOpen, setWasOpen] = React.useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    setExiting(!open);
  }

  React.useEffect(() => {
    if (!exiting) return;
    const timer = window.setTimeout(
      () => setExiting(false),
      SIDE_PANEL_MOTION_MS,
    );
    return () => window.clearTimeout(timer);
  }, [exiting]);

  return open || exiting;
}

/**
 * The docked column. Its box is always there, parked behind the rail while
 * closed, so opening moves it in the same frame the canvas edge moves; only
 * its contents mount and unmount. Closed, it is hidden and inert.
 */
function DockedSidePanel({
  open,
  children,
}: {
  open: boolean;
  children: React.ReactNode;
}) {
  const hasContents = useStaysForExit(open);
  const panelRef = React.useRef<HTMLElement>(null);

  // Closing from inside the panel hands focus to the rail's toggle rather than
  // dropping it on the document.
  React.useEffect(() => {
    if (open) return;
    if (!panelRef.current?.contains(document.activeElement)) return;
    document.querySelector<HTMLElement>("[data-side-panel-toggle]")?.focus();
  }, [open]);

  return (
    <aside
      ref={panelRef}
      id={SIDE_PANEL_ELEMENT_ID}
      aria-label="Workbench side panel"
      inert={!open}
      data-state={open ? "open" : "closed"}
      {...stylex.props(s.dock, open ? s.dockOpen : null)}
    >
      {hasContents ? children : null}
    </aside>
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
  const dragRef = React.useRef<{
    pointerId: number;
    startX: number;
    startWidth: number;
  } | null>(null);

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
        onPreview(
          clampSidePanelWidth(drag.startWidth + (event.clientX - drag.startX)),
        );
      }}
      onPointerUp={(event) => {
        const drag = dragRef.current;
        if (!drag || drag.pointerId !== event.pointerId) return;
        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
          event.currentTarget.releasePointerCapture(event.pointerId);
        }
        dragRef.current = null;
        endSidePanelResize();
        onCommit(
          clampSidePanelWidth(drag.startWidth + (event.clientX - drag.startX)),
        );
      }}
      onPointerCancel={(event) => {
        const drag = dragRef.current;
        if (!drag || drag.pointerId !== event.pointerId) return;
        dragRef.current = null;
        endSidePanelResize();
        // The drag never finished: put the edge back where it was.
        onPreview(drag.startWidth);
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
