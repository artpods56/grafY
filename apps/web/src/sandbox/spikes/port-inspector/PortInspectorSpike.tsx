"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { ChevronDown, ChevronRight } from "lucide-react";

import { overlay } from "@/lib/stylex/overlay.stylex";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { artifactTypeColor } from "@/features/workbench/canvas/nodes.css";
import { SchemaDrill } from "@/features/workbench/canvas/nodes/type-inspector";
import {
  CatalogNodePreview,
  portKey,
} from "@/features/workbench/ui/CatalogNodePreview";
import { SandboxShell } from "../../SandboxShell";
import {
  GEO_MAP_LAYER_SCHEMA,
  LAYER_PORT,
  VECTOR_LAYER_FIELDS,
  VECTOR_LAYER_REGISTRY,
  VECTOR_LAYER_SPEC,
} from "../../fixtures/vector-map-layer";
import { schemaOutline, type OutlineNode } from "./schema-outline";

type CardId = "today" | "unions" | "fold" | "drill" | "guides";

const CARDS: { id: CardId; label: string; note: string }[] = [
  {
    id: "today",
    label: "Today",
    note: "The previous flattened tree. It only follows anyOf, so source and style (oneOf) have no children.",
  },
  {
    id: "unions",
    label: "All unions",
    note: "Same schema, every oneOf branch opened as “as kind”. Still a dump — but a complete one.",
  },
  {
    id: "fold",
    label: "Fold",
    note: "Complete outline, closed. Open an object to see inside. Unions stay a type until expanded.",
  },
  {
    id: "drill",
    label: "Drill",
    note: "Shipping inspector. One object at a time. Click a nested field to go in. Breadcrumb back. Not a projection picker.",
  },
  {
    id: "guides",
    label: "Guides",
    note: "Full outline with indent rails. Wider, still the schema, not a summary.",
  },
];

const LAYER_COLOR = artifactTypeColor("geo.map_layer", tokens.colorAccent);
const OUTLINE = schemaOutline(GEO_MAP_LAYER_SCHEMA);

const s = stylex.create({
  scene: {
    display: "flex",
    alignItems: "flex-start",
    gap: "24px",
  },
  popup: {
    width: "320px",
    flexShrink: 0,
    overflow: "hidden",
    marginTop: "36px",
  },
  popupWide: {
    width: "380px",
  },
  popupDrill: {
    width: "440px",
    marginTop: "28px",
  },
  header: {
    display: "grid",
    gap: "3px",
    padding: "12px 14px 10px",
  },
  headerDrill: {
    gap: "6px",
    padding: "16px 18px 14px",
  },
  title: {
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeSm,
    fontWeight: 740,
  },
  titleRow: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    minWidth: 0,
  },
  contract: {
    display: "flex",
    alignItems: "center",
    gap: "7px",
    color: tokens.colorSubtle,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: tokens.fontSizeXs,
    fontWeight: 700,
  },
  dot: {
    width: "7px",
    height: "7px",
    flexShrink: 0,
    borderRadius: "9999px",
  },
  description: {
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
  section: {
    padding: "9px 14px 12px",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
  },
  sectionDrill: {
    padding: "14px 18px 18px",
  },
  sectionTitle: {
    marginBottom: "6px",
    color: tokens.colorMuted,
    fontSize: "10px",
    fontWeight: 800,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
  },
  tree: {
    display: "grid",
    gap: "1px",
    maxHeight: "360px",
    overflowY: "auto",
  },
  row: {
    display: "flex",
    alignItems: "baseline",
    gap: "8px",
    minHeight: "20px",
    width: "100%",
    padding: 0,
    borderWidth: 0,
    backgroundColor: "transparent",
    color: "inherit",
    font: "inherit",
    textAlign: "left",
  },
  rowButton: {
    cursor: "pointer",
    borderRadius: tokens.radiusSm,
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorHover,
    },
  },
  fieldName: {
    color: tokens.colorTextEmphasis,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: tokens.fontSizeXs,
  },
  branchName: {
    color: tokens.colorMuted,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: tokens.fontSizeXs,
    fontStyle: "italic",
  },
  required: { color: tokens.colorSubtle },
  fieldType: {
    marginLeft: "auto",
    color: tokens.colorSubtle,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: tokens.fontSizeXs,
    whiteSpace: "nowrap",
  },
  chevron: {
    flexShrink: 0,
    color: tokens.colorSubtle,
  },
  rail: {
    borderLeftWidth: 1,
    borderLeftStyle: "solid",
    borderLeftColor: tokens.colorDivider,
  },
});

function InspectorHeader({
  roomy = false,
  besidePort = false,
}: {
  roomy?: boolean;
  besidePort?: boolean;
}) {
  return (
    <header {...stylex.props(s.header, roomy ? s.headerDrill : null)}>
      {besidePort ? (
        <span {...stylex.props(s.contract)}>geo.map_layer@1</span>
      ) : (
        <div {...stylex.props(s.titleRow)}>
          <span {...stylex.props(s.title)}>layer</span>
          <span {...stylex.props(s.contract)}>
            <span
              {...stylex.props(s.dot)}
              style={{ backgroundColor: LAYER_COLOR }}
            />
            geo.map_layer@1
          </span>
        </div>
      )}
      <span {...stylex.props(s.description)}>
        Lightweight display instructions for one vector, raster, or WMS source.
      </span>
    </header>
  );
}

function TypeMark({ node }: { node: OutlineNode }) {
  return (
    <>
      <span
        {...stylex.props(node.kind === "branch" ? s.branchName : s.fieldName)}
      >
        {node.name}
        {node.required ? <span {...stylex.props(s.required)}>*</span> : null}
      </span>
      <span {...stylex.props(s.fieldType)}>{node.typeLabel}</span>
    </>
  );
}

function ExpandedTree({
  nodes,
  depth,
  guides,
}: {
  nodes: readonly OutlineNode[];
  depth: number;
  guides?: boolean;
}) {
  return (
    <>
      {nodes.map((node) => (
        <div
          key={node.id}
          {...stylex.props(guides && depth > 0 ? s.rail : null)}
          style={{ paddingLeft: depth === 0 ? 0 : 12 }}
        >
          <div {...stylex.props(s.row)}>
            <TypeMark node={node} />
          </div>
          {node.children.length ? (
            <ExpandedTree
              nodes={node.children}
              depth={depth + 1}
              guides={guides}
            />
          ) : null}
        </div>
      ))}
    </>
  );
}

function FoldTree({
  nodes,
  depth,
  open,
  onToggle,
}: {
  nodes: readonly OutlineNode[];
  depth: number;
  open: ReadonlySet<string>;
  onToggle: (id: string) => void;
}) {
  return (
    <>
      {nodes.map((node) => {
        const expanded = open.has(node.id);
        return (
          <div key={node.id} style={{ paddingLeft: depth === 0 ? 0 : 12 }}>
            {node.expandable ? (
              <button
                type="button"
                {...stylex.props(s.row, s.rowButton)}
                onClick={() => onToggle(node.id)}
              >
                <span {...stylex.props(s.chevron)}>
                  {expanded ? (
                    <ChevronDown size={11} />
                  ) : (
                    <ChevronRight size={11} />
                  )}
                </span>
                <TypeMark node={node} />
              </button>
            ) : (
              <div {...stylex.props(s.row)} style={{ paddingLeft: 15 }}>
                <TypeMark node={node} />
              </div>
            )}
            {expanded && node.children.length ? (
              <FoldTree
                nodes={node.children}
                depth={depth + 1}
                open={open}
                onToggle={onToggle}
              />
            ) : null}
          </div>
        );
      })}
    </>
  );
}

function TodayCard() {
  return (
    <div {...stylex.props(overlay.popup, s.popup)}>
      <InspectorHeader />
      <section {...stylex.props(s.section)}>
        <div {...stylex.props(s.sectionTitle)}>Map layer</div>
        <div {...stylex.props(s.tree)}>
          {OUTLINE.map((node) => (
            <div key={node.id} {...stylex.props(s.row)}>
              <TypeMark node={node} />
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function UnionsCard() {
  return (
    <div {...stylex.props(overlay.popup, s.popup)}>
      <InspectorHeader />
      <section {...stylex.props(s.section)}>
        <div {...stylex.props(s.sectionTitle)}>Payload</div>
        <div {...stylex.props(s.tree)}>
          <ExpandedTree nodes={OUTLINE} depth={0} />
        </div>
      </section>
    </div>
  );
}

function FoldCard() {
  const [open, setOpen] = React.useState<Set<string>>(
    () => new Set(OUTLINE.map((node) => node.id)),
  );
  return (
    <div {...stylex.props(overlay.popup, s.popup)}>
      <InspectorHeader />
      <section {...stylex.props(s.section)}>
        <div {...stylex.props(s.sectionTitle)}>Payload</div>
        <div {...stylex.props(s.tree)}>
          <FoldTree
            nodes={OUTLINE}
            depth={0}
            open={open}
            onToggle={(id) => {
              setOpen((current) => {
                const next = new Set(current);
                if (next.has(id)) next.delete(id);
                else next.add(id);
                return next;
              });
            }}
          />
        </div>
      </section>
    </div>
  );
}

function DrillCard() {
  return (
    <div {...stylex.props(overlay.popup, s.popup, s.popupDrill)}>
      <InspectorHeader roomy besidePort />
      <section {...stylex.props(s.section, s.sectionDrill)}>
        <SchemaDrill schema={GEO_MAP_LAYER_SCHEMA} rootLabel="GeoMapLayer" />
      </section>
    </div>
  );
}

function GuidesCard() {
  return (
    <div {...stylex.props(overlay.popup, s.popup, s.popupWide)}>
      <InspectorHeader />
      <section {...stylex.props(s.section)}>
        <div {...stylex.props(s.sectionTitle)}>Payload</div>
        <div {...stylex.props(s.tree)}>
          <ExpandedTree nodes={OUTLINE} depth={0} guides />
        </div>
      </section>
    </div>
  );
}

export function PortInspectorSpike() {
  const [card, setCard] = React.useState<CardId>("drill");
  const selected = CARDS.find((item) => item.id === card) ?? CARDS[3];

  return (
    <SandboxShell
      title="Port inspector"
      note={selected.note}
      variants={CARDS}
      activeVariant={card}
      onVariant={(id) => setCard(id as CardId)}
    >
      <div {...stylex.props(s.scene)}>
        <CatalogNodePreview
          spec={VECTOR_LAYER_SPEC}
          registry={VECTOR_LAYER_REGISTRY}
          fields={VECTOR_LAYER_FIELDS}
          selectedPortKey={portKey(LAYER_PORT)}
        />
        {card === "today" ? (
          <TodayCard />
        ) : card === "unions" ? (
          <UnionsCard />
        ) : card === "fold" ? (
          <FoldCard />
        ) : card === "drill" ? (
          <DrillCard />
        ) : (
          <GuidesCard />
        )}
      </div>
    </SandboxShell>
  );
}
