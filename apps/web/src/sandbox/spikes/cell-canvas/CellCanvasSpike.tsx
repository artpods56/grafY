"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { Button } from "@/components/ui/button";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useMediaQuery } from "@/hooks/use-media-query";
import { tokens } from "@/lib/stylex/tokens.stylex";
import {
  CellCanvas,
  cellGraphBounds,
  type CellCanvasHandle,
} from "@/features/workbench/cell-canvas/CellCanvas";
import {
  CanvasLabPanel,
  CanvasLabRow,
} from "@/features/workbench/cell-canvas/CanvasLabPanel";
import {
  CanvasLabProvider,
  replaceLabQuery,
  useCanvasLab,
} from "@/features/workbench/cell-canvas/CanvasLabProvider";
import { cellGraphFromAuthoredDocument } from "@/features/workbench/cell-canvas/cell-document-adapter";
import { cellPortKey } from "@/features/workbench/cell-canvas/cell-model";

import {
  ASK_A_MODEL_CARD_ID,
  ASK_A_MODEL_FIXTURE,
} from "../../fixtures/graphs/ask-a-model";
import {
  canvasNodesDocument,
  nodeFixtureRegistry,
  readNodeIds,
} from "../../fixtures/graphs/canvas-nodes";
import { inspectCards } from "./canvas-inspection";
import { cardPortAddress, NodeLabControls } from "./NodeLabControls";

const NARROW = "(max-width: 620px)";
const PANEL_ID = "canvas-lab-panel";

/*
 * The canvas is the page: it fills the viewport and the scene fits its whole
 * box, so the lab panel floats over it instead of taking a column. On a narrow
 * screen the panel starts closed behind a labelled button and opens over the
 * canvas, never in a row of its own.
 */
const s = stylex.create({
  page: {
    position: "relative",
    height: "100svh",
    overflow: "hidden",
    backgroundColor: tokens.colorBg,
    color: tokens.colorText,
  },
  stage: { position: "absolute", inset: 0 },
  panel: {
    position: "absolute",
    zIndex: 10,
    top: "calc(12px + env(safe-area-inset-top, 0px))",
    left: "calc(12px + env(safe-area-inset-left, 0px))",
    width: {
      default: "252px",
      "@media (max-width: 620px)":
        "calc(100% - 24px - env(safe-area-inset-left, 0px) - env(safe-area-inset-right, 0px))",
    },
    maxWidth: { default: null, "@media (max-width: 620px)": "360px" },
    maxHeight:
      "calc(100% - 24px - env(safe-area-inset-top, 0px) - env(safe-area-inset-bottom, 0px))",
    display: { default: "flex", "@media (max-width: 620px)": "none" },
  },
  panelOpen: { display: "flex" },
  toggle: {
    position: "absolute",
    zIndex: 10,
    top: "calc(12px + env(safe-area-inset-top, 0px))",
    left: "calc(12px + env(safe-area-inset-left, 0px))",
    display: { default: "none", "@media (max-width: 620px)": "inline-flex" },
    minHeight: "44px",
    paddingInline: "14px",
    border: `1px solid ${tokens.colorBorder}`,
    borderRadius: "12px",
    backgroundColor: tokens.colorChrome,
    boxShadow: "0 4px 16px rgba(0, 0, 0, 0.16)",
  },
  toggleHidden: { display: "none" },
  stageNote: {
    position: "absolute",
    right: "calc(12px + env(safe-area-inset-right, 0px))",
    bottom: "calc(12px + env(safe-area-inset-bottom, 0px))",
    pointerEvents: "none",
    margin: 0,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
  },
  notice: {
    position: "absolute",
    inset: 0,
    display: "grid",
    placeItems: "center",
    margin: 0,
    padding: "16px",
    color: tokens.colorMuted,
    pointerEvents: "none",
  },
  noticeLink: { pointerEvents: "auto" },
});

function setOption(key: string, value: string | null) {
  replaceLabQuery((query) => {
    if (value === null) query.delete(key);
    else query.set(key, value);
  });
}

function CardLab() {
  const params = useSearchParams();
  const { settings, routing } = useCanvasLab();
  const fixture = params.get("fixture") ?? ASK_A_MODEL_FIXTURE;
  const available = fixture === ASK_A_MODEL_FIXTURE;
  const nodeQuery = params.get("nodes");
  const scene = React.useMemo(
    () =>
      cellGraphFromAuthoredDocument(
        canvasNodesDocument(readNodeIds(nodeQuery)),
        nodeFixtureRegistry,
      ),
    [nodeQuery],
  );
  const bounds = React.useMemo(
    () => cellGraphBounds(scene.graph.cards),
    [scene],
  );
  const selection = params.get("sel");
  const selectedId = scene.graph.cards.some((card) => card.id === selection)
    ? selection
    : null;
  const selectedIds = React.useMemo(
    () => new Set(selectedId ? [selectedId] : []),
    [selectedId],
  );
  const hotAddress = params.get("hot") ?? params.get("hover");
  const previewPortKey = scene.graph.cards.flatMap((card) =>
    card.ports
      .filter((port) => cardPortAddress(card.id, port) === hotAddress)
      .map((port) => `${card.id}:${cellPortKey(port.direction, port.id)}`),
  )[0];
  const tab = params.get("tab") === "nodes" ? "nodes" : "canvas";
  const requestedZoom = Number(params.get("zoom"));
  const zoom =
    Number.isFinite(requestedZoom) &&
    requestedZoom >= 0.15 &&
    requestedZoom <= 2
      ? requestedZoom
      : null;
  const freeze = params.get("freeze") === "1";
  const inspect = params.get("inspect") === "1";
  const theme = params.get("theme");
  const colorScheme = theme === "light" || theme === "dark" ? theme : undefined;

  const narrow = useMediaQuery(NARROW);
  const [panelOpen, setPanelOpen] = React.useState(false);
  const toggle = React.useRef<HTMLButtonElement>(null);
  const panelVisible = !narrow || panelOpen;

  // Opening on a narrow screen moves focus into the panel; closing hands it back.
  const openPanel = () => {
    setPanelOpen(true);
    requestAnimationFrame(() =>
      document
        .getElementById(PANEL_ID)
        ?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')
        ?.focus(),
    );
  };
  const closePanel = () => {
    setPanelOpen(false);
    requestAnimationFrame(() => toggle.current?.focus());
  };

  const stage = React.useRef<HTMLDivElement>(null);
  const [canvas, setCanvas] = React.useState<CellCanvasHandle | null>(null);
  const [actualZoom, setActualZoom] = React.useState(1);

  React.useLayoutEffect(() => {
    const element = stage.current;
    if (!canvas || !element || scene.graph.cards.length === 0) return;
    const fit = () => {
      if (zoom === null) canvas.viewportHandle.fitBounds(bounds, 0.18, 1);
      else
        canvas.viewAt(
          bounds.x + bounds.width / 2,
          bounds.y + bounds.height / 2,
          zoom,
        );
    };
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(element);
    return () => observer.disconnect();
  }, [bounds, canvas, scene.graph.cards.length, zoom]);

  React.useEffect(() => {
    const element = stage.current;
    if (!inspect || !available || !element || !canvas) return;
    const {
      exits: _exits,
      underCards: _underCards,
      depth: _depth,
      ...look
    } = settings;
    const inspection = {
      look,
      routing,
      get cards() {
        return inspectCards(element);
      },
    };
    window.__grafy = inspection;
    console.table(
      inspection.cards.map(({ id, rect, ports, tabs }) => ({
        id,
        width: rect.width,
        height: rect.height,
        ports: ports.length,
        tabs: tabs.length,
      })),
    );
    return () => {
      if (window.__grafy === inspection) delete window.__grafy;
    };
  }, [
    available,
    canvas,
    inspect,
    settings,
    routing,
    scene,
    selectedId,
    previewPortKey,
    zoom,
  ]);

  return (
    <div {...stylex.props(s.page)} style={{ colorScheme }}>
      <Button
        ref={toggle}
        variant="secondary"
        size="sm"
        aria-expanded={panelVisible}
        aria-controls={PANEL_ID}
        xstyle={[s.toggle, panelVisible && s.toggleHidden]}
        onClick={openPanel}
      >
        Lab settings
      </Button>
      <CanvasLabPanel
        id={PANEL_ID}
        xstyle={[s.panel, panelOpen && s.panelOpen]}
        close={narrow ? closePanel : undefined}
        reset={() =>
          replaceLabQuery((query) => {
            for (const key of [
              "lab",
              "fixture",
              "nodes",
              "tab",
              "sel",
              "hover",
              "hot",
              "zoom",
              "freeze",
              "inspect",
              "theme",
            ]) {
              query.delete(key);
            }
          })
        }
        help={
          <p>
            <code>
              fixture={ASK_A_MODEL_FIXTURE} ·
              nodes=ask-model,schema-builder,text-input · tab=nodes · sel=
              {ASK_A_MODEL_CARD_ID} · hot=port:ask-model/input:messages ·
              zoom=0.15–2 · freeze=1 · inspect=1 · theme=light|dark
            </code>
          </p>
        }
        tabs={{
          value: tab,
          onChange: (value) =>
            setOption("tab", value === "nodes" ? value : null),
          nodes: (
            <NodeLabControls
              cards={scene.graph.cards}
              selectedId={selectedId}
              hotAddress={hotAddress}
            />
          ),
        }}
        canvasControls={
          <>
            <CanvasLabRow label="Theme">
              <SegmentedControl
                aria-label="Theme"
                value={colorScheme ?? "app"}
                options={[
                  { value: "app", label: "App" },
                  { value: "light", label: "Light" },
                  { value: "dark", label: "Dark" },
                ]}
                onValueChange={(value) =>
                  setOption("theme", value === "app" ? null : value)
                }
              />
            </CanvasLabRow>
            <CanvasLabRow label="Zoom">
              <Select
                aria-label="Zoom"
                size="sm"
                value={zoom ?? ""}
                onChange={(event) =>
                  setOption("zoom", event.currentTarget.value || null)
                }
              >
                <option value="">Fit</option>
                {[
                  ...new Set([
                    0.5,
                    0.75,
                    1,
                    1.5,
                    2,
                    ...(zoom === null ? [] : [zoom]),
                  ]),
                ]
                  .sort((a, b) => a - b)
                  .map((value) => (
                    <option key={value} value={value}>
                      {Math.round(value * 100)}%
                    </option>
                  ))}
              </Select>
            </CanvasLabRow>
            <Switch
              label="Freeze motion"
              checked={freeze}
              phoneTouch
              onCheckedChange={(on) => setOption("freeze", on ? "1" : null)}
            />
            <Switch
              label="Inspect geometry"
              checked={inspect}
              phoneTouch
              onCheckedChange={(on) => setOption("inspect", on ? "1" : null)}
            />
          </>
        }
      />
      <div
        ref={stage}
        {...stylex.props(s.stage)}
        data-canvas-lab-frozen={freeze ? "true" : undefined}
      >
        {available ? (
          <>
            <CellCanvas
              {...scene}
              look={settings}
              routing={routing}
              editable={false}
              autoFitOnMount={false}
              selectedCardIds={selectedIds}
              onSelectionChange={(selection) =>
                setOption("sel", [...selection.cardIds].at(-1) ?? null)
              }
              previewPortKey={previewPortKey}
              onHandleReady={setCanvas}
              onViewportZoomChange={setActualZoom}
            />
            {scene.graph.cards.length === 0 && (
              <p {...stylex.props(s.notice)}>Choose a node in the Nodes tab.</p>
            )}
            <p {...stylex.props(s.stageNote)}>
              {scene.graph.cards.length}{" "}
              {scene.graph.cards.length === 1 ? "card" : "cards"} ·{" "}
              {scene.graph.pipes.length}{" "}
              {scene.graph.pipes.length === 1 ? "pipe" : "pipes"} ·{" "}
              {Math.round(actualZoom * 100)}%
            </p>
          </>
        ) : (
          <p {...stylex.props(s.notice)}>
            <span>
              Unknown fixture.{" "}
              <Link href="/sandbox/cell-canvas" {...stylex.props(s.noticeLink)}>
                Load Ask a model
              </Link>
            </span>
          </p>
        )}
      </div>
    </div>
  );
}

export function CellCanvasSpike() {
  return (
    <React.Suspense fallback={null}>
      <CanvasLabProvider sandbox>
        <CardLab />
      </CanvasLabProvider>
    </React.Suspense>
  );
}
