"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  Circle,
  Copy,
  Grid3x3,
  Layers,
  LayoutGrid,
  Maximize,
  Play,
  Plus,
  Scan,
  Search,
  Square,
  SquareDashedMousePointer,
  StickyNote,
  Trash2,
  Type,
  Unlink,
} from "lucide-react";

import type { NodeRegistry, NodeSpec } from "@/lib/api";
import {
  Menu,
  MenuContent,
  MenuGroup,
  MenuGroupLabel,
  MenuItem,
  MenuLabel,
  MenuSeparator,
  MenuSubmenu,
  MenuSubmenuTrigger,
  MenuTrigger,
} from "@/components/ui/menu";
import { tokens } from "@/lib/stylex/tokens.stylex";
import type { AnnotationKind } from "../../canvas/annotations";
import {
  useNodeMenuEntry,
  type NodeMenuRegistry,
} from "../../canvas/nodes/node-menu-registry";
import {
  buildSourceFilters,
  catalogNodeKey,
  catalogNodesForFilter,
  catalogNodeSpecs,
  sortCatalogNodes,
} from "../../model/node-catalog";
import type { CanvasMenuRequest } from "./canvas-menu-target";

/** What the selection allows, as the selection bar and toolbar decide it. */
export interface CanvasMenuSelection {
  count: number;
  workflowCount: number;
  canRun: boolean;
  canDuplicate: boolean;
  canDelete: boolean;
  /** Present when the selection can be collected; `disabled` says why not. */
  collect: { disabled: boolean; title?: string } | null;
  canTidy: boolean;
}

/** Every action the menu offers. "Here" means at the point it was opened. */
export interface CanvasMenuActions {
  searchNodes: () => void;
  addNodeHere: (spec: NodeSpec) => void;
  addAnnotationHere: (kind: AnnotationKind) => void;
  selectAll: () => void;
  fitView: () => void;
  openCanvasSettings: () => void;
  runSelection: () => void;
  collect: () => void;
  tidy: () => void;
  duplicate: () => void;
  remove: () => void;
  fitSelection: () => void;
  deleteEdge: (edgeId: string) => void;
}

const ANNOTATIONS: readonly {
  kind: AnnotationKind;
  label: string;
  icon: typeof Type;
}[] = [
  { kind: "text", label: "Text", icon: Type },
  { kind: "rectangle", label: "Rectangle", icon: Square },
  { kind: "ellipse", label: "Ellipse", icon: Circle },
];

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

/**
 * The canvas right-click menu. On the empty canvas it adds things where it
 * was opened; on a node it opens on that node's own facts and actions, then
 * what can be done with the selection; on an edge it removes the connection.
 */
export function CanvasContextMenu({
  request,
  registry,
  activeGraphId,
  canEdit,
  selection,
  nodeMenus,
  actions,
  onClose,
}: {
  request: CanvasMenuRequest | null;
  registry: NodeRegistry | null;
  activeGraphId: string | null;
  canEdit: boolean;
  selection: CanvasMenuSelection;
  nodeMenus: NodeMenuRegistry;
  actions: CanvasMenuActions;
  onClose: () => void;
}) {
  // The last request stays on screen while the menu animates out.
  const [shown, setShown] = React.useState(request);
  if (request !== null && request !== shown) setShown(request);
  const target = shown?.target ?? null;
  const nodeEntry = useNodeMenuEntry(
    nodeMenus,
    target?.kind === "node" ? target.nodeId : null,
  );
  const point = shown?.point ?? null;
  const anchor = React.useMemo(
    () =>
      point
        ? {
            getBoundingClientRect: () =>
              DOMRect.fromRect({ x: point.x, y: point.y, width: 0, height: 0 }),
          }
        : null,
    [point],
  );

  return (
    <Menu
      open={request !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      {/*
        Base UI gives a root menu its place in the menu tree through a trigger;
        without one, a submenu opening reads as a sibling opening and closes
        the menu. This one is invisible and never pressed. The menu is placed
        by the click itself (the positioner's anchor), not by the trigger,
        which Base UI keeps measuring from its first opening.
      */}
      <MenuTrigger
        aria-hidden="true"
        tabIndex={-1}
        {...stylex.props(s.anchor)}
      />
      <MenuContent
        anchor={anchor}
        side="bottom"
        align="start"
        sideOffset={2}
        aria-label="Canvas menu"
        finalFocus={() => {
          const back = shown?.returnFocus;
          return back?.isConnected ? back : false;
        }}
      >
        {target?.kind === "pane" ? (
          <PaneItems
            registry={registry}
            activeGraphId={activeGraphId}
            canEdit={canEdit}
            actions={actions}
          />
        ) : target?.kind === "edge" ? (
          <Item
            icon={Unlink}
            label="Delete connection"
            danger
            disabled={!canEdit}
            onClick={() => actions.deleteEdge(target.edgeId)}
          />
        ) : target ? (
          <>
            {target.kind === "node" && nodeEntry ? (
              <>
                <MenuGroup>
                  <MenuGroupLabel xstyle={s.info}>
                    <span {...stylex.props(s.infoTitle)}>
                      {nodeEntry.info.title}
                    </span>
                    {(nodeEntry.info.lines ?? []).map((line, index) => (
                      <span key={index}>{line}</span>
                    ))}
                    {nodeEntry.info.mono ? (
                      <span {...stylex.props(s.infoMono)}>
                        {nodeEntry.info.mono}
                      </span>
                    ) : null}
                  </MenuGroupLabel>
                  {nodeEntry.items
                    .filter((item) => item.id !== "remove")
                    .map((item) => (
                      <MenuItem
                        key={item.id}
                        disabled={item.disabled}
                        onClick={item.onClick}
                        icon={item.icon ?? <span />}
                      >
                        {item.label}
                      </MenuItem>
                    ))}
                </MenuGroup>
                <MenuSeparator />
              </>
            ) : target.kind === "selection" ? (
              <MenuGroup>
                <MenuLabel>
                  {plural(selection.count, "node")} selected
                </MenuLabel>
              </MenuGroup>
            ) : null}
            <SelectionItems selection={selection} actions={actions} />
          </>
        ) : null}
      </MenuContent>
    </Menu>
  );
}

function PaneItems({
  registry,
  activeGraphId,
  canEdit,
  actions,
}: {
  registry: NodeRegistry | null;
  activeGraphId: string | null;
  canEdit: boolean;
  actions: CanvasMenuActions;
}) {
  // The catalog, by source, as the Add node picker groups it.
  const sources = React.useMemo(() => {
    if (!registry) return [];
    const nodes = catalogNodeSpecs(registry, activeGraphId);
    return buildSourceFilters(registry)
      .filter((source) => source.kind !== "all")
      .map((source) => ({
        id: source.id,
        title: source.title,
        nodes: sortCatalogNodes(catalogNodesForFilter(nodes, source)),
      }))
      .filter((source) => source.nodes.length > 0);
  }, [activeGraphId, registry]);

  return (
    <>
      <Item
        icon={Search}
        label="Search nodes…"
        disabled={!canEdit || !registry}
        onClick={actions.searchNodes}
      />
      <Submenu
        icon={Plus}
        label="Add node"
        disabled={!canEdit || sources.length === 0}
      >
        {sources.map((source) => (
          <Submenu key={source.id} label={source.title}>
            {source.nodes.map((spec) => (
              <Item
                key={catalogNodeKey(spec)}
                label={spec.title}
                title={spec.description || undefined}
                disabled={spec.runnable === false}
                onClick={() => actions.addNodeHere(spec)}
              />
            ))}
          </Submenu>
        ))}
      </Submenu>
      <Submenu icon={StickyNote} label="Annotation" disabled={!canEdit}>
        {ANNOTATIONS.map((annotation) => (
          <Item
            key={annotation.kind}
            icon={annotation.icon}
            label={annotation.label}
            onClick={() => actions.addAnnotationHere(annotation.kind)}
          />
        ))}
      </Submenu>
      <MenuSeparator />
      <Item
        icon={SquareDashedMousePointer}
        label="Select all"
        onClick={actions.selectAll}
      />
      <Item icon={Maximize} label="Fit view" onClick={actions.fitView} />
      <MenuSeparator />
      <Item
        icon={Grid3x3}
        label="Canvas settings…"
        onClick={actions.openCanvasSettings}
      />
    </>
  );
}

function SelectionItems({
  selection,
  actions,
}: {
  selection: CanvasMenuSelection;
  actions: CanvasMenuActions;
}) {
  const many = selection.count > 1;
  return (
    <>
      {selection.workflowCount ? (
        <Item
          icon={Play}
          label={
            selection.workflowCount > 1
              ? `Run ${plural(selection.workflowCount, "node")}`
              : "Run node"
          }
          disabled={!selection.canRun}
          onClick={actions.runSelection}
        />
      ) : null}
      {selection.collect ? (
        <Item
          icon={Layers}
          label="Collect"
          title={selection.collect.title}
          disabled={selection.collect.disabled}
          onClick={actions.collect}
        />
      ) : null}
      {selection.canTidy ? (
        <Item icon={LayoutGrid} label="Tidy up" onClick={actions.tidy} />
      ) : null}
      <Item
        icon={Copy}
        label={
          many ? `Duplicate ${plural(selection.count, "node")}` : "Duplicate"
        }
        disabled={!selection.canDuplicate}
        onClick={actions.duplicate}
      />
      <Item
        icon={Scan}
        label={many ? "Fit selection" : "Fit to node"}
        onClick={actions.fitSelection}
      />
      <MenuSeparator />
      <Item
        icon={Trash2}
        label={many ? `Delete ${plural(selection.count, "node")}` : "Delete"}
        shortcut="⌫"
        danger
        disabled={!selection.canDelete}
        onClick={actions.remove}
      />
    </>
  );
}

function Item({
  icon: Icon,
  label,
  title,
  shortcut,
  danger = false,
  disabled = false,
  onClick,
}: {
  icon?: typeof Plus;
  label: string;
  title?: string;
  shortcut?: string;
  danger?: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <MenuItem
      disabled={disabled}
      title={title}
      onClick={onClick}
      danger={danger}
      hint={shortcut}
      icon={Icon ? <Icon size={13} aria-hidden="true" /> : <span />}
    >
      {label}
    </MenuItem>
  );
}

function Submenu({
  icon: Icon,
  label,
  disabled = false,
  children,
}: {
  icon?: typeof Plus;
  label: string;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <MenuSubmenu disabled={disabled}>
      <MenuSubmenuTrigger
        icon={Icon ? <Icon size={13} aria-hidden="true" /> : <span />}
      >
        {label}
      </MenuSubmenuTrigger>
      <MenuContent
        side="inline-end"
        align="start"
        sideOffset={-2}
        alignOffset={-5}
      >
        {children}
      </MenuContent>
    </MenuSubmenu>
  );
}

const s = stylex.create({
  anchor: {
    position: "fixed",
    top: 0,
    left: 0,
    width: 0,
    height: 0,
    padding: 0,
    borderWidth: 0,
    opacity: 0,
    pointerEvents: "none",
  },
  info: {
    display: "grid",
    gap: "2px",
    padding: "6px 8px 8px",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
    overflowWrap: "anywhere",
  },
  infoTitle: {
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    fontWeight: 560,
  },
  infoMono: {
    marginTop: "2px",
    color: tokens.colorSubtle,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "10px",
  },
});
