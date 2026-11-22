"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";

import { useOptionalAuthSession } from "@/features/auth/AuthSessionBoundary";
import { sandboxSession } from "@/features/auth/dev-session";
import type { GraphPresentation } from "@/features/workbench/artifacts/artifact-viewer";
import { defaultNodeConfig } from "@/features/workbench/authoring/types";
import {
  CellCanvas,
  DEFAULT_CELL_GLASS_LOOK,
  DEFAULT_CELL_ROUTING,
  type CellCanvasHandle,
  type CellCanvasStats,
  type CellCardMove,
  type CellConnectionEnds,
} from "@/features/workbench/cell-canvas/CellCanvas";
import { plugRowOffset } from "@/features/workbench/cell-canvas/cell-card-geometry";
import type {
  AnnotationColorToken,
  CellCardSurfaceData,
  CellResizeCommit,
  CellSelectionSnapshot,
  OperatorCardSurfaceData,
} from "@/features/workbench/cell-canvas/cell-contracts";
import {
  annotationHexFromToken,
  cellGraphFromAuthoredDocument,
  graphCommandsFromCellAddPlug,
  graphCommandsFromCellConfigChange,
  graphCommandsFromCellConnect,
  graphCommandsFromCellDeleteForDocument,
  graphCommandsFromCellMovesForDocument,
  graphCommandsFromCellRemovePlug,
  graphCommandsFromCellResizeForDocument,
  type CellNodeRunState,
} from "@/features/workbench/cell-canvas/cell-document-adapter";
import type { CellGlassLook } from "@/features/workbench/cell-canvas/cell-glass-stage";
import {
  createDemoCellGraph,
  createStressCellGraph,
} from "@/features/workbench/cell-canvas/cell-graphs";
import { computeOperatorCardLayout } from "@/features/workbench/cell-canvas/cell-card-geometry";
import {
  CELL_SIZE,
  cellToWorldOrigin,
  type CellGraph,
  type CellPort,
  type CellRoutingOptions,
} from "@/features/workbench/cell-canvas/cell-model";
import { COLLECTION_PORT } from "@/features/workbench/authoring/collection-spec";
import { newNodeKind } from "@/features/workbench/authoring/project-graphs";
import {
  applyGraphCommandNormalized,
  type AuthoredGraphDocument,
} from "@/features/workbench/authoring/graph-document";
import { useNodeRegistry, useWorkspaces } from "@/hooks/use-api";

import {
  CellLookPanel,
  CellZoomBar,
  type CellGraphKind,
  type ShowcaseOperatorOption,
} from "./CellLookPanel";
import {
  createShowcaseAuthoredDocument,
  mergeShowcaseRegistry,
} from "./cell-showcase-graphs";

const ZOOM_STEP = 1.2;

const EMPTY_ID_SET: ReadonlySet<string> = new Set();
const EMPTY_SURFACES: Record<string, CellCardSurfaceData> = {};
const EMPTY_SELECTION: CellSelectionSnapshot = {
  cardIds: new Set(),
  pipeIds: new Set(),
};

const s = stylex.create({
  host: {
    position: "relative",
    width: "100%",
    height: "100svh",
    overflow: "hidden",
  },
  lookPanel: {
    position: "absolute",
    top: "16px",
    left: "16px",
    zIndex: 30,
  },
  zoomBar: {
    position: "absolute",
    bottom: "16px",
    left: "16px",
    zIndex: 30,
  },
});

const LookPanel = React.memo(CellLookPanel);
const ZoomBar = React.memo(CellZoomBar);

function useFrameRate(): number | null {
  const [rate, setRate] = React.useState<number | null>(null);
  React.useEffect(() => {
    let frames = 0;
    let since = performance.now();
    let handle = 0;
    const tick = (now: number) => {
      frames += 1;
      if (now - since >= 500) {
        setRate(Math.round((frames * 1000) / (now - since)));
        frames = 0;
        since = now;
      }
      handle = requestAnimationFrame(tick);
    };
    handle = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(handle);
  }, []);
  return rate;
}

function specOptionKey(operatorId: string, version: number): string {
  return `${operatorId}@${version}`;
}

export function CellCanvasSpike() {
  const authSession = useOptionalAuthSession();
  const devBypass = sandboxSession() !== null;
  const liveUserId = !devBypass ? authSession?.session.user_id : undefined;
  const { data: workspaces } = useWorkspaces(liveUserId);
  const { data: liveRegistry } = useNodeRegistry(
    !devBypass ? workspaces?.[0]?.id : undefined,
  );

  const effectiveRegistry = React.useMemo(
    () => mergeShowcaseRegistry(liveRegistry),
    [liveRegistry],
  );

  const showcaseOptions = React.useMemo<ShowcaseOperatorOption[]>(() => {
    return effectiveRegistry.nodes
      .filter((spec) => spec.catalog_visible !== false)
      .map((spec) => ({
        key: specOptionKey(spec.operator_id, spec.operator_version),
        label: spec.title || spec.operator_id,
      }));
  }, [effectiveRegistry.nodes]);

  const [pickedOperatorKey, setSelectedOperatorKey] = React.useState("");
  // A pick the registry no longer offers falls back to its first operator.
  const selectedOperatorKey = showcaseOptions.some(
    (opt) => opt.key === pickedOperatorKey,
  )
    ? pickedOperatorKey
    : (showcaseOptions[0]?.key ?? "");

  const [graphKind, setGraphKind] = React.useState<CellGraphKind>("demo");
  const [mockGraph, setMockGraph] =
    React.useState<CellGraph>(createDemoCellGraph);
  const [mockSurfaces, setMockSurfaces] =
    React.useState<Record<string, CellCardSurfaceData>>(EMPTY_SURFACES);

  const initialShowcase = React.useMemo(
    () => createShowcaseAuthoredDocument(mergeShowcaseRegistry(null)),
    [],
  );
  const [showcaseDoc, setShowcaseDoc] = React.useState<AuthoredGraphDocument>(
    initialShowcase.document,
  );
  const [showcasePresentation, setShowcasePresentation] =
    React.useState<GraphPresentation>(initialShowcase.presentation);
  const [showcaseRunState, setShowcaseRunState] = React.useState<
    Readonly<Record<string, CellNodeRunState>>
  >(initialShowcase.nodeRunState);
  const [collapsedAppendices, setCollapsedAppendices] =
    React.useState<ReadonlySet<string>>(EMPTY_ID_SET);
  const [configSections, setConfigSections] = React.useState<
    Readonly<Record<string, Readonly<Record<string, boolean>>>>
  >({});

  const [selection, setSelection] =
    React.useState<CellSelectionSnapshot>(EMPTY_SELECTION);
  const [look, setLook] = React.useState<CellGlassLook>(
    DEFAULT_CELL_GLASS_LOOK,
  );
  const [routing, setRouting] =
    React.useState<CellRoutingOptions>(DEFAULT_CELL_ROUTING);
  const [zoom, setZoom] = React.useState(1);
  const [stats, setStats] = React.useState<CellCanvasStats>({
    cards: 0,
    pipes: 0,
    deepCount: 0,
    reroutes: 0,
    draggedCardId: null,
  });
  const fps = useFrameRate();

  const canvasHandleRef = React.useRef<CellCanvasHandle | null>(null);
  const pendingFitRef = React.useRef(false);
  const serialRef = React.useRef(1);

  const showcaseScene = React.useMemo(
    () =>
      cellGraphFromAuthoredDocument(showcaseDoc, effectiveRegistry, {
        presentation: showcasePresentation,
        nodeRunState: showcaseRunState,
        collapsedAppendices,
        configSections,
      }),
    [
      collapsedAppendices,
      configSections,
      effectiveRegistry,
      showcaseDoc,
      showcasePresentation,
      showcaseRunState,
    ],
  );

  const activeGraph =
    graphKind === "showcase" ? showcaseScene.graph : mockGraph;
  const activeSurfaces =
    graphKind === "showcase" ? showcaseScene.surfaceById : mockSurfaces;

  const showcaseDocRef = React.useRef(showcaseDoc);
  const showcasePresentationRef = React.useRef(showcasePresentation);
  const effectiveRegistryRef = React.useRef(effectiveRegistry);
  const graphKindRef = React.useRef(graphKind);

  React.useLayoutEffect(() => {
    showcaseDocRef.current = showcaseDoc;
    showcasePresentationRef.current = showcasePresentation;
    effectiveRegistryRef.current = effectiveRegistry;
    graphKindRef.current = graphKind;
  });

  React.useLayoutEffect(() => {
    if (!pendingFitRef.current || !canvasHandleRef.current) return;
    pendingFitRef.current = false;
    canvasHandleRef.current.fitGraph();
  }, [graphKind, activeGraph]);

  const onHandleReady = React.useCallback((handle: CellCanvasHandle | null) => {
    canvasHandleRef.current = handle;
    if (handle && pendingFitRef.current) {
      pendingFitRef.current = false;
      handle.fitGraph();
    }
  }, []);

  const commitShowcaseCommands = React.useCallback(
    (
      commands: readonly ReturnType<
        typeof graphCommandsFromCellMovesForDocument
      >[number][],
    ) => {
      if (commands.length === 0) return;
      setShowcaseDoc((current) =>
        commands.reduce(applyGraphCommandNormalized, current),
      );
    },
    [],
  );

  const onGraph = React.useCallback((kind: CellGraphKind) => {
    canvasHandleRef.current?.cancelGesture();
    setGraphKind(kind);
    pendingFitRef.current = true;
    if (kind === "showcase") {
      const fresh = createShowcaseAuthoredDocument(
        effectiveRegistryRef.current,
      );
      setShowcaseDoc(fresh.document);
      setShowcasePresentation(fresh.presentation);
      setShowcaseRunState(fresh.nodeRunState);
      setCollapsedAppendices(EMPTY_ID_SET);
      setSelection({ cardIds: new Set(["ocr-extract"]), pipeIds: new Set() });
      return;
    }
    if (kind === "stress") {
      setMockGraph(createStressCellGraph());
    } else {
      setMockGraph(createDemoCellGraph());
    }
    setMockSurfaces(EMPTY_SURFACES);
    setSelection(EMPTY_SELECTION);
  }, []);

  const onMoveCards = React.useCallback(
    (moves: readonly CellCardMove[]) => {
      if (graphKindRef.current !== "showcase") {
        const byId = new Map(moves.map((m) => [m.cardId, m]));
        setMockGraph((current) => ({
          ...current,
          cards: current.cards.map((card) => {
            const moved = byId.get(card.id);
            return moved ? { ...card, col: moved.col, row: moved.row } : card;
          }),
        }));
        return;
      }

      const doc = showcaseDocRef.current;
      const docCommands = graphCommandsFromCellMovesForDocument(doc, moves);
      commitShowcaseCommands(docCommands);

      const moveById = new Map(moves.map((m) => [m.cardId, m]));
      setShowcasePresentation((current) => {
        const hasViewerMove = current.viewers.some((v) => moveById.has(v.id));
        const hasAnnotationMove = current.annotations.some((a) =>
          moveById.has(a.id),
        );
        if (!hasViewerMove && !hasAnnotationMove) return current;
        return {
          ...current,
          viewers: current.viewers.map((v) => {
            const moved = moveById.get(v.id);
            return moved
              ? { ...v, position: cellToWorldOrigin(moved.col, moved.row) }
              : v;
          }),
          annotations: current.annotations.map((a) => {
            const moved = moveById.get(a.id);
            return moved
              ? { ...a, position: cellToWorldOrigin(moved.col, moved.row) }
              : a;
          }),
        };
      });
    },
    [commitShowcaseCommands],
  );

  const onResizeCard = React.useCallback(
    (commit: CellResizeCommit) => {
      if (graphKindRef.current !== "showcase") {
        setMockGraph((current) => ({
          ...current,
          cards: current.cards.map((card) =>
            card.id === commit.cardId
              ? {
                  ...card,
                  widthCells: commit.widthCells,
                  heightCells: commit.heightCells,
                }
              : card,
          ),
        }));
        return;
      }

      const doc = showcaseDocRef.current;
      const docCommands = graphCommandsFromCellResizeForDocument(doc, commit);
      if (docCommands.length > 0) {
        commitShowcaseCommands(docCommands);
        return;
      }
      setShowcasePresentation((current) => ({
        ...current,
        viewers: current.viewers.map((v) =>
          v.id === commit.cardId
            ? {
                ...v,
                layout: {
                  width: commit.widthCells * CELL_SIZE,
                  body_height: commit.heightCells * CELL_SIZE,
                  appendix_height: null,
                },
              }
            : v,
        ),
        annotations: current.annotations.map((a) =>
          a.id === commit.cardId
            ? {
                ...a,
                layout: {
                  width: commit.widthCells * CELL_SIZE,
                  height: commit.heightCells * CELL_SIZE,
                },
              }
            : a,
        ),
      }));
    },
    [commitShowcaseCommands],
  );

  const onConnect = React.useCallback(
    (ends: CellConnectionEnds) => {
      if (graphKindRef.current !== "showcase") {
        setMockGraph((current) => {
          const duplicate = current.pipes.some(
            (pipe) =>
              pipe.sourceCardId === ends.sourceCardId &&
              pipe.sourcePortId === ends.sourcePortId &&
              pipe.targetCardId === ends.targetCardId &&
              pipe.targetPortId === ends.targetPortId,
          );
          if (duplicate) return current;
          const ids = new Set(current.pipes.map((pipe) => pipe.id));
          let serial = current.pipes.length + 1;
          while (ids.has(`wire-${serial}`)) serial += 1;
          return {
            ...current,
            pipes: [
              ...current.pipes,
              { id: `wire-${serial}`, ...ends, enabled: true },
            ],
          };
        });
        return;
      }

      const doc = showcaseDocRef.current;
      const nodeIds = new Set(doc.nodes.map((n) => n.id));
      if (!nodeIds.has(ends.sourceCardId) || !nodeIds.has(ends.targetCardId)) {
        return;
      }
      const edgeId = `wire-${++serialRef.current}`;
      const cmds = graphCommandsFromCellConnect({
        edgeId,
        sourceCardId: ends.sourceCardId,
        sourcePortName: ends.sourcePortId,
        targetCardId: ends.targetCardId,
        targetPortName: ends.targetPortId,
      });
      commitShowcaseCommands(cmds);
    },
    [commitShowcaseCommands],
  );

  const onRemoveCards = React.useCallback(
    (cardIds: readonly string[]) => {
      const removed = new Set(cardIds);
      if (graphKindRef.current !== "showcase") {
        setMockGraph((current) => ({
          cards: current.cards.filter((c) => !removed.has(c.id)),
          pipes: current.pipes.filter(
            (p) => !removed.has(p.sourceCardId) && !removed.has(p.targetCardId),
          ),
        }));
        setSelection((current) => ({
          cardIds: new Set(
            [...current.cardIds].filter((id) => !removed.has(id)),
          ),
          pipeIds: current.pipeIds,
        }));
        return;
      }

      commitShowcaseCommands(
        graphCommandsFromCellDeleteForDocument(
          showcaseDocRef.current,
          cardIds,
          [],
        ),
      );
      setShowcasePresentation((current) => ({
        ...current,
        viewers: current.viewers.filter((v) => !removed.has(v.id)),
        links: current.links.filter(
          (l) =>
            !removed.has(l.source_node_id) && !removed.has(l.target_viewer_id),
        ),
        annotations: current.annotations.filter((a) => !removed.has(a.id)),
      }));
      setSelection((current) => ({
        cardIds: new Set([...current.cardIds].filter((id) => !removed.has(id))),
        pipeIds: current.pipeIds,
      }));
    },
    [commitShowcaseCommands],
  );

  const onRemovePipes = React.useCallback(
    (pipeIds: readonly string[]) => {
      const removed = new Set(pipeIds);
      if (graphKindRef.current !== "showcase") {
        setMockGraph((current) => ({
          ...current,
          pipes: current.pipes.filter((p) => !removed.has(p.id)),
        }));
        setSelection((current) => ({
          cardIds: current.cardIds,
          pipeIds: new Set(
            [...current.pipeIds].filter((id) => !removed.has(id)),
          ),
        }));
        return;
      }

      commitShowcaseCommands(
        graphCommandsFromCellDeleteForDocument(
          showcaseDocRef.current,
          [],
          pipeIds,
        ),
      );
      setShowcasePresentation((current) => ({
        ...current,
        links: current.links.filter((l) => !removed.has(l.id)),
      }));
      setSelection((current) => ({
        cardIds: current.cardIds,
        pipeIds: new Set([...current.pipeIds].filter((id) => !removed.has(id))),
      }));
    },
    [commitShowcaseCommands],
  );

  const onOperatorConfigChange = React.useCallback(
    (cardId: string, fieldId: string, value: unknown) => {
      if (graphKindRef.current !== "showcase") {
        // Mock surfaces hold plain fields only, so only a primitive lands.
        if (
          typeof value !== "string" &&
          typeof value !== "number" &&
          typeof value !== "boolean"
        ) {
          return;
        }
        setMockSurfaces((current) => {
          const surface = current[cardId];
          if (surface?.kind !== "operator" || !surface.configFields) {
            return current;
          }
          return {
            ...current,
            [cardId]: {
              ...surface,
              configFields: surface.configFields.map((field) =>
                field.id === fieldId ? { ...field, value } : field,
              ),
            },
          };
        });
        return;
      }
      commitShowcaseCommands(
        graphCommandsFromCellConfigChange(cardId, fieldId, value),
      );
    },
    [commitShowcaseCommands],
  );

  const onOperatorAddPlug = React.useCallback(
    (cardId: string, portName: string) => {
      if (graphKindRef.current !== "showcase") {
        setMockSurfaces((current) => {
          const surface = current[cardId];
          const card = mockGraph.cards.find((c) => c.id === cardId);
          if (
            surface?.kind !== "operator" ||
            !surface.instancePlugGroups ||
            !card
          ) {
            return current;
          }
          let addedPort: CellPort | null = null;
          const nextGroups = surface.instancePlugGroups.map((group) => {
            if (group.portName !== portName) return group;
            const nextIndex = group.plugs.length + 1;
            const plugId = `${portName}::plug-${Date.now()}-${nextIndex}`;
            const label = `Hint ${nextIndex}`;
            addedPort = {
              id: plugId,
              name: label,
              direction: "input",
              rowOffset: plugRowOffset(group, group.plugs.length),
              artifactTypeId: group.artifactTypeId,
              shape: group.shape,
            };
            return {
              ...group,
              plugs: [...group.plugs, { plugId, label, connected: false }],
            };
          });
          if (!addedPort) return current;
          const nextSurface: OperatorCardSurfaceData = {
            ...surface,
            instancePlugGroups: nextGroups,
          };
          const nextHeight = computeOperatorCardLayout(
            { ...card, heightCells: 2, ports: [...card.ports, addedPort] },
            nextSurface,
          ).totalHeightCells;
          setMockGraph((g) => ({
            ...g,
            cards: g.cards.map((c) =>
              c.id === cardId
                ? {
                    ...c,
                    ports: [...c.ports, addedPort!],
                    heightCells: nextHeight,
                  }
                : c,
            ),
          }));
          return { ...current, [cardId]: nextSurface };
        });
        return;
      }
      const node = showcaseDocRef.current.nodes.find((n) => n.id === cardId);
      if (!node) return;
      commitShowcaseCommands(
        graphCommandsFromCellAddPlug(cardId, portName, node.input_plugs),
      );
    },
    [commitShowcaseCommands, mockGraph.cards],
  );

  const onOperatorRemovePlug = React.useCallback(
    (cardId: string, portName: string, plugId: string) => {
      if (graphKindRef.current !== "showcase") return;
      commitShowcaseCommands(
        graphCommandsFromCellRemovePlug(cardId, portName, plugId),
      );
    },
    [commitShowcaseCommands],
  );

  const onCollectionRemoveMember = React.useCallback(
    (cardId: string, memberId: string) => {
      if (graphKindRef.current !== "showcase") return;
      commitShowcaseCommands(
        graphCommandsFromCellRemovePlug(cardId, COLLECTION_PORT, memberId),
      );
    },
    [commitShowcaseCommands],
  );

  const onOperatorToggleAppendix = React.useCallback((cardId: string) => {
    setCollapsedAppendices((current) => {
      const next = new Set(current);
      if (next.has(cardId)) next.delete(cardId);
      else next.add(cardId);
      return next;
    });
  }, []);

  const onOperatorToggleConfigSection = React.useCallback(
    (cardId: string, sectionKey: string, open: boolean) => {
      setConfigSections((current) => ({
        ...current,
        [cardId]: { ...current[cardId], [sectionKey]: open },
      }));
    },
    [],
  );

  const onOperatorRun = React.useCallback((cardId: string) => {
    if (graphKindRef.current !== "showcase") {
      setMockGraph((current) => ({
        ...current,
        cards: current.cards.map((c) =>
          c.id === cardId
            ? { ...c, status: c.status === "working" ? "done" : "working" }
            : c,
        ),
      }));
      return;
    }
    setShowcaseRunState((current) => {
      const prev = current[cardId];
      const nextStatus = prev?.status === "working" ? "done" : "working";
      return {
        ...current,
        [cardId]: {
          ...prev,
          status: nextStatus,
          statusLabel: nextStatus === "working" ? "Running" : "120 ms",
        },
      };
    });
  }, []);

  const onAnnotationColorChange = React.useCallback(
    (cardId: string, color: AnnotationColorToken) => {
      if (graphKindRef.current !== "showcase") return;
      const hex = annotationHexFromToken(color);
      setShowcasePresentation((current) => ({
        ...current,
        annotations: current.annotations.map((ann) =>
          ann.id === cardId ? { ...ann, color: hex } : ann,
        ),
      }));
    },
    [],
  );

  const onAddShowcaseOperator = React.useCallback(() => {
    const spec =
      effectiveRegistryRef.current.nodes.find(
        (n) =>
          specOptionKey(n.operator_id, n.operator_version) ===
          selectedOperatorKey,
      ) ?? effectiveRegistryRef.current.nodes[0];
    if (!spec) return;
    const id = `node-${++serialRef.current}`;
    const maxCol = showcaseScene.graph.cards.reduce(
      (max, card) => Math.max(max, card.col + card.widthCells),
      2,
    );
    const col = Math.min(maxCol + 3, 66);
    const row = 24;
    commitShowcaseCommands([
      {
        kind: "add_node",
        node: {
          id,
          kind: newNodeKind(spec),
          operator_id: spec.operator_id,
          operator_version: spec.operator_version,
          position: cellToWorldOrigin(col, row),
          layout: null,
          config: defaultNodeConfig(spec),
          input_plugs: spec.inputs
            .filter((p) => p.instance_plugs)
            .map((p) => ({ id: `${p.name}-plug-1`, port: p.name })),
          artifact_type_bindings: [],
        },
      },
    ]);
    setSelection({ cardIds: new Set([id]), pipeIds: new Set() });
  }, [commitShowcaseCommands, selectedOperatorKey, showcaseScene.graph.cards]);

  const onZoomIn = React.useCallback(
    () => canvasHandleRef.current?.zoomBy(ZOOM_STEP),
    [],
  );
  const onZoomOut = React.useCallback(
    () => canvasHandleRef.current?.zoomBy(1 / ZOOM_STEP),
    [],
  );
  const onZoomPreset = React.useCallback(
    (preset: number) => canvasHandleRef.current?.zoomAtCenter(preset),
    [],
  );
  const onFit = React.useCallback(
    () => canvasHandleRef.current?.fitGraph(),
    [],
  );

  return (
    <div {...stylex.props(s.host)}>
      <CellCanvas
        graph={activeGraph}
        surfaceById={activeSurfaces}
        look={look}
        routing={routing}
        selectedCardIds={selection.cardIds}
        selectedPipeIds={selection.pipeIds}
        fitLeftClearance={270}
        dataGraph={graphKind}
        exposeDebugApi
        onMoveCards={onMoveCards}
        onResizeCard={onResizeCard}
        onConnect={onConnect}
        onRemoveCards={onRemoveCards}
        onRemovePipes={onRemovePipes}
        onSelectionChange={setSelection}
        onOperatorRun={onOperatorRun}
        onOperatorConfigChange={onOperatorConfigChange}
        onOperatorAddPlug={onOperatorAddPlug}
        onOperatorRemovePlug={onOperatorRemovePlug}
        onOperatorToggleAppendix={onOperatorToggleAppendix}
        onOperatorToggleConfigSection={onOperatorToggleConfigSection}
        onCollectionRemoveMember={onCollectionRemoveMember}
        onAnnotationColorChange={onAnnotationColorChange}
        onHandleReady={onHandleReady}
        onViewportZoomChange={setZoom}
        onStatsChange={setStats}
      />
      <div {...stylex.props(s.lookPanel)}>
        <LookPanel
          graph={graphKind}
          onGraph={onGraph}
          counts={{
            cards: stats.cards,
            pipes: stats.pipes,
            deepCount: stats.deepCount,
            reroutes: stats.reroutes,
          }}
          fps={fps}
          look={look}
          onLook={setLook}
          routing={routing}
          onRouting={setRouting}
          showcaseRegistrySource={liveRegistry ? "live" : "fixture"}
          showcaseOperators={showcaseOptions}
          selectedOperatorKey={selectedOperatorKey}
          onSelectedOperatorKeyChange={setSelectedOperatorKey}
          onAddShowcaseOperator={onAddShowcaseOperator}
        />
      </div>
      <div {...stylex.props(s.zoomBar)}>
        <ZoomBar
          zoom={zoom}
          onZoomIn={onZoomIn}
          onZoomOut={onZoomOut}
          onZoomPreset={onZoomPreset}
          onFit={onFit}
        />
      </div>
    </div>
  );
}
