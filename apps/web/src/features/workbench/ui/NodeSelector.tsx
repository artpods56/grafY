"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  ArrowLeft,
  ArrowDownToLine,
  ArrowUpFromLine,
  Cable,
  ExternalLink,
  LayoutGrid,
  LibraryBig,
  Package,
  Plus,
  Search,
  Settings2,
  Workflow,
} from "lucide-react";

import {
  connectionRoutesFor,
  encodeHandleId,
  type ConnectionRoute,
} from "../canvas/handles";
import { schemaFields, type SchemaField } from "../canvas/config-schema";
import { artifactTypeColor } from "../canvas/nodes.css";
import {
  artifactTitleFor,
  CatalogNodePreview,
  fieldTypeLabel,
  portKey,
} from "./CatalogNodePreview";
import {
  acceptedPortShapes,
  portArtifactType,
  portArtifactTypeVariable,
  portHasInstancePlugs,
  portMetaForPort,
} from "../canvas/types";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import type { NodeRegistry, NodeSpec, Port } from "@/lib/api";
import { FINE_POINTER_QUERY, useMediaQuery } from "@/hooks/use-media-query";
import { tokens } from "@/lib/stylex/tokens.stylex";
import {
  buildCatalogFilters,
  buildSourceFilters,
  catalogNodeKey,
  catalogNodeSpecs,
  filterAndSearchCatalogNodes,
  INPUT_NODES_FILTER,
  moduleReleaseSpecs,
  nodesCompatibleWithPort,
  sourceFilterId,
  sortCatalogNodes,
  type CatalogFilter,
} from "../model/node-catalog";

const MODULE_PLUGIN_SLUG = "graph.module";
const MOBILE_NODE_SELECTOR_QUERY = "(max-width: 720px)";

/** A port-scoped Add node invocation using the same routes as canvas wiring. */
export type NodeSelectorCompatibilityContext =
  | {
      direction: "upstream";
      port: Port & { readonly direction: "input" };
    }
  | {
      direction: "downstream";
      port: Port & { readonly direction: "output" };
    };

export interface NodeSelectorProps {
  open: boolean;
  registry: NodeRegistry;
  activeGraphId: string | null;
  /** Limits results to nodes that can connect to the invoking port. */
  compatibility?: NodeSelectorCompatibilityContext;
  /** User-facing reason the registry could not be loaded. */
  errorMessage?: string | null;
  loading?: boolean;
  /** Keeps inspection available while disabling graph mutation for viewers. */
  canInsert?: boolean;
  insertDisabledReason?: string;
  /** Controlled-dialog opener, forwarded to Base UI's finalFocus contract. */
  returnFocusRef?: React.RefObject<HTMLElement | null>;
  onOpenChange: (open: boolean) => void;
  onAddNode: (spec: NodeSpec) => void;
  onRetry?: () => void;
  onOpenGraph?: (graphId: string) => void;
  onOpenWorkspaceLibrary?: () => void;
}

interface CompatibleNode {
  spec: NodeSpec;
  routeSummary: string;
  additionalRouteCount: number;
}

interface CompatiblePortPair {
  source: Port;
  target: Port;
  route: ConnectionRoute;
  routeCount: number;
}

function nodeKey(spec: NodeSpec): string {
  return catalogNodeKey(spec);
}

function pluginFor(
  registry: NodeRegistry,
  slug: string,
): NodeRegistry["plugins"][number] {
  const plugin = registry.plugins.find((candidate) => candidate.slug === slug);
  if (!plugin) {
    throw new Error(`Node registry is missing owner plugin "${slug}".`);
  }
  return plugin;
}

function shapesAreCompatible(source: Port, target: Port): boolean {
  const acceptedShapes = acceptedPortShapes(target);
  return (
    acceptedShapes.includes(source.shape) ||
    (!portHasInstancePlugs(target) &&
      source.shape === "many" &&
      acceptedShapes.includes("one"))
  );
}

function routeTitle(route: ConnectionRoute): string | null {
  const conversionTitle = route.conversionPath
    .map((conversion) => conversion.title)
    .join(" → ");
  if (route.kind === "projection") return route.projection.title;
  if (route.kind === "conversion") return conversionTitle;
  if (route.kind === "projection-conversion") {
    return `${route.projection.title} → ${conversionTitle}`;
  }
  return null;
}

function compatiblePortPairs(
  sourceSpec: NodeSpec,
  targetSpec: NodeSpec,
  registry: NodeRegistry,
): CompatiblePortPair[] {
  const pairs: CompatiblePortPair[] = [];
  for (const source of sourceSpec.outputs) {
    for (const target of targetSpec.inputs) {
      if (!shapesAreCompatible(source, target)) continue;
      const routes = connectionRoutesFor(
        {
          sourceHandle: encodeHandleId(portMetaForPort(source)),
          targetHandle: encodeHandleId(portMetaForPort(target)),
        },
        registry.artifact_types,
        registry.artifact_conversions,
      );
      const route = routes[0];
      if (!route) continue;
      pairs.push({ source, target, route, routeCount: routes.length });
    }
  }
  return pairs;
}

function compatibleNodesForPort(
  selected: NodeSpec,
  port: Port,
  registry: NodeRegistry,
): CompatibleNode[] {
  const selectedKey = nodeKey(selected);
  const matches = registry.nodes.flatMap((candidate) => {
    if (nodeKey(candidate) === selectedKey) return [];
    const pairs =
      port.direction === "input"
        ? compatiblePortPairs(candidate, selected, registry).filter(
            (pair) => pair.target.name === port.name,
          )
        : compatiblePortPairs(selected, candidate, registry).filter(
            (pair) => pair.source.name === port.name,
          );
    const first = pairs[0];
    if (!first) return [];

    const transport = portHasInstancePlugs(first.target)
      ? "direct to ordered input"
      : acceptedPortShapes(first.target).includes(first.source.shape)
        ? "direct"
        : "map each item";
    const transformation = routeTitle(first.route);
    const routeSummary = [
      `${first.source.title ?? first.source.name} → ${first.target.title ?? first.target.name}`,
      transport,
      transformation,
    ]
      .filter((value): value is string => Boolean(value))
      .join(" · ");
    const totalRouteCount = pairs.reduce(
      (count, pair) => count + pair.routeCount,
      0,
    );
    return [
      {
        spec: candidate,
        routeSummary,
        additionalRouteCount: totalRouteCount - 1,
      },
    ];
  });
  const order = new Map(
    sortCatalogNodes(matches.map((match) => match.spec)).map((spec, index) => [
      nodeKey(spec),
      index,
    ]),
  );
  return matches.sort(
    (left, right) =>
      (order.get(nodeKey(left.spec)) ?? 0) -
      (order.get(nodeKey(right.spec)) ?? 0),
  );
}

function fieldConstraintLabel(field: SchemaField): string {
  const constraints = [field.required ? "required" : "optional"];
  if (field.type === "string-list") {
    if (field.minItems !== undefined && field.maxItems !== undefined) {
      constraints.push(`${field.minItems}–${field.maxItems} items`);
    } else if (field.minItems !== undefined) {
      constraints.push(`min ${field.minItems} items`);
    } else if (field.maxItems !== undefined) {
      constraints.push(`max ${field.maxItems} items`);
    }
    if (
      field.itemMinLength !== undefined &&
      field.itemMaxLength !== undefined
    ) {
      constraints.push(
        `${field.itemMinLength}–${field.itemMaxLength} characters per item`,
      );
    } else if (field.itemMinLength !== undefined) {
      constraints.push(`min ${field.itemMinLength} characters per item`);
    } else if (field.itemMaxLength !== undefined) {
      constraints.push(`max ${field.itemMaxLength} characters per item`);
    }
    return constraints.join(" · ");
  }
  if (field.minimum !== undefined && field.maximum !== undefined) {
    constraints.push(`${field.minimum}–${field.maximum}`);
  } else if (field.minimum !== undefined) {
    constraints.push(`min ${field.minimum}`);
  } else if (field.maximum !== undefined) {
    constraints.push(`max ${field.maximum}`);
  }
  if (field.minLength !== undefined && field.maxLength !== undefined) {
    constraints.push(`${field.minLength}–${field.maxLength} characters`);
  } else if (field.minLength !== undefined) {
    constraints.push(`min ${field.minLength} characters`);
  } else if (field.maxLength !== undefined) {
    constraints.push(`max ${field.maxLength} characters`);
  }
  return constraints.join(" · ");
}

function SourceFilterIcon({ filter }: { filter: CatalogFilter }) {
  if (filter.id === "all") return <LayoutGrid size={14} />;
  if (filter.id === "workspace-library") return <LibraryBig size={14} />;
  return <Package size={14} />;
}

const s = stylex.create({
  header: {
    display: "grid",
    gridTemplateColumns: {
      default: "132px minmax(0, 1fr)",
      "@media (max-width: 720px)": "1fr",
    },
    alignItems: "center",
    gap: "12px",
    padding: {
      default: "12px 48px 12px 16px",
      "@media (max-width: 720px)": "12px 48px 12px 12px",
    },
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorBorder,
  },
  heading: { minWidth: 0 },
  titleRow: { display: "flex", alignItems: "center", gap: "9px" },
  title: {
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeLg,
    fontWeight: 760,
  },
  description: {
    marginTop: "3px",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeSm,
  },
  searchWrap: { position: "relative" },
  searchIcon: {
    position: "absolute",
    top: "11px",
    left: "12px",
    color: tokens.colorSubtle,
    pointerEvents: "none",
  },
  search: {
    width: "100%",
    height: {
      default: "40px",
      "@media (max-width: 720px)": "44px",
    },
    padding: "0 12px 0 34px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: {
      default: tokens.colorBorderStrong,
      ":focus": tokens.colorAccent,
    },
    borderRadius: tokens.radiusSm,
    outlineColor: tokens.colorAccent,
    outlineStyle: "solid",
    outlineOffset: "2px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
    backgroundColor: tokens.colorSurfaceSunken,
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
  },
  layout: {
    minHeight: 0,
    flex: 1,
    display: "grid",
    overflow: "hidden",
    overscrollBehaviorY: "contain",
    paddingBottom: {
      default: 0,
      "@media (max-width: 720px)": "env(safe-area-inset-bottom, 0px)",
    },
    gridTemplateColumns: {
      default: "148px minmax(0, 1fr) 360px",
      "@media (max-width: 1024px)": "minmax(0, 1fr) minmax(0, 1fr)",
      "@media (max-width: 720px)": "1fr",
    },
    gridTemplateRows: {
      default: "minmax(0, 1fr)",
      "@media (max-width: 1024px)": "auto minmax(0, 1fr)",
    },
    gridTemplateAreas: {
      default: '"filters nodes inspector"',
      "@media (max-width: 1024px)": '"filters filters" "nodes inspector"',
      "@media (max-width: 720px)": '"filters" "nodes"',
    },
  },
  detailLayout: {
    gridTemplateColumns: "minmax(0, 1fr)",
    gridTemplateRows: "minmax(0, 1fr)",
    gridTemplateAreas: '"inspector"',
  },
  hidden: { display: "none" },
  compactFilters: {
    display: { default: "none", "@media (max-width: 1024px)": "flex" },
    alignItems: "center",
    gap: "8px",
  },
  sourceRail: {
    display: { default: "block", "@media (max-width: 1024px)": "none" },
  },
  filterButton: {
    minHeight: "44px",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "6px",
    flexShrink: 0,
    paddingInline: "10px",
    border: `1px solid ${tokens.colorBorderStrong}`,
    borderRadius: tokens.radiusSm,
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    cursor: "pointer",
  },
  refinementsCollapsed: {
    display: { default: "grid", "@media (max-width: 1024px)": "none" },
  },
  backButton: {
    minHeight: "44px",
    display: "inline-flex",
    alignItems: "center",
    alignSelf: "flex-start",
    flexShrink: 0,
    gap: "6px",
    paddingInline: "12px",
    borderWidth: 0,
    backgroundColor: "transparent",
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    cursor: "pointer",
  },
  originBadge: {
    minHeight: "17px",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
    paddingInline: "5px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorderStrong,
    borderRadius: "99px",
    backgroundColor: tokens.colorSurfaceSunken,
    color: tokens.colorMuted,
    fontSize: "8px",
    fontWeight: 840,
    letterSpacing: "0.06em",
    lineHeight: 1,
    textTransform: "uppercase",
    whiteSpace: "nowrap",
  },
  filterPane: {
    gridArea: "filters",
    minWidth: 0,
    minHeight: 0,
    display: "flex",
    flexDirection: "column",
    padding: {
      default: "12px 8px",
      "@media (max-width: 1024px)": "6px 12px",
    },
    borderRightWidth: {
      default: 1,
      "@media (max-width: 1024px)": 0,
    },
    borderRightStyle: "solid",
    borderRightColor: tokens.colorBorder,
    borderBottomWidth: {
      default: 0,
      "@media (max-width: 1024px)": 1,
    },
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorBorder,
    overflowY: "auto",
  },
  filterHeading: {
    paddingInline: "10px",
    marginBottom: {
      default: "10px",
      "@media (max-width: 720px)": 0,
    },
    flexShrink: 0,
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeXs,
    fontWeight: 730,
  },
  filterLibrary: {
    marginTop: {
      default: "12px",
      "@media (max-width: 720px)": 0,
    },
    paddingTop: {
      default: "12px",
      "@media (max-width: 720px)": 0,
    },
    borderTopWidth: {
      default: 1,
      "@media (max-width: 720px)": 0,
    },
    borderTopStyle: "solid",
    borderTopColor: tokens.colorBorder,
  },
  refinementSection: {
    marginTop: {
      default: "12px",
      "@media (max-width: 720px)": 0,
    },
    paddingTop: {
      default: "12px",
      "@media (max-width: 720px)": 0,
    },
    borderTopWidth: {
      default: 1,
      "@media (max-width: 720px)": 0,
    },
    borderTopStyle: "solid",
    borderTopColor: tokens.colorBorder,
    display: "grid",
    gap: "10px",
    paddingInline: "10px",
  },
  refinementField: {
    display: "grid",
    gap: "4px",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    fontWeight: 730,
  },
  refinementSelect: {
    width: "100%",
    minHeight: { default: "32px", "@media (max-width: 1024px)": "44px" },
    padding: "0 8px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorderStrong,
    borderRadius: tokens.radiusSm,
    backgroundColor: tokens.colorSurfaceSunken,
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    cursor: "pointer",
    outlineColor: tokens.colorAccent,
    outlineStyle: "solid",
    outlineOffset: "2px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
  },
  refinementCheck: {
    display: "flex",
    alignItems: "center",
    gap: "7px",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    fontWeight: 640,
    cursor: "pointer",
    minHeight: { default: "24px", "@media (max-width: 1024px)": "44px" },
  },
  nodePane: {
    gridArea: "nodes",
    minWidth: 0,
    minHeight: 0,
    display: "flex",
    flexDirection: "column",
    borderRightWidth: {
      default: 1,
      "@media (max-width: 720px)": 0,
    },
    borderRightStyle: "solid",
    borderRightColor: tokens.colorBorder,
  },
  nodePaneHeader: {
    display: "grid",
    padding: "10px 14px",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorBorder,
  },
  nodePaneTitle: {
    overflow: "hidden",
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeSm,
    fontWeight: 730,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  resultCount: {
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    whiteSpace: "nowrap",
  },
  resultHeading: {
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    justifyContent: "flex-start",
    gap: "12px",
  },
  categoryToolbar: {
    display: {
      default: "grid",
      "@media (max-width: 720px)": "flex",
    },
    flexDirection: "row",
    width: {
      default: "auto",
      "@media (max-width: 720px)": "max-content",
    },
    gap: "2px",
  },
  categoryButton: {
    width: {
      default: "100%",
      "@media (max-width: 720px)": "auto",
    },
    minHeight: {
      default: "36px",
      "@media (max-width: 720px)": "44px",
    },
    display: "flex",
    alignItems: "center",
    gap: "10px",
    paddingInline: "10px",
    borderWidth: 0,
    borderRadius: tokens.radiusSm,
    outlineColor: tokens.colorAccent,
    outlineStyle: "solid",
    outlineOffset: "1px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: tokens.colorSubtle,
    cursor: "pointer",
    fontSize: tokens.fontSizeSm,
    fontWeight: 560,
    textAlign: "left",
    whiteSpace: "nowrap",
  },
  categoryButtonActive: {
    backgroundColor: tokens.colorSurfaceRaised,
    color: tokens.colorTextEmphasis,
  },
  compatibilityBanner: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
    padding: "7px 12px",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
    backgroundColor: tokens.colorSurfaceMuted,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
  },
  nodeList: {
    minHeight: 0,
    flex: 1,
    overflowY: "auto",
    display: "flex",
    flexDirection: "column",
    gap: "2px",
    padding: "6px",
  },
  nodeRow: {
    width: "100%",
    minHeight: "56px",
    flexShrink: 0,
    display: "flex",
    alignItems: "center",
    padding: "9px 10px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: {
      default: "transparent",
      ":hover": tokens.colorBorderStrong,
    },
    borderRadius: "8px",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: tokens.colorText,
    cursor: "pointer",
    fontFamily: "inherit",
    outlineColor: tokens.colorAccent,
    outlineStyle: "solid",
    outlineOffset: "-3px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
    textAlign: "left",
    transitionProperty: "background-color, border-color",
    transitionDuration: "120ms",
  },
  nodeRowActive: {
    borderColor: tokens.colorAccent,
    backgroundColor: tokens.colorAccentSoft,
  },
  nodeCopy: { minWidth: 0, display: "grid", gap: "3px" },
  nodeTitleRow: {
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    gap: "6px",
  },
  nodeTitle: {
    minWidth: 0,
    overflow: "hidden",
    fontSize: tokens.fontSizeSm,
    fontWeight: 730,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  nodeDescription: {
    display: "-webkit-box",
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.4,
    WebkitBoxOrient: "vertical",
    WebkitLineClamp: 1,
  },
  technicalToggle: {
    minHeight: { default: "28px", "@media (max-width: 720px)": "44px" },
    alignSelf: "flex-start",
    paddingInline: "0",
    borderWidth: 0,
    backgroundColor: "transparent",
    color: tokens.colorMuted,
    cursor: "pointer",
    outlineColor: tokens.colorAccent,
    outlineStyle: "solid",
    outlineOffset: "2px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
    fontSize: tokens.fontSizeXs,
    fontWeight: 680,
    textDecorationLine: "underline",
    textUnderlineOffset: "2px",
  },
  empty: {
    minHeight: "160px",
    display: "grid",
    placeItems: "center",
    alignContent: "center",
    gap: "10px",
    padding: "24px",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.5,
    textAlign: "center",
  },
  moduleDiagnostics: {
    display: "grid",
    gap: "8px",
    padding: "12px 14px 16px",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorBorder,
    backgroundColor: tokens.colorSurfaceMuted,
  },
  moduleDiagnosticsNote: {
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
  openGraphButton: {
    flexShrink: 0,
    minHeight: "24px",
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
    paddingInline: "7px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorderStrong,
    borderRadius: "5px",
    backgroundColor: {
      default: tokens.colorSurface,
      ":hover": tokens.colorHover,
    },
    color: tokens.colorMuted,
    cursor: "pointer",
    outlineColor: tokens.colorAccent,
    outlineStyle: "solid",
    outlineOffset: "2px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
    fontSize: "10px",
    fontWeight: 700,
  },
  inspectorOpenGraph: {
    marginTop: "8px",
    alignSelf: "flex-start",
  },
  resetButton: {
    minHeight: "29px",
    paddingInline: "10px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorderStrong,
    borderRadius: "5px",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: tokens.colorMuted,
    cursor: "pointer",
    outlineColor: tokens.colorAccent,
    outlineStyle: "solid",
    outlineOffset: "2px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
    fontSize: tokens.fontSizeXs,
    fontWeight: 700,
  },
  inspector: {
    gridArea: "inspector",
    minWidth: 0,
    minHeight: 0,
    display: "flex",
    flexDirection: "column",
    backgroundColor: tokens.colorSurface,
  },
  inspectorBody: {
    minHeight: 0,
    flex: 1,
    display: "flex",
    flexDirection: "column",
  },
  previewStage: {
    flexShrink: 0,
    maxHeight: "36%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "14px 12px",
    overflow: "auto",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorBorder,
  },
  inspectorScroll: { minHeight: 0, flex: 1, overflowY: "auto" },
  inspectorHeader: {
    padding: "14px",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorBorder,
  },
  inspectorProvenance: {
    display: "flex",
    alignItems: "center",
    gap: "7px",
  },
  eyebrow: {
    color: tokens.colorAccent,
    fontSize: "10px",
    fontWeight: 820,
    letterSpacing: "0.11em",
    textTransform: "uppercase",
  },
  inspectorTitle: {
    marginTop: 0,
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeLg,
    fontWeight: 760,
    letterSpacing: "-0.015em",
    lineHeight: 1.2,
  },
  operatorId: {
    marginTop: "5px",
    color: tokens.colorSubtle,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: tokens.fontSizeXs,
  },
  inspectorDescription: {
    maxWidth: "68ch",
    marginTop: "10px",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.55,
  },
  inspectorSummary: {
    display: "grid",
    gap: "8px",
    marginTop: "12px",
  },
  inspectorStatement: {
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.5,
  },
  inspectorStatementStrong: {
    color: tokens.colorTextEmphasis,
    fontWeight: 680,
  },
  inspectorConfiguration: {
    display: "grid",
    gap: "3px",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.5,
  },
  inspectorConfigurationLabel: {
    color: tokens.colorTextEmphasis,
    fontWeight: 680,
  },
  section: {
    padding: "18px 22px",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorBorder,
  },
  sectionTitleRow: {
    display: "flex",
    alignItems: "center",
    gap: "7px",
    marginBottom: "12px",
  },
  sectionIcon: { color: tokens.colorSubtle },
  sectionTitle: {
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeSm,
    fontWeight: 750,
  },
  worksWithHeader: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    minWidth: 0,
    marginBottom: "12px",
  },
  worksWithTitle: {
    flexShrink: 0,
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeSm,
    fontWeight: 750,
  },
  worksWithPort: {
    minWidth: 0,
    flex: 1,
    overflow: "hidden",
    color: tokens.colorTextEmphasis,
    fontFamily: "inherit",
    fontSize: tokens.fontSizeSm,
    fontWeight: 650,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  worksWithPortSelect: {
    padding: "1px 0",
    borderWidth: 0,
    borderBottomWidth: 1,
    borderStyle: "solid",
    borderBottomColor: tokens.colorBorderStrong,
    borderRadius: 0,
    backgroundColor: "transparent",
    cursor: "pointer",
    outlineColor: tokens.colorAccent,
    outlineStyle: "solid",
    outlineOffset: "2px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
  },
  compatibilityHeading: {
    marginBottom: "5px",
    color: tokens.colorSubtle,
    fontSize: "10px",
    fontWeight: 800,
    letterSpacing: "0.09em",
    textTransform: "uppercase",
  },
  compatibilityList: { display: "grid" },
  compatibilityItem: {
    width: "100%",
    display: "grid",
    gap: "2px",
    padding: "8px 0",
    borderWidth: 0,
    borderBottomWidth: 1,
    borderStyle: "solid",
    borderBottomColor: tokens.colorDivider,
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: tokens.colorText,
    cursor: "pointer",
    fontFamily: "inherit",
    outlineColor: tokens.colorAccent,
    outlineStyle: "solid",
    outlineOffset: "2px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
    textAlign: "left",
  },
  compatibilityName: {
    overflow: "hidden",
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    fontWeight: 680,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  compatibilityMeta: {
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontSize: "10px",
    lineHeight: 1.4,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  compatibilityEmpty: {
    padding: "8px 0",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
  portGrid: {
    display: "grid",
    gridTemplateColumns: {
      default: "repeat(2, minmax(0, 1fr))",
      "@media (max-width: 900px)": "1fr",
    },
    gap: "18px",
  },
  portColumnHeading: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
    marginBottom: "5px",
    color: tokens.colorSubtle,
    fontSize: "10px",
    fontWeight: 800,
    letterSpacing: "0.09em",
    textTransform: "uppercase",
  },
  portList: { display: "grid" },
  portRow: {
    display: "grid",
    gridTemplateColumns: "7px minmax(0, 1fr)",
    gap: "9px",
    padding: "10px 0",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
  },
  portDot: {
    width: "7px",
    height: "7px",
    marginTop: "5px",
    borderRadius: "99px",
  },
  portCopy: { minWidth: 0 },
  portTitle: {
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    fontWeight: 690,
  },
  portContract: {
    marginTop: "2px",
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "10px",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  portRules: {
    marginTop: "3px",
    color: tokens.colorSubtle,
    fontSize: "10px",
  },
  portDescription: {
    marginTop: "5px",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
  fieldList: { display: "grid" },
  fieldRow: {
    display: "grid",
    gridTemplateColumns: {
      default: "minmax(130px, 0.7fr) minmax(0, 1.3fr)",
      "@media (max-width: 900px)": "1fr",
    },
    gap: "8px 18px",
    padding: "11px 0",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
  },
  fieldIdentity: { minWidth: 0 },
  fieldTitle: {
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    fontWeight: 690,
  },
  fieldName: {
    marginTop: "2px",
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "10px",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  fieldDetails: { minWidth: 0 },
  fieldMeta: { color: tokens.colorSubtle, fontSize: "10px" },
  fieldDescription: {
    marginTop: "4px",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
  fieldChoices: {
    marginTop: "4px",
    overflowWrap: "anywhere",
    color: tokens.colorSubtle,
    fontSize: "10px",
  },
  inspectorFooter: {
    minHeight: "62px",
    display: "grid",
    padding: "10px 18px",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorBorder,
    backgroundColor: tokens.colorSurfaceRaised,
  },
  visuallyHidden: {
    position: "absolute",
    width: "1px",
    height: "1px",
    padding: 0,
    margin: "-1px",
    overflow: "hidden",
    clip: "rect(0, 0, 0, 0)",
    whiteSpace: "nowrap",
    borderWidth: 0,
  },
  addButton: {
    width: "100%",
    minHeight: "44px",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "7px",
    paddingInline: "12px",
    overflow: "hidden",
    borderWidth: 0,
    borderRadius: tokens.radiusSm,
    backgroundColor: {
      default: tokens.colorAccent,
      ":hover": tokens.colorAccentHover,
    },
    color: tokens.colorOnAccent,
    cursor: "pointer",
    outlineColor: tokens.colorAccent,
    outlineStyle: "solid",
    outlineOffset: "2px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
    fontSize: tokens.fontSizeSm,
    fontWeight: 750,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  addButtonDisabled: {
    backgroundColor: tokens.colorAccentDisabled,
    color: tokens.colorTextDisabled,
    cursor: "not-allowed",
  },
});

interface CompatibilityListProps {
  title?: string;
  matches: readonly CompatibleNode[];
  registry: NodeRegistry;
  emptyMessage: string;
  onInspect: (spec: NodeSpec) => void;
}

function CompatibilityList({
  title,
  matches,
  registry,
  emptyMessage,
  onInspect,
}: CompatibilityListProps) {
  return (
    <div>
      {title ? (
        <h4 {...stylex.props(s.compatibilityHeading)}>{title}</h4>
      ) : null}
      {matches.length ? (
        <div {...stylex.props(s.compatibilityList)}>
          {matches.map((match) => (
            <button
              key={nodeKey(match.spec)}
              type="button"
              aria-label={`Inspect ${match.spec.title}`}
              {...stylex.props(s.compatibilityItem)}
              onClick={() => onInspect(match.spec)}
            >
              <span {...stylex.props(s.compatibilityName)}>
                {match.spec.title}
              </span>
              <span {...stylex.props(s.compatibilityMeta)}>
                {pluginFor(registry, match.spec.plugin_slug).title} ·{" "}
                {match.routeSummary}
                {match.additionalRouteCount > 0
                  ? ` · +${match.additionalRouteCount} route${match.additionalRouteCount === 1 ? "" : "s"}`
                  : ""}
              </span>
            </button>
          ))}
        </div>
      ) : (
        <p {...stylex.props(s.compatibilityEmpty)}>{emptyMessage}</p>
      )}
    </div>
  );
}

interface WorksWithSectionProps {
  ports: readonly Port[];
  activePort: Port;
  matches: readonly CompatibleNode[];
  registry: NodeRegistry;
  onSelectPort: (port: Port) => void;
  onInspect: (spec: NodeSpec) => void;
}

function portScopeLabel(port: Port): string {
  const title = port.title ?? port.name;
  return `${title} ${port.direction === "input" ? "input" : "output"}`;
}

function WorksWithSection({
  ports,
  activePort,
  matches,
  registry,
  onSelectPort,
  onInspect,
}: WorksWithSectionProps) {
  const receiving = activePort.direction === "input";
  return (
    <section {...stylex.props(s.section)}>
      <div {...stylex.props(s.worksWithHeader)}>
        <Cable size={13} {...stylex.props(s.sectionIcon)} />
        <h3 {...stylex.props(s.worksWithTitle)}>Works with:</h3>
        {ports.length > 1 ? (
          <select
            aria-label="Works with port"
            value={portKey(activePort)}
            {...stylex.props(s.worksWithPort, s.worksWithPortSelect)}
            onChange={(event) => {
              const next = ports.find(
                (port) => portKey(port) === event.currentTarget.value,
              );
              if (next) onSelectPort(next);
            }}
          >
            {ports.map((port) => (
              <option key={portKey(port)} value={portKey(port)}>
                {portScopeLabel(port)}
              </option>
            ))}
          </select>
        ) : (
          <span {...stylex.props(s.worksWithPort)}>
            {portScopeLabel(activePort)}
          </span>
        )}
      </div>
      <CompatibilityList
        matches={matches}
        registry={registry}
        emptyMessage={
          receiving
            ? "No registered node currently provides a compatible output."
            : "No registered node currently accepts this output."
        }
        onInspect={onInspect}
      />
    </section>
  );
}

interface PortListProps {
  direction: "input" | "output";
  ports: readonly Port[];
  registry: NodeRegistry;
}

function PortList({ direction, ports, registry }: PortListProps) {
  const input = direction === "input";
  return (
    <div>
      <h4 {...stylex.props(s.portColumnHeading)}>
        {input ? <ArrowDownToLine size={12} /> : <ArrowUpFromLine size={12} />}
        {input ? "Inputs" : "Outputs"} · {ports.length}
      </h4>
      {ports.length ? (
        <div {...stylex.props(s.portList)}>
          {ports.map((port) => {
            const artifactType = portArtifactType(port);
            const variable = portArtifactTypeVariable(port);
            const contract = artifactType
              ? `${artifactType.id}@${artifactType.schema_version}`
              : (variable ?? "generic");
            const acceptedShapeRule = acceptedPortShapes(port)
              .map((shape) => (shape === "many" ? "sequence" : "single value"))
              .join(" or ");
            const rules = [
              port.required ? "required" : "optional",
              acceptedShapeRule,
              portHasInstancePlugs(port)
                ? "ordered input plugs"
                : port.variadic
                  ? "multiple connections"
                  : null,
            ]
              .filter(Boolean)
              .join(" · ");
            return (
              <div
                key={`${direction}-${port.name}`}
                {...stylex.props(s.portRow)}
              >
                <span
                  aria-hidden="true"
                  {...stylex.props(s.portDot)}
                  style={{
                    backgroundColor: artifactType
                      ? artifactTypeColor(artifactType.id, tokens.colorAccent)
                      : tokens.colorAccent,
                  }}
                />
                <div {...stylex.props(s.portCopy)}>
                  <div {...stylex.props(s.portTitle)}>
                    {port.title ?? port.name}
                  </div>
                  <div {...stylex.props(s.portContract)}>
                    {artifactTitleFor(registry, port)} · {contract}
                  </div>
                  <div {...stylex.props(s.portRules)}>{rules}</div>
                  {port.description ? (
                    <p {...stylex.props(s.portDescription)}>
                      {port.description}
                    </p>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <p {...stylex.props(s.compatibilityEmpty)}>
          {input
            ? "No inputs. This node can start a workflow."
            : "No outputs. This node finishes a branch."}
        </p>
      )}
    </div>
  );
}

export function NodeSelector({
  open,
  registry,
  activeGraphId,
  compatibility,
  errorMessage = null,
  loading = false,
  canInsert = true,
  insertDisabledReason = "You do not have permission to edit this graph.",
  returnFocusRef: providedReturnFocusRef,
  onOpenChange,
  onAddNode,
  onRetry,
  onOpenGraph,
  onOpenWorkspaceLibrary,
}: NodeSelectorProps) {
  const mobileNodeSelector = useMediaQuery(MOBILE_NODE_SELECTOR_QUERY);
  const finePointer = useMediaQuery(FINE_POINTER_QUERY);
  const [query, setQuery] = React.useState("");
  const [activeSourceId, setActiveSourceId] = React.useState<string>("all");
  const [artifactFilterId, setArtifactFilterId] = React.useState<string | null>(
    null,
  );
  const [inputNodesOnly, setInputNodesOnly] = React.useState(false);
  const [selectedNodeKey, setSelectedNodeKey] = React.useState<string | null>(
    null,
  );
  const [selectedRelease, setSelectedRelease] = React.useState<{
    moduleKey: string;
    releaseKey: string;
  } | null>(null);
  const [technicalDetailsOpen, setTechnicalDetailsOpen] = React.useState(false);
  const [detailsOpen, setDetailsOpen] = React.useState(false);
  const [filtersOpen, setFiltersOpen] = React.useState(false);
  const [compatibilityPortSelection, setCompatibilityPortSelection] =
    React.useState<{ specKey: string; portKey: string } | null>(null);
  const resultRefs = React.useRef(new Map<string, HTMLButtonElement>());
  const filterRefs = React.useRef(new Map<string, HTMLButtonElement>());
  const dialogRef = React.useRef<HTMLDivElement>(null);
  const searchRef = React.useRef<HTMLInputElement>(null);
  const backRef = React.useRef<HTMLButtonElement>(null);
  const pendingResultFocusKey = React.useRef<string | null>(null);
  const wasOpen = React.useRef(false);

  const catalogFilters = React.useMemo(
    () => buildCatalogFilters(registry),
    [registry],
  );
  const sourceFilters = React.useMemo(
    () => buildSourceFilters(registry),
    [registry],
  );
  const artifactOptions = React.useMemo(
    () => catalogFilters.filter((filter) => filter.kind === "artifact"),
    [catalogFilters],
  );
  const activeSourceFilter =
    sourceFilters.find((filter) => filter.id === activeSourceId) ??
    sourceFilters[0]!;
  const activeArtifactFilter =
    artifactOptions.find((filter) => filter.id === artifactFilterId) ?? null;
  const refinementFilters = React.useMemo(
    () => [
      ...(activeArtifactFilter ? [activeArtifactFilter] : []),
      ...(inputNodesOnly ? [INPUT_NODES_FILTER] : []),
    ],
    [activeArtifactFilter, inputNodesOnly],
  );

  const catalogNodes = React.useMemo(
    () => catalogNodeSpecs(registry, activeGraphId),
    [activeGraphId, registry],
  );
  const compatibleCatalogNodes = React.useMemo(
    () =>
      compatibility
        ? nodesCompatibleWithPort(catalogNodes, compatibility, registry)
        : catalogNodes,
    [catalogNodes, compatibility, registry],
  );
  const catalogRegistry = React.useMemo(
    () => ({ ...registry, nodes: catalogNodes }),
    [catalogNodes, registry],
  );
  const showingModules = activeSourceId === "workspace-library";
  const activeEditingModule = React.useMemo(
    () =>
      activeGraphId
        ? (registry.nodes.find(
            (spec) =>
              spec.module_graph_id === activeGraphId &&
              spec.catalog_visible !== false,
          ) ?? null)
        : null,
    [activeGraphId, registry.nodes],
  );

  React.useEffect(() => {
    if (open && !wasOpen.current) {
      setQuery("");
      setActiveSourceId("all");
      setArtifactFilterId(null);
      setInputNodesOnly(false);
      setSelectedNodeKey(null);
      setSelectedRelease(null);
      setTechnicalDetailsOpen(false);
      setDetailsOpen(false);
      setFiltersOpen(false);
      setCompatibilityPortSelection(null);
    }
    wasOpen.current = open;
  }, [open]);

  const normalizedQuery = query.trim().toLowerCase();
  const filteredNodes = React.useMemo(() => {
    if (loading || errorMessage) return [];
    return filterAndSearchCatalogNodes(
      compatibleCatalogNodes,
      [activeSourceFilter, ...refinementFilters],
      query,
      registry,
    );
  }, [
    activeSourceFilter,
    compatibleCatalogNodes,
    errorMessage,
    loading,
    query,
    refinementFilters,
    registry,
  ]);
  const listedSpec =
    filteredNodes.find((spec) => nodeKey(spec) === selectedNodeKey) ??
    filteredNodes[0] ??
    null;
  const moduleReleases = React.useMemo(
    () =>
      listedSpec?.plugin_slug === MODULE_PLUGIN_SLUG
        ? moduleReleaseSpecs(
            registry,
            listedSpec.module_id,
            listedSpec.module_graph_id,
          )
        : [],
    [listedSpec, registry],
  );
  const selectedSpec = React.useMemo(() => {
    if (!listedSpec) return null;
    if (listedSpec.plugin_slug !== MODULE_PLUGIN_SLUG) return listedSpec;
    const moduleKey = listedSpec.module_id ?? listedSpec.module_graph_id;
    const selectedReleaseKey =
      moduleKey && selectedRelease?.moduleKey === moduleKey
        ? selectedRelease.releaseKey
        : null;
    return (
      moduleReleases.find((spec) => nodeKey(spec) === selectedReleaseKey) ??
      moduleReleases.find((spec) => spec.catalog_visible !== false) ??
      moduleReleases[0] ??
      listedSpec
    );
  }, [listedSpec, moduleReleases, selectedRelease]);
  const selectedSpecKey = selectedSpec ? nodeKey(selectedSpec) : null;
  const selectedFields = selectedSpec
    ? schemaFields(selectedSpec.config_schema)
    : [];
  const compatibilityPorts = selectedSpec
    ? [...selectedSpec.inputs, ...selectedSpec.outputs]
    : [];
  const compatibilityPortKey =
    compatibilityPortSelection?.specKey === selectedSpecKey
      ? compatibilityPortSelection.portKey
      : null;
  const activeCompatibilityPort =
    compatibilityPorts.find((port) => portKey(port) === compatibilityPortKey) ??
    compatibilityPorts[0] ??
    null;
  const portMatches = React.useMemo(
    () =>
      selectedSpec && activeCompatibilityPort
        ? compatibleNodesForPort(
            selectedSpec,
            activeCompatibilityPort,
            catalogRegistry,
          )
        : [],
    [activeCompatibilityPort, catalogRegistry, selectedSpec],
  );
  const selectedPlugin = selectedSpec
    ? pluginFor(registry, selectedSpec.plugin_slug)
    : null;
  const selectedPrimaryInput = selectedSpec?.inputs[0] ?? null;
  const selectedPrimaryOutput = selectedSpec?.outputs[0] ?? null;
  const selectedPrimaryInputArtifact = selectedPrimaryInput
    ? portArtifactType(selectedPrimaryInput)
    : null;
  const selectedPrimaryOutputArtifact = selectedPrimaryOutput
    ? portArtifactType(selectedPrimaryOutput)
    : null;
  const resultsTitle =
    activeSourceFilter.id === "all"
      ? "All nodes"
      : activeSourceFilter.id === "workspace-library"
        ? "Workspace library"
        : `${activeSourceFilter.title} nodes`;
  const isModuleSelection = selectedPlugin?.entry_kind === "module";
  const isDeprecatedModule = selectedSpec?.publication_state === "deprecated";
  const selectionCanInsert = canInsert && selectedSpec?.runnable !== false;
  const pluginUnavailableReason =
    selectedSpec?.non_runnable_detail ??
    "This Plugin release is catalog-only until its isolated runtime is available.";
  const selectionDisabledReason = !canInsert
    ? insertDisabledReason
    : pluginUnavailableReason;
  const activeResultId = listedSpec
    ? `node-selector-result-${nodeKey(listedSpec)}`
    : undefined;
  const compatibilityPortTitle = compatibility
    ? (compatibility.port.title ?? compatibility.port.name)
    : null;
  const resultStatus = loading
    ? "Loading nodes…"
    : errorMessage
      ? "Nodes could not be loaded."
      : filteredNodes.length === 0
        ? "No nodes found."
        : `${filteredNodes.length} ${filteredNodes.length === 1 ? "node" : "nodes"}.`;

  const selectSource = (id: string) => {
    setActiveSourceId(id);
    setSelectedNodeKey(null);
    setTechnicalDetailsOpen(false);
    setCompatibilityPortSelection(null);
  };

  const focusSourceAt = (index: number) => {
    const boundedIndex = Math.max(0, Math.min(index, sourceFilters.length - 1));
    const nextFilter = sourceFilters[boundedIndex];
    if (!nextFilter) return;
    selectSource(nextFilter.id);
    filterRefs.current.get(nextFilter.id)?.focus();
  };

  const focusResultAt = (index: number) => {
    if (!filteredNodes.length) return;
    const boundedIndex = Math.max(0, Math.min(index, filteredNodes.length - 1));
    const nextSpec = filteredNodes[boundedIndex];
    if (!nextSpec) return;
    const key = nodeKey(nextSpec);
    setSelectedNodeKey(key);
    resultRefs.current.get(key)?.focus();
  };

  const insertNode = (spec: NodeSpec) => {
    if (!canInsert || spec.runnable === false) return;
    if (
      spec.publication_state === "deprecated" &&
      !window.confirm(
        `Insert deprecated Module “${spec.title}”? New inserts are discouraged. Existing pinned calls keep working.`,
      )
    ) {
      return;
    }
    onAddNode(spec);
  };

  const inspectCatalogNode = (spec: NodeSpec) => {
    const key = nodeKey(spec);
    pendingResultFocusKey.current = key;
    setQuery("");
    setActiveSourceId(
      spec.plugin_slug === MODULE_PLUGIN_SLUG
        ? "workspace-library"
        : sourceFilterId(spec.plugin_slug),
    );
    setArtifactFilterId(null);
    setInputNodesOnly(false);
    setSelectedNodeKey(key);
    setSelectedRelease(null);
    setTechnicalDetailsOpen(false);
    setCompatibilityPortSelection(null);
  };

  React.useEffect(() => {
    if (mobileNodeSelector && detailsOpen) {
      pendingResultFocusKey.current = null;
      backRef.current?.focus();
      return;
    }
    const key = pendingResultFocusKey.current;
    if (!key) return;
    pendingResultFocusKey.current = null;
    const option = resultRefs.current.get(key);
    option?.scrollIntoView?.({ block: "nearest" });
    option?.focus();
  }, [
    activeSourceId,
    artifactFilterId,
    inputNodesOnly,
    query,
    selectedNodeKey,
    mobileNodeSelector,
    detailsOpen,
  ]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        ref={dialogRef}
        size="catalog"
        aria-labelledby="node-selector-title"
        aria-describedby="node-selector-description"
        initialFocus={finePointer ? searchRef : dialogRef}
        finalFocus={providedReturnFocusRef}
      >
        <div {...stylex.props(s.header)}>
          <div {...stylex.props(s.heading)}>
            <div {...stylex.props(s.titleRow)}>
              <DialogTitle id="node-selector-title" {...stylex.props(s.title)}>
                Add node
              </DialogTitle>
            </div>
            <DialogDescription
              id="node-selector-description"
              {...stylex.props(s.visuallyHidden)}
            >
              Choose what to add to your workflow.
            </DialogDescription>
          </div>
          <div
            {...stylex.props(
              s.searchWrap,
              mobileNodeSelector && detailsOpen && s.hidden,
            )}
          >
            <Search size={14} {...stylex.props(s.searchIcon)} />
            <input
              ref={searchRef}
              aria-label="Search nodes"
              aria-autocomplete="list"
              aria-controls="node-selector-results"
              aria-activedescendant={activeResultId}
              value={query}
              placeholder="Search nodes…"
              {...stylex.props(s.search)}
              onChange={(event) => {
                setQuery(event.currentTarget.value);
                setSelectedNodeKey(null);
              }}
              onKeyDown={(event) => {
                if (event.key === "ArrowDown") {
                  event.preventDefault();
                  focusResultAt(0);
                } else if (event.key === "Enter") {
                  event.preventDefault();
                  if (selectedSpec) insertNode(selectedSpec);
                }
              }}
            />
          </div>
        </div>

        <div
          {...stylex.props(
            s.layout,
            mobileNodeSelector && detailsOpen && s.detailLayout,
          )}
        >
          <nav
            aria-label="Node filters"
            {...stylex.props(
              s.filterPane,
              mobileNodeSelector && detailsOpen && s.hidden,
            )}
          >
            <div {...stylex.props(s.compactFilters)}>
              <select
                aria-label="Node source"
                value={activeSourceId}
                {...stylex.props(s.refinementSelect)}
                onChange={(event) => selectSource(event.currentTarget.value)}
              >
                {sourceFilters.map((filter) => (
                  <option key={filter.id} value={filter.id}>
                    {filter.id === "all" ? "All sources" : filter.title}
                  </option>
                ))}
              </select>
              <button
                type="button"
                aria-expanded={filtersOpen}
                aria-controls="node-selector-refinements"
                {...stylex.props(s.filterButton)}
                onClick={() => setFiltersOpen((open) => !open)}
              >
                <Settings2 size={14} aria-hidden="true" />
                Filters
                {artifactFilterId || inputNodesOnly
                  ? ` (${Number(!!artifactFilterId) + Number(inputNodesOnly)})`
                  : ""}
              </button>
            </div>
            <div {...stylex.props(s.sourceRail)}>
              <h3 {...stylex.props(s.filterHeading)}>Source</h3>
              <div
                role="toolbar"
                aria-label="Node sources"
                aria-orientation={
                  mobileNodeSelector ? "horizontal" : "vertical"
                }
                {...stylex.props(s.categoryToolbar)}
              >
                {sourceFilters.map((filter, index) => {
                  const active = filter.id === activeSourceId;
                  const count = filterAndSearchCatalogNodes(
                    compatibleCatalogNodes,
                    [filter, ...refinementFilters],
                    "",
                    registry,
                  ).length;
                  const filterButton = (
                    <button
                      ref={(element) => {
                        if (element) filterRefs.current.set(filter.id, element);
                        else filterRefs.current.delete(filter.id);
                      }}
                      type="button"
                      tabIndex={active ? 0 : -1}
                      aria-label={`${filter.title}, ${count} ${count === 1 ? "node" : "nodes"}`}
                      aria-pressed={active}
                      {...stylex.props(
                        s.categoryButton,
                        active ? s.categoryButtonActive : null,
                      )}
                      onClick={() => selectSource(filter.id)}
                      onKeyDown={(event) => {
                        if (
                          event.key === "ArrowDown" ||
                          event.key === "ArrowRight"
                        ) {
                          event.preventDefault();
                          focusSourceAt(index + 1);
                        } else if (
                          event.key === "ArrowUp" ||
                          event.key === "ArrowLeft"
                        ) {
                          event.preventDefault();
                          focusSourceAt(index - 1);
                        } else if (event.key === "Home") {
                          event.preventDefault();
                          focusSourceAt(0);
                        } else if (event.key === "End") {
                          event.preventDefault();
                          focusSourceAt(sourceFilters.length - 1);
                        }
                      }}
                    >
                      <SourceFilterIcon filter={filter} />
                      {filter.title}
                    </button>
                  );
                  return filter.id === "workspace-library" ? (
                    <div key={filter.id} {...stylex.props(s.filterLibrary)}>
                      {filterButton}
                    </div>
                  ) : (
                    <React.Fragment key={filter.id}>
                      {filterButton}
                    </React.Fragment>
                  );
                })}
              </div>
            </div>
            <div
              id="node-selector-refinements"
              {...stylex.props(
                s.refinementSection,
                !filtersOpen && s.refinementsCollapsed,
              )}
            >
              <label {...stylex.props(s.refinementField)}>
                <span>Artifact</span>
                <select
                  aria-label="Artifact type"
                  value={artifactFilterId ?? ""}
                  {...stylex.props(s.refinementSelect)}
                  onChange={(event) => {
                    setArtifactFilterId(event.currentTarget.value || null);
                    setSelectedNodeKey(null);
                  }}
                >
                  <option value="">Any artifact</option>
                  {artifactOptions.map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.title}
                    </option>
                  ))}
                </select>
              </label>
              <label {...stylex.props(s.refinementCheck)}>
                <input
                  type="checkbox"
                  checked={inputNodesOnly}
                  onChange={(event) => {
                    setInputNodesOnly(event.currentTarget.checked);
                    setSelectedNodeKey(null);
                  }}
                />
                Input nodes only
              </label>
            </div>
          </nav>

          <section
            aria-labelledby="node-selector-results-heading"
            {...stylex.props(
              s.nodePane,
              mobileNodeSelector && detailsOpen && s.hidden,
            )}
          >
            <header {...stylex.props(s.nodePaneHeader)}>
              <div {...stylex.props(s.resultHeading)}>
                <h3
                  id="node-selector-results-heading"
                  {...stylex.props(s.nodePaneTitle)}
                >
                  {resultsTitle}
                </h3>
                <span
                  role={errorMessage ? "alert" : "status"}
                  aria-live={errorMessage ? "assertive" : "polite"}
                  aria-atomic="true"
                  {...stylex.props(s.resultCount)}
                >
                  {resultStatus}
                </span>
              </div>
            </header>
            {compatibility && compatibilityPortTitle ? (
              <div
                id="node-selector-compatibility"
                {...stylex.props(s.compatibilityBanner)}
              >
                <Cable size={12} aria-hidden="true" />
                Showing nodes that can connect{" "}
                {compatibility.direction === "upstream" ? "to" : "from"}{" "}
                <strong>{compatibilityPortTitle}</strong>.
              </div>
            ) : null}
            <div
              id="node-selector-results"
              role="listbox"
              aria-label="Node results"
              aria-busy={loading}
              aria-activedescendant={activeResultId}
              {...stylex.props(s.nodeList)}
            >
              {errorMessage ? (
                <div {...stylex.props(s.empty)}>
                  <span>Nodes couldn’t be loaded. {errorMessage}</span>
                  {onRetry ? (
                    <button
                      type="button"
                      {...stylex.props(s.resetButton)}
                      onClick={onRetry}
                    >
                      Try again
                    </button>
                  ) : null}
                </div>
              ) : loading ? (
                <div {...stylex.props(s.empty)}>Loading nodes…</div>
              ) : filteredNodes.length ? (
                filteredNodes.map((spec, index) => {
                  const key = nodeKey(spec);
                  const active = listedSpec
                    ? key === nodeKey(listedSpec)
                    : false;
                  const representativePort = spec.outputs[0] ?? spec.inputs[0];
                  const representativeArtifact = representativePort
                    ? portArtifactType(representativePort)
                    : null;
                  return (
                    <button
                      key={key}
                      id={`node-selector-result-${key}`}
                      ref={(element) => {
                        if (element) resultRefs.current.set(key, element);
                        else resultRefs.current.delete(key);
                      }}
                      type="button"
                      role="option"
                      tabIndex={active ? 0 : -1}
                      aria-selected={active}
                      {...stylex.props(
                        s.nodeRow,
                        active ? s.nodeRowActive : null,
                      )}
                      style={
                        active && representativeArtifact
                          ? {
                              borderColor: artifactTypeColor(
                                representativeArtifact.id,
                                tokens.colorAccent,
                              ),
                            }
                          : undefined
                      }
                      onClick={() => {
                        setSelectedNodeKey(key);
                        setTechnicalDetailsOpen(false);
                        setDetailsOpen(true);
                      }}
                      onFocus={() => setSelectedNodeKey(key)}
                      onKeyDown={(event) => {
                        if (event.key === "ArrowDown") {
                          event.preventDefault();
                          focusResultAt(index + 1);
                        } else if (event.key === "ArrowUp") {
                          event.preventDefault();
                          focusResultAt(index - 1);
                        } else if (event.key === "Home") {
                          event.preventDefault();
                          focusResultAt(0);
                        } else if (event.key === "End") {
                          event.preventDefault();
                          focusResultAt(filteredNodes.length - 1);
                        } else if (event.key === "Enter") {
                          event.preventDefault();
                          if (selectedSpec) insertNode(selectedSpec);
                        }
                      }}
                    >
                      <span {...stylex.props(s.nodeCopy)}>
                        <span {...stylex.props(s.nodeTitleRow)}>
                          <span {...stylex.props(s.nodeTitle)}>
                            {spec.title}
                          </span>
                        </span>
                        <span {...stylex.props(s.nodeDescription)}>
                          {spec.description || "No description is available."}
                        </span>
                      </span>
                    </button>
                  );
                })
              ) : (
                <div {...stylex.props(s.empty)}>
                  <span>
                    {compatibility
                      ? "No nodes match this port and the current search or filter."
                      : showingModules
                        ? "No published Modules match the current search."
                        : "No nodes match the current search or filter."}
                  </span>
                  {normalizedQuery ||
                  activeSourceId !== "all" ||
                  artifactFilterId !== null ||
                  inputNodesOnly ? (
                    <button
                      type="button"
                      {...stylex.props(s.resetButton)}
                      onClick={() => {
                        setQuery("");
                        setActiveSourceId("all");
                        setArtifactFilterId(null);
                        setInputNodesOnly(false);
                        setSelectedNodeKey(null);
                      }}
                    >
                      Reset search and filter
                    </button>
                  ) : null}
                </div>
              )}
            </div>
            {showingModules && !loading && !errorMessage ? (
              <div
                aria-label="Workspace library notes"
                {...stylex.props(s.moduleDiagnostics)}
              >
                {activeEditingModule ? (
                  <p {...stylex.props(s.moduleDiagnosticsNote)}>
                    “{activeEditingModule.title}” is hidden here because it is
                    the graph currently being edited.
                  </p>
                ) : null}
                {filteredNodes.length === 0 && !normalizedQuery ? (
                  <p {...stylex.props(s.moduleDiagnosticsNote)}>
                    {compatibility
                      ? "No published Modules in this workspace can connect to this port."
                      : "No published Modules in this workspace yet. Open a source graph, declare Module Input/Output boundaries, then Publish release."}
                    {onOpenWorkspaceLibrary ? (
                      <>
                        {" "}
                        <button
                          type="button"
                          {...stylex.props(s.resetButton)}
                          onClick={onOpenWorkspaceLibrary}
                        >
                          Open workspace library
                        </button>
                      </>
                    ) : null}
                  </p>
                ) : null}
              </div>
            ) : null}
          </section>

          <aside
            aria-label="Node information"
            aria-labelledby={
              selectedSpec ? "node-selector-inspector-title" : undefined
            }
            {...stylex.props(
              s.inspector,
              mobileNodeSelector && !detailsOpen && s.hidden,
            )}
          >
            {mobileNodeSelector && detailsOpen ? (
              <button
                ref={backRef}
                type="button"
                {...stylex.props(s.backButton)}
                onClick={() => {
                  pendingResultFocusKey.current = listedSpec
                    ? nodeKey(listedSpec)
                    : null;
                  setDetailsOpen(false);
                }}
              >
                <ArrowLeft size={16} aria-hidden="true" /> Back to results
              </button>
            ) : null}
            {selectedSpec && selectedPlugin ? (
              <>
                <div
                  key={nodeKey(selectedSpec)}
                  {...stylex.props(s.inspectorBody)}
                  className={[
                    stylex.props(s.inspectorBody).className,
                    "grafy-node-detail",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                >
                  <div
                    {...stylex.props(s.previewStage)}
                    className={[
                      stylex.props(s.previewStage).className,
                      "grafy-node-preview-stage",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                  >
                    <CatalogNodePreview
                      spec={selectedSpec}
                      registry={registry}
                      fields={selectedFields}
                      selectedPortKey={
                        activeCompatibilityPort
                          ? portKey(activeCompatibilityPort)
                          : null
                      }
                      onSelectPort={(port) => {
                        if (!selectedSpecKey) return;
                        setCompatibilityPortSelection({
                          specKey: selectedSpecKey,
                          portKey: portKey(port),
                        });
                      }}
                    />
                  </div>
                  <div {...stylex.props(s.inspectorScroll)}>
                    {isModuleSelection ? (
                      <header {...stylex.props(s.inspectorHeader)}>
                        <div {...stylex.props(s.inspectorProvenance)}>
                          <div {...stylex.props(s.eyebrow)}>
                            Module · release{" "}
                            {selectedSpec.module_graph_revision}
                          </div>
                          <span {...stylex.props(s.originBadge)}>
                            {selectedSpec.publication_state ?? "published"}
                          </span>
                        </div>
                        <h3
                          id="node-selector-inspector-title"
                          {...stylex.props(s.inspectorTitle)}
                        >
                          {selectedSpec.title}
                        </h3>
                        <div {...stylex.props(s.operatorId)}>
                          Module contract · release{" "}
                          {selectedSpec.module_graph_revision}
                        </div>
                        {moduleReleases.length > 1 ? (
                          <label {...stylex.props(s.operatorId)}>
                            Release{" "}
                            <select
                              aria-label="Module release"
                              value={nodeKey(selectedSpec)}
                              onChange={(event) => {
                                const moduleKey =
                                  listedSpec.module_id ??
                                  listedSpec.module_graph_id;
                                if (!moduleKey) return;
                                setSelectedRelease({
                                  moduleKey,
                                  releaseKey: event.currentTarget.value,
                                });
                              }}
                            >
                              {moduleReleases.map((release) => (
                                <option
                                  key={nodeKey(release)}
                                  value={nodeKey(release)}
                                >
                                  Release {release.module_graph_revision}
                                  {release.is_current_library_release
                                    ? " (current)"
                                    : ""}
                                </option>
                              ))}
                            </select>
                          </label>
                        ) : null}
                        {isDeprecatedModule ? (
                          <p {...stylex.props(s.moduleDiagnosticsNote)}>
                            This Module is deprecated. New inserts are
                            discouraged; existing pins keep working.
                          </p>
                        ) : null}
                        {selectedSpec.module_graph_id && onOpenGraph ? (
                          <button
                            type="button"
                            title="Open the saved graph that defines this module"
                            {...stylex.props(
                              s.openGraphButton,
                              s.inspectorOpenGraph,
                            )}
                            onClick={() =>
                              onOpenGraph(selectedSpec.module_graph_id!)
                            }
                          >
                            <ExternalLink size={10} />
                            Open source graph
                          </button>
                        ) : null}
                        <p {...stylex.props(s.inspectorDescription)}>
                          {selectedSpec.description ||
                            "No description is available for this node."}
                        </p>
                        {selectedSpec.runnable === false ? (
                          <p {...stylex.props(s.moduleDiagnosticsNote)}>
                            Catalog preview only. {pluginUnavailableReason}
                          </p>
                        ) : null}
                      </header>
                    ) : (
                      <header {...stylex.props(s.inspectorHeader)}>
                        <h3
                          id="node-selector-inspector-title"
                          {...stylex.props(s.inspectorTitle)}
                        >
                          {selectedSpec.title}
                        </h3>
                        <p {...stylex.props(s.inspectorDescription)}>
                          {selectedSpec.description ||
                            "No description is available for this node."}
                        </p>
                        {selectedSpec.runnable === false ? (
                          <p {...stylex.props(s.moduleDiagnosticsNote)}>
                            Catalog preview only. {pluginUnavailableReason}
                          </p>
                        ) : null}
                        <div {...stylex.props(s.inspectorSummary)}>
                          <p {...stylex.props(s.inspectorStatement)}>
                            {selectedPrimaryInput ? (
                              <>
                                Accepts{" "}
                                <span
                                  {...stylex.props(s.inspectorStatementStrong)}
                                  style={{
                                    color: selectedPrimaryInputArtifact
                                      ? artifactTypeColor(
                                          selectedPrimaryInputArtifact.id,
                                          tokens.colorTextEmphasis,
                                        )
                                      : tokens.colorTextEmphasis,
                                  }}
                                >
                                  {artifactTitleFor(
                                    registry,
                                    selectedPrimaryInput,
                                  )}
                                </span>
                                {selectedSpec.inputs.length > 1
                                  ? ` + ${selectedSpec.inputs.length - 1} more`
                                  : ` · ${selectedPrimaryInput.shape === "many" ? "sequence" : "single value"}`}
                              </>
                            ) : (
                              "Starts a workflow"
                            )}
                          </p>
                          <p {...stylex.props(s.inspectorStatement)}>
                            {selectedPrimaryOutput ? (
                              <>
                                Produces{" "}
                                <span
                                  {...stylex.props(s.inspectorStatementStrong)}
                                  style={{
                                    color: selectedPrimaryOutputArtifact
                                      ? artifactTypeColor(
                                          selectedPrimaryOutputArtifact.id,
                                          tokens.colorTextEmphasis,
                                        )
                                      : tokens.colorTextEmphasis,
                                  }}
                                >
                                  {artifactTitleFor(
                                    registry,
                                    selectedPrimaryOutput,
                                  )}
                                </span>
                                {selectedSpec.outputs.length > 1
                                  ? ` + ${selectedSpec.outputs.length - 1} more`
                                  : ` · ${selectedPrimaryOutput.shape === "many" ? "sequence" : "single value"}`}
                              </>
                            ) : (
                              "Ends a workflow branch"
                            )}
                          </p>
                          <div {...stylex.props(s.inspectorConfiguration)}>
                            <span
                              {...stylex.props(s.inspectorConfigurationLabel)}
                            >
                              Configuration:
                            </span>
                            <span>
                              {selectedFields.length
                                ? `${selectedFields.map((field) => field.title).join(", ")} ${selectedFields.length === 1 ? "is" : "are"} editable after adding.`
                                : "No editable settings."}
                            </span>
                          </div>
                          <button
                            type="button"
                            aria-expanded={technicalDetailsOpen}
                            {...stylex.props(s.technicalToggle)}
                            onClick={() =>
                              setTechnicalDetailsOpen((open) => !open)
                            }
                          >
                            {technicalDetailsOpen
                              ? "Hide technical details"
                              : "View technical details"}
                          </button>
                        </div>
                      </header>
                    )}

                    {isModuleSelection || technicalDetailsOpen ? (
                      <>
                        <section {...stylex.props(s.section)}>
                          <div {...stylex.props(s.sectionTitleRow)}>
                            <Workflow
                              size={13}
                              {...stylex.props(s.sectionIcon)}
                            />
                            <h3 {...stylex.props(s.sectionTitle)}>
                              {isModuleSelection ? "Module contract" : "Ports"}
                            </h3>
                          </div>
                          {!isModuleSelection ? (
                            <p {...stylex.props(s.moduleDiagnosticsNote)}>
                              {selectedSpec.operator_id}@
                              {selectedSpec.operator_version}
                            </p>
                          ) : null}
                          <div {...stylex.props(s.portGrid)}>
                            <PortList
                              direction="input"
                              ports={selectedSpec.inputs}
                              registry={registry}
                            />
                            <PortList
                              direction="output"
                              ports={selectedSpec.outputs}
                              registry={registry}
                            />
                          </div>
                        </section>

                        <section {...stylex.props(s.section)}>
                          <div {...stylex.props(s.sectionTitleRow)}>
                            <Settings2
                              size={13}
                              {...stylex.props(s.sectionIcon)}
                            />
                            <h3 {...stylex.props(s.sectionTitle)}>
                              Configuration
                            </h3>
                          </div>
                          {selectedFields.length ? (
                            <div {...stylex.props(s.fieldList)}>
                              {selectedFields.map((field) => (
                                <div
                                  key={field.name}
                                  {...stylex.props(s.fieldRow)}
                                >
                                  <div {...stylex.props(s.fieldIdentity)}>
                                    <div {...stylex.props(s.fieldTitle)}>
                                      {field.title}
                                    </div>
                                    <div {...stylex.props(s.fieldName)}>
                                      {field.name}
                                    </div>
                                  </div>
                                  <div {...stylex.props(s.fieldDetails)}>
                                    <div {...stylex.props(s.fieldMeta)}>
                                      {fieldTypeLabel(field)} ·{" "}
                                      {fieldConstraintLabel(field)}
                                    </div>
                                    {field.description ? (
                                      <p {...stylex.props(s.fieldDescription)}>
                                        {field.description}
                                      </p>
                                    ) : null}
                                    {field.enumValues?.length ? (
                                      <p {...stylex.props(s.fieldChoices)}>
                                        Choices:{" "}
                                        {field.enumValues
                                          .map(String)
                                          .join(", ")}
                                      </p>
                                    ) : null}
                                    {field.pattern ? (
                                      <p {...stylex.props(s.fieldChoices)}>
                                        Pattern: {field.pattern}
                                      </p>
                                    ) : null}
                                  </div>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <p {...stylex.props(s.compatibilityEmpty)}>
                              No editable scalar settings are declared. Upload
                              or custom controls, when available, appear on the
                              node after it is added.
                            </p>
                          )}
                        </section>
                      </>
                    ) : null}

                    {activeCompatibilityPort ? (
                      <WorksWithSection
                        ports={compatibilityPorts}
                        activePort={activeCompatibilityPort}
                        matches={portMatches}
                        registry={registry}
                        onSelectPort={(port) => {
                          if (!selectedSpecKey) return;
                          setCompatibilityPortSelection({
                            specKey: selectedSpecKey,
                            portKey: portKey(port),
                          });
                        }}
                        onInspect={inspectCatalogNode}
                      />
                    ) : null}
                  </div>
                </div>

                <footer {...stylex.props(s.inspectorFooter)}>
                  {!selectionCanInsert ? (
                    <span
                      id="node-selector-insert-disabled-reason"
                      {...stylex.props(s.visuallyHidden)}
                    >
                      {selectionDisabledReason}
                    </span>
                  ) : null}
                  <button
                    type="button"
                    disabled={!selectionCanInsert}
                    aria-describedby={
                      !selectionCanInsert
                        ? "node-selector-insert-disabled-reason"
                        : undefined
                    }
                    title={
                      !selectionCanInsert
                        ? selectionDisabledReason
                        : isModuleSelection
                          ? `Insert module call for ${selectedSpec.title}`
                          : `Add ${selectedSpec.title} to the workflow`
                    }
                    {...stylex.props(
                      s.addButton,
                      !selectionCanInsert ? s.addButtonDisabled : null,
                    )}
                    onClick={() => insertNode(selectedSpec)}
                  >
                    <Plus size={14} />{" "}
                    {isModuleSelection
                      ? "Insert module call"
                      : `Add ${selectedSpec.title}`}
                  </button>
                </footer>
              </>
            ) : (
              <div {...stylex.props(s.empty)}>
                {loading
                  ? "Loading node details…"
                  : errorMessage
                    ? "Node details are unavailable until the list loads."
                    : "Select a node to inspect its contract."}
              </div>
            )}
          </aside>
        </div>
      </DialogContent>
    </Dialog>
  );
}
