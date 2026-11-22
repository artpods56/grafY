"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { X } from "lucide-react";

import { Button, IconButton } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";
import { Surface } from "@/components/ui/surface";
import { Switch } from "@/components/ui/switch";
import type { RunEdgeCollectionMode } from "@/lib/api";
import { overlay } from "@/lib/stylex/overlay.stylex";
import { tokens } from "@/lib/stylex/tokens.stylex";

import type { ArtifactOriginEdge } from "../artifacts/artifact-origin-edge";
import type {
  ArtifactViewerEdge,
  ArtifactViewerEdgeUpdate,
} from "../artifacts/artifact-viewer";
import type { WorkflowEdge, WorkflowEdgeUpdate } from "../authoring/types";
import { useCellViewportApi } from "./CellCanvasContext";
import type { WorldPoint } from "./cell-model";
import {
  conversionPathsEqual,
  feedChoicesFromRouteOptions,
  projectionsEqual,
} from "../authoring/connection-feeds";

const POPOVER_WIDTH = 264;
const VIEWPORT_MARGIN = 12;
const VERTICAL_OFFSET = 16;
const ESTIMATED_HEIGHT = 240;

const s = stylex.create({
  wrapper: {
    position: "fixed",
    // Keep in sync with POPOVER_WIDTH.
    width: "264px",
    zIndex: 60,
    pointerEvents: "auto",
  },
  surface: {
    display: "flex",
    flexDirection: "column",
    gap: "10px",
    padding: "10px",
    overflowY: "auto",
    maxHeight: "inherit",
  },
  header: {
    display: "flex",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: "8px",
  },
  headerTitles: {
    minWidth: 0,
    display: "flex",
    flexDirection: "column",
    gap: "2px",
  },
  title: {
    fontSize: tokens.fontSizeSm,
    fontWeight: 600,
    color: tokens.colorTextEmphasis,
    lineHeight: 1.25,
  },
  subtitle: {
    fontSize: tokens.fontSizeXs,
    color: tokens.colorMuted,
    lineHeight: 1.25,
    overflowWrap: "anywhere",
  },
  section: {
    display: "flex",
    flexDirection: "column",
    gap: "6px",
  },
  sectionLabel: {
    fontSize: tokens.fontSizeXs,
    fontWeight: 600,
    color: tokens.colorMuted,
  },
  modeRow: {
    display: "flex",
    gap: "4px",
  },
  modeButton: {
    flex: 1,
  },
  choiceList: {
    display: "flex",
    flexDirection: "column",
    gap: "3px",
  },
  choiceButton: {
    height: "auto",
    paddingBlock: "5px",
    paddingInline: "8px",
    flexDirection: "column",
    alignItems: "flex-start",
    justifyContent: "flex-start",
    gap: "2px",
    textAlign: "left",
    whiteSpace: "normal",
    fontWeight: 500,
  },
  choiceTitle: {
    fontSize: tokens.fontSizeXs,
    fontWeight: 600,
    color: "inherit",
    lineHeight: 1.3,
  },
  choiceDescription: {
    fontSize: tokens.fontSizeXs,
    color: tokens.colorMuted,
    lineHeight: 1.3,
    overflowWrap: "anywhere",
  },
  footer: {
    display: "flex",
    justifyContent: "flex-end",
    paddingTop: "4px",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
  },
});

export type CellInspectedPipe =
  | { kind: "workflow"; edge: WorkflowEdge }
  | { kind: "origin"; edge: ArtifactOriginEdge }
  | { kind: "viewer"; edge: ArtifactViewerEdge };

export interface CellPipeInspectorProps {
  pipe: CellInspectedPipe;
  anchor: WorldPoint;
  editable: boolean;
  onClose: () => void;
  onUpdateWorkflowEdge: (edgeId: string, update: WorkflowEdgeUpdate) => void;
  onUpdateOriginCollectionMode: (
    originId: string,
    collectionMode: RunEdgeCollectionMode,
  ) => void;
  onUpdateViewerEdge: (
    edgeId: string,
    update: ArtifactViewerEdgeUpdate,
  ) => void;
  onRemovePipe: (pipeId: string) => void;
}

function inspectorTitle(pipe: CellInspectedPipe): string {
  switch (pipe.kind) {
    case "workflow":
      return "Connection";
    case "origin":
      return "Artifact connection";
    case "viewer":
      return "Viewer feed";
  }
}

function inspectorSubtitle(pipe: CellInspectedPipe): string | null {
  switch (pipe.kind) {
    case "workflow":
      return pipe.edge.data?.sourcePortName
        ? `From ${pipe.edge.data.sourcePortName}`
        : null;
    case "viewer":
      return pipe.edge.data?.sourcePortName
        ? `From ${pipe.edge.data.sourcePortName}`
        : null;
    case "origin":
      return null;
  }
}

export function CellPipeInspector({
  pipe,
  anchor,
  editable,
  onClose,
  onUpdateWorkflowEdge,
  onUpdateOriginCollectionMode,
  onUpdateViewerEdge,
  onRemovePipe,
}: CellPipeInspectorProps) {
  const viewportApi = useCellViewportApi();

  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const screen = viewportApi ? viewportApi.worldToScreen(anchor) : anchor;
  const viewportWidth =
    typeof window !== "undefined" ? window.innerWidth : 1280;
  const viewportHeight =
    typeof window !== "undefined" ? window.innerHeight : 800;

  const left = Math.max(
    VIEWPORT_MARGIN,
    Math.min(
      screen.x - POPOVER_WIDTH / 2,
      Math.max(
        VIEWPORT_MARGIN,
        viewportWidth - POPOVER_WIDTH - VIEWPORT_MARGIN,
      ),
    ),
  );
  const preferBelow =
    screen.y + VERTICAL_OFFSET + ESTIMATED_HEIGHT <=
    viewportHeight - VIEWPORT_MARGIN;
  const rawTop = preferBelow
    ? screen.y + VERTICAL_OFFSET
    : screen.y - VERTICAL_OFFSET - ESTIMATED_HEIGHT;
  const maxTop = Math.max(
    VIEWPORT_MARGIN,
    viewportHeight - ESTIMATED_HEIGHT - VIEWPORT_MARGIN,
  );
  const top = Math.max(VIEWPORT_MARGIN, Math.min(rawTop, maxTop));
  const maxHeight = Math.max(160, viewportHeight - VIEWPORT_MARGIN * 2);

  const title = inspectorTitle(pipe);
  const subtitle = inspectorSubtitle(pipe);

  return (
    <div
      role="dialog"
      aria-label={title}
      data-cell-canvas-chrome="true"
      data-cell-pipe-inspector={pipe.edge.id}
      onPointerDown={(event) => event.stopPropagation()}
      {...stylex.props(s.wrapper)}
      style={{ left, top, maxHeight }}
    >
      <Surface
        tone="raised"
        padding="none"
        shape="lg"
        xstyle={[overlay.popup, s.surface]}
      >
        <div {...stylex.props(s.header)}>
          <div {...stylex.props(s.headerTitles)}>
            <span {...stylex.props(s.title)}>{title}</span>
            {subtitle ? (
              <span {...stylex.props(s.subtitle)}>{subtitle}</span>
            ) : null}
          </div>
          <IconButton
            size="xs"
            variant="ghost"
            shape="round"
            label="Close connection editor"
            onClick={onClose}
          >
            <X size={14} />
          </IconButton>
        </div>

        {pipe.kind === "workflow" ? (
          <WorkflowPipeInspectorBody
            edge={pipe.edge}
            editable={editable}
            onUpdate={onUpdateWorkflowEdge}
            onRemove={(edgeId) => {
              onRemovePipe(edgeId);
              onClose();
            }}
          />
        ) : pipe.kind === "origin" ? (
          <OriginPipeInspectorBody
            edge={pipe.edge}
            editable={editable}
            onUpdateCollectionMode={onUpdateOriginCollectionMode}
            onRemove={(edgeId) => {
              onRemovePipe(edgeId);
              onClose();
            }}
          />
        ) : (
          <ViewerPipeInspectorBody
            edge={pipe.edge}
            editable={editable}
            onUpdate={onUpdateViewerEdge}
            onRemove={(edgeId) => {
              onRemovePipe(edgeId);
              onClose();
            }}
          />
        )}
      </Surface>
    </div>
  );
}

function CollectionModeSection({
  mode,
  disabled,
  onSelect,
}: {
  mode: RunEdgeCollectionMode;
  disabled: boolean;
  onSelect: (mode: RunEdgeCollectionMode) => void;
}) {
  return (
    <div {...stylex.props(s.section)}>
      <span {...stylex.props(s.sectionLabel)}>Collection</span>
      <div {...stylex.props(s.modeRow)}>
        <Button
          size="xs"
          variant="soft"
          pressed={mode === "direct"}
          disabled={disabled}
          xstyle={s.modeButton}
          onClick={() => onSelect("direct")}
        >
          Whole list
        </Button>
        <Button
          size="xs"
          variant="soft"
          pressed={mode === "map"}
          disabled={disabled}
          xstyle={s.modeButton}
          onClick={() => onSelect("map")}
        >
          Each item (map)
        </Button>
      </div>
    </div>
  );
}

function WorkflowPipeInspectorBody({
  edge,
  editable,
  onUpdate,
  onRemove,
}: {
  edge: WorkflowEdge;
  editable: boolean;
  onUpdate: (edgeId: string, update: WorkflowEdgeUpdate) => void;
  onRemove: (edgeId: string) => void;
}) {
  const issues = edge.data?.compatibilityIssues ?? [];
  const incompatible = issues.length > 0;
  const canEditRoute = editable && !incompatible;
  const enabled = edge.data?.enabled ?? true;
  const collectionMode = edge.data?.collectionMode ?? "direct";
  const showCollectionModes =
    (edge.data?.allowedCollectionModes?.length ?? 0) > 1;
  const choices = feedChoicesFromRouteOptions(
    edge.data?.sourcePortName ?? "",
    edge.data?.routeOptions ?? [],
  );
  const showFeedChoices =
    choices.length > 1 ||
    choices.some(
      (choice) =>
        Boolean(choice.route.projection) ||
        choice.route.conversionPath.length > 0,
    );

  return (
    <>
      {incompatible ? <Notice tone="danger">{issues.join(" ")}</Notice> : null}

      <div {...stylex.props(s.section)}>
        <Switch
          size="sm"
          label="Enabled"
          checked={enabled}
          disabled={!canEditRoute}
          onCheckedChange={(nextEnabled) =>
            onUpdate(edge.id, { enabled: nextEnabled })
          }
        />
      </div>

      {showCollectionModes ? (
        <CollectionModeSection
          mode={collectionMode}
          disabled={!canEditRoute}
          onSelect={(nextMode) =>
            onUpdate(edge.id, { collectionMode: nextMode })
          }
        />
      ) : null}

      {showFeedChoices ? (
        <div {...stylex.props(s.section)}>
          <span {...stylex.props(s.sectionLabel)}>Feed</span>
          <div {...stylex.props(s.choiceList)}>
            {choices.map((choice) => {
              const active =
                projectionsEqual(
                  edge.data?.projection,
                  choice.route.projection,
                ) &&
                conversionPathsEqual(
                  edge.data?.conversionPath ?? [],
                  choice.route.conversionPath,
                );
              return (
                <Button
                  key={choice.key}
                  size="xs"
                  variant="ghost"
                  block
                  pressed={active}
                  disabled={!canEditRoute}
                  xstyle={s.choiceButton}
                  onClick={() =>
                    onUpdate(edge.id, {
                      route: {
                        projection: choice.route.projection,
                        conversionPath: choice.route.conversionPath,
                      },
                    })
                  }
                >
                  <span {...stylex.props(s.choiceTitle)}>{choice.title}</span>
                  <span {...stylex.props(s.choiceDescription)}>
                    {choice.description}
                  </span>
                </Button>
              );
            })}
          </div>
        </div>
      ) : null}

      <div {...stylex.props(s.footer)}>
        <Button
          size="xs"
          variant="danger"
          disabled={!editable}
          onClick={() => onRemove(edge.id)}
        >
          Remove connection
        </Button>
      </div>
    </>
  );
}

function OriginPipeInspectorBody({
  edge,
  editable,
  onUpdateCollectionMode,
  onRemove,
}: {
  edge: ArtifactOriginEdge;
  editable: boolean;
  onUpdateCollectionMode: (
    originId: string,
    collectionMode: RunEdgeCollectionMode,
  ) => void;
  onRemove: (edgeId: string) => void;
}) {
  const collectionMode = edge.data.collectionMode ?? "direct";
  const showCollectionModes =
    (edge.data.allowedCollectionModes?.length ?? 0) > 1;

  return (
    <>
      {showCollectionModes ? (
        <CollectionModeSection
          mode={collectionMode}
          disabled={!editable}
          onSelect={(nextMode) =>
            onUpdateCollectionMode(edge.data.originId, nextMode)
          }
        />
      ) : null}

      <div {...stylex.props(s.footer)}>
        <Button
          size="xs"
          variant="danger"
          disabled={!editable}
          onClick={() => onRemove(edge.id)}
        >
          Disconnect
        </Button>
      </div>
    </>
  );
}

function ViewerPipeInspectorBody({
  edge,
  editable,
  onUpdate,
  onRemove,
}: {
  edge: ArtifactViewerEdge;
  editable: boolean;
  onUpdate: (edgeId: string, update: ArtifactViewerEdgeUpdate) => void;
  onRemove: (edgeId: string) => void;
}) {
  const choices = feedChoicesFromRouteOptions(
    edge.data?.sourcePortName ?? "",
    edge.data?.routeOptions ?? [],
  );

  return (
    <>
      {choices.length > 0 ? (
        <div {...stylex.props(s.section)}>
          <span {...stylex.props(s.sectionLabel)}>Feed</span>
          <div {...stylex.props(s.choiceList)}>
            {choices.map((choice) => {
              const active = projectionsEqual(
                edge.data?.projection,
                choice.route.projection,
              );
              return (
                <Button
                  key={choice.key}
                  size="xs"
                  variant="ghost"
                  block
                  pressed={active}
                  disabled={!editable}
                  xstyle={s.choiceButton}
                  onClick={() =>
                    onUpdate(edge.id, {
                      projection: choice.route.projection ?? null,
                    })
                  }
                >
                  <span {...stylex.props(s.choiceTitle)}>{choice.title}</span>
                  <span {...stylex.props(s.choiceDescription)}>
                    {choice.description}
                  </span>
                </Button>
              );
            })}
          </div>
        </div>
      ) : null}

      <div {...stylex.props(s.footer)}>
        <Button
          size="xs"
          variant="danger"
          disabled={!editable}
          onClick={() => onRemove(edge.id)}
        >
          Remove link
        </Button>
      </div>
    </>
  );
}
