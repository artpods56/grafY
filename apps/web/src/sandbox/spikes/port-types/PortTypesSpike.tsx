"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Menu } from "@base-ui/react/menu";
import { Check, ChevronDown } from "lucide-react";

import { overlay } from "@/lib/stylex/overlay.stylex";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { portMarkStyle } from "@/features/workbench/canvas/handle-style";
import { artifactTypeColor } from "@/features/workbench/canvas/nodes.css";
import { SandboxShell } from "../../SandboxShell";

/**
 * Where a generic port's type lives on a node. The same four nodes are drawn
 * under each approach: one generic input ("Count items"), two different
 * generics on one node ("Pair"), a generic output ("Interpret file"), and a
 * node with no generics at all ("Add integers") as the control.
 */

type ApproachId =
  "caption" | "field" | "short" | "tag" | "signature" | "ring" | "compare";

type Approach = Exclude<ApproachId, "compare">;

interface TypeKey {
  id: string;
  schema_version: number;
}

interface SpikePort {
  name: string;
  direction: "input" | "output";
  required?: boolean;
  shape: "one" | "many";
  /** A concrete type the port always has. */
  fixed?: TypeKey;
  /** A type variable the node binds (a generic port). */
  variable?: string;
}

interface SpikeNode {
  key: string;
  title: string;
  inputs: SpikePort[];
  outputs: SpikePort[];
}

const INTEGER = { id: "scalar.integer", schema_version: 1 };
const TEXT = { id: "scalar.text", schema_version: 1 };

const NODES: readonly SpikeNode[] = [
  {
    key: "count",
    title: "Count items",
    inputs: [
      {
        name: "items",
        direction: "input",
        required: true,
        shape: "many",
        variable: "T",
      },
    ],
    outputs: [
      { name: "count", direction: "output", shape: "one", fixed: INTEGER },
    ],
  },
  {
    key: "pair",
    title: "Pair",
    inputs: [
      {
        name: "left",
        direction: "input",
        required: true,
        shape: "one",
        variable: "L",
      },
      { name: "right", direction: "input", shape: "many", variable: "R" },
    ],
    outputs: [{ name: "pair", direction: "output", shape: "one", fixed: TEXT }],
  },
  {
    key: "interpret",
    title: "Interpret file",
    inputs: [
      {
        name: "blob",
        direction: "input",
        required: true,
        shape: "one",
        fixed: { id: "file.blob", schema_version: 1 },
      },
    ],
    outputs: [
      { name: "file", direction: "output", shape: "one", variable: "format" },
    ],
  },
  {
    key: "add",
    title: "Add integers",
    inputs: [
      {
        name: "left",
        direction: "input",
        required: true,
        shape: "one",
        fixed: INTEGER,
      },
      {
        name: "right",
        direction: "input",
        required: true,
        shape: "one",
        fixed: INTEGER,
      },
    ],
    outputs: [
      { name: "result", direction: "output", shape: "one", fixed: INTEGER },
    ],
  },
];

/** Which ports have a wire, to see types beside real edges. */
type EdgeMode = "none" | "inputs" | "all";

/**
 * The type a wire brings: an open generic takes what its source produces, as
 * it does on the canvas when you connect it.
 */
const SOURCE_TYPES: Record<string, TypeKey> = {
  T: { id: "file.png", schema_version: 1 },
  L: { id: "file.png", schema_version: 1 },
  R: { id: "file.jpeg", schema_version: 1 },
  format: { id: "json.schema", schema_version: 1 },
};

const CHOICES: readonly TypeKey[] = [
  { id: "file.png", schema_version: 1 },
  { id: "file.jpeg", schema_version: 1 },
  { id: "image.raster", schema_version: 1 },
  { id: "table.data", schema_version: 1 },
  { id: "json.schema", schema_version: 1 },
];

const INITIAL_BINDINGS: Record<string, Record<string, TypeKey | undefined>> = {
  count: { T: undefined },
  pair: { L: { id: "file.png", schema_version: 1 }, R: undefined },
  interpret: { format: undefined },
  add: {},
};

const APPROACHES: readonly { id: ApproachId; label: string; note: string }[] = [
  {
    id: "caption",
    label: "Caption",
    note: "The type is the port's caption, small above its name, and is the picker. The name keeps its line level with the ball. What is on the canvas now.",
  },
  {
    id: "field",
    label: "Field",
    note: "Read the port as a form field: its name is the label, its type is the field's value in a box you open. The ball lines up with the box, the thing you set.",
  },
  {
    id: "short",
    label: "Short",
    note: "One line, compact notation: png, png[] for a sequence, any while unbound. Every port states its type this way; only generic ones open a menu. Full names in the tooltip and menu.",
  },
  {
    id: "tag",
    label: "Tag",
    note: "The type belongs to the connector, not the plate: a small tag hangs beyond a generic port's ball, where wires meet. The plate keeps only names.",
  },
  {
    id: "signature",
    label: "Signature",
    note: "Generics are declared once, on the name row, like a function signature: Pair‹L, R›. Ports refer to them (left: L). Two ports sharing a variable share one picker by construction.",
  },
  {
    id: "ring",
    label: "Ring",
    note: "No type text at all. A generic port still open has a dashed ring; bound, it turns solid in its type's colour. Click the ring to choose. The type is in the tooltip.",
  },
  {
    id: "compare",
    label: "Compare all",
    note: "Every approach on the two hardest nodes: one generic sequence input, and two different generics on one node.",
  },
];

const s = stylex.create({
  controls: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    gap: "8px",
    marginBottom: "24px",
  },
  toggle: {
    height: "26px",
    display: "inline-flex",
    alignItems: "center",
    gap: "6px",
    paddingInline: "9px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusSm,
    backgroundColor: {
      default: tokens.colorChrome,
      ":hover": tokens.colorHover,
    },
    color: tokens.colorText,
    cursor: "pointer",
    fontSize: tokens.fontSizeXs,
  },
  toggleOn: { backgroundColor: tokens.colorAccentSoft },
  scenes: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "flex-start",
    gap: "28px 12px",
  },
  scene: { display: "grid", gap: "10px" },
  sceneLabel: {
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    letterSpacing: "0.02em",
  },
  // Room either side for balls and, in "tag", the tags beyond them.
  sceneStage: { paddingInline: "96px", paddingBlock: "4px 8px" },
  // With wires, room for their off-screen ends.
  sceneStageWired: { paddingInline: "196px", paddingBlock: "4px 40px" },
  wires: {
    position: "absolute",
    overflow: "visible",
    pointerEvents: "none",
  },
  segmented: {
    display: "inline-flex",
    alignItems: "center",
    gap: "2px",
    padding: "2px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusSm,
    backgroundColor: tokens.colorChrome,
  },
  segmentedLabel: {
    paddingInline: "6px 4px",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
  },
  segment: {
    height: "22px",
    paddingInline: "8px",
    borderWidth: 0,
    borderRadius: "4px",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: tokens.colorMuted,
    cursor: "pointer",
    fontSize: tokens.fontSizeXs,
  },
  segmentOn: {
    backgroundColor: tokens.colorAccentSoft,
    color: tokens.colorText,
  },
  compareGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(620px, 1fr))",
    gap: "28px 20px",
  },
  compareCell: {
    display: "grid",
    gap: "10px",
    padding: "14px 0 18px",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorBorder,
  },
  compareTitle: {
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    fontWeight: 600,
  },
  compareNote: {
    maxWidth: "62ch",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
  compareNodes: { display: "flex", flexWrap: "wrap", gap: "12px" },

  node: { position: "relative", width: "300px" },
  nameRow: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
    height: "24px",
    paddingInline: "2px",
  },
  name: {
    minWidth: 0,
    overflow: "hidden",
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    fontWeight: 500,
    letterSpacing: "-0.01em",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  plate: {
    position: "relative",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorderStrong,
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorChrome,
    boxShadow: tokens.shadowNodeActive,
  },
  row: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)",
    height: "50px",
  },
  cell: {
    position: "relative",
    height: "100%",
    minWidth: 0,
    display: "flex",
    alignItems: "center",
  },
  cellOut: { justifyContent: "flex-end" },
  label: {
    display: "flex",
    alignItems: "center",
    gap: "4px",
    minWidth: 0,
    maxWidth: "calc(100% - 8px)",
    paddingInline: "10px",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    fontWeight: 500,
  },
  // Right-aligned, but read in the same order as an input: name, then type.
  labelOut: { justifyContent: "flex-end" },
  labelText: {
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  required: { flexShrink: 0, color: tokens.colorSubtle },
  mono: {
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "10.5px",
    fontWeight: 400,
  },
  subtle: { color: tokens.colorSubtle },

  // A type you can open: quiet text with a chevron.
  typeButton: {
    display: "inline-flex",
    alignItems: "center",
    gap: "2px",
    minWidth: 0,
    maxWidth: "100%",
    height: "18px",
    paddingInline: "3px",
    borderWidth: 0,
    borderRadius: tokens.radiusSm,
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: { default: tokens.colorSubtle, ":hover": tokens.colorText },
    cursor: "pointer",
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "10.5px",
  },
  typeBound: { color: tokens.colorMuted },
  typeLocked: {
    cursor: "default",
    backgroundColor: { default: "transparent", ":hover": "transparent" },
  },
  typeText: {
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  chevron: { flexShrink: 0, opacity: 0.7 },

  // Caption: above the name.
  caption: {
    position: "absolute",
    bottom: "calc(50% + 7px)",
    maxWidth: "calc(200% - 30px)",
    display: "flex",
  },
  captionIn: { left: "7px" },
  captionOut: { right: "7px" },
  captionText: { fontSize: "10px", height: "16px" },

  // Field: name as the label, the type as a boxed value under it.
  field: {
    display: "grid",
    gap: "3px",
    minWidth: 0,
    maxWidth: "calc(100% - 16px)",
    paddingInline: "10px",
  },
  fieldOut: { justifyItems: "end" },
  fieldLabel: {
    color: tokens.colorSubtle,
    fontSize: "10px",
    fontWeight: 500,
    letterSpacing: "0.02em",
  },
  fieldBox: {
    height: "20px",
    maxWidth: "100%",
    paddingInline: "6px 4px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    backgroundColor: {
      default: tokens.colorSurface,
      ":hover": tokens.colorSurface,
    },
  },

  // Tag: beyond the ball, outside the plate.
  tag: {
    position: "absolute",
    top: "50%",
    marginTop: "-9px",
    display: "flex",
  },
  tagIn: { right: "calc(100% + 46px)" },
  tagOut: { left: "calc(100% + 46px)" },
  tagPill: {
    height: "18px",
    paddingInline: "6px 4px",
    borderWidth: 1,
    borderStyle: "solid",
    borderRadius: "9999px",
    backgroundColor: {
      default: tokens.colorChrome,
      ":hover": tokens.colorSurface,
    },
    fontSize: "10px",
  },

  // Signature: parameters on the name row.
  params: {
    display: "flex",
    alignItems: "center",
    gap: "2px",
    minWidth: 0,
    color: tokens.colorSubtle,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "10.5px",
  },
  param: { display: "inline-flex", alignItems: "center", gap: "3px" },
  paramName: { color: tokens.colorText },

  // Ports: a slot outside the plate with a stem and a ring.
  ball: {
    position: "absolute",
    top: "50%",
    marginTop: "-15px",
    width: "30px",
    height: "30px",
  },
  ballIn: { left: "-39px" },
  ballOut: { right: "-39px" },
  stem: {
    position: "absolute",
    top: "50%",
    width: "23px",
    height: "1px",
    marginTop: "-0.5px",
    opacity: 0.5,
  },
  stemIn: { left: "50%" },
  stemOut: { right: "50%" },
  ring: {
    position: "absolute",
    top: "50%",
    left: "50%",
    width: "10px",
    height: "10px",
    marginTop: "-5px",
    marginLeft: "-5px",
    boxSizing: "border-box",
    borderWidth: 2,
    borderStyle: "solid",
    borderRadius: "9999px",
    backgroundColor: tokens.colorSurface,
  },
  ringOpen: { borderStyle: "dashed", borderWidth: "1.5px" },
  ringButton: {
    position: "absolute",
    inset: 0,
    padding: 0,
    borderWidth: 0,
    borderRadius: "9999px",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    cursor: "pointer",
  },

  menu: {
    display: "grid",
    gap: "1px",
    minWidth: "190px",
    padding: "4px",
    zIndex: 60,
  },
  menuHead: {
    padding: "5px 8px 6px",
    color: tokens.colorSubtle,
    fontSize: "10px",
    letterSpacing: "0.04em",
    textTransform: "uppercase",
  },
  option: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "10px",
    padding: "5px 8px",
    borderRadius: tokens.radiusSm,
    color: tokens.colorText,
    cursor: "pointer",
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "11px",
  },
  optionAny: { fontFamily: "inherit", color: tokens.colorMuted },
});

function keyText(type: TypeKey): string {
  return `${type.id}@${type.schema_version}`;
}

/** "Sequence<file.png@1>" / "file.png@1" / "Sequence<any>" / "any". */
function fullType(shape: SpikePort["shape"], type: TypeKey | undefined) {
  const inner = type ? keyText(type) : "any";
  return shape === "many" ? `Sequence<${inner}>` : inner;
}

/** "png[]" / "png" / "any[]": the family-free name, [] for a sequence. */
function shortType(shape: SpikePort["shape"], type: TypeKey | undefined) {
  let inner = "any";
  if (type) {
    const [family, kind = family] = type.id.split(".");
    inner = kind === "data" || kind === "value" ? family : kind;
    if (type.id === "scalar.integer") inner = "int";
    if (type.id === "scalar.text") inner = "text";
    if (type.schema_version > 1) inner = `${inner}@${type.schema_version}`;
  }
  return shape === "many" ? `${inner}[]` : inner;
}

function colorOf(type: TypeKey | undefined): string {
  return type
    ? artifactTypeColor(type.id, tokens.colorAccent)
    : tokens.colorAccent;
}

interface NodeContext {
  approach: Approach;
  node: SpikeNode;
  bindings: Record<string, TypeKey | undefined>;
  locked: boolean;
  edges: EdgeMode;
  onBind: (variable: string, type: TypeKey | undefined) => void;
}

function portWired(edges: EdgeMode, port: SpikePort): boolean {
  return edges === "all" || (edges === "inputs" && port.direction === "input");
}

/** Bindings as the node sees them once wired: open generics take the source. */
function wiredBindings(
  node: SpikeNode,
  bindings: Record<string, TypeKey | undefined>,
  edges: EdgeMode,
): Record<string, TypeKey | undefined> {
  const next = { ...bindings };
  for (const port of [...node.inputs, ...node.outputs]) {
    if (port.variable && !next[port.variable] && portWired(edges, port)) {
      next[port.variable] = SOURCE_TYPES[port.variable];
    }
  }
  return next;
}

/** Plate geometry, as on the canvas: a 24px name row, 1px border, 50px rows. */
const NODE_WIDTH = 300;
const NAME_ROW = 24;
const ROW = 50;
/** From the plate's edge to the ring's outer edge, where a wire starts. */
const RING_REACH = 28;
/** How far a wire runs to its off-screen end. */
const WIRE_RUN = 150;
/** The SVG reaches this far past each side of the plate. */
const WIRE_MARGIN = RING_REACH + WIRE_RUN + 12;

/**
 * Wires into and out of a node, drawn under its plate, balls and tags: each
 * comes from (or goes to) a ghost port off to the side.
 */
function WireLayer({ ctx }: { ctx: NodeContext }) {
  const rows = Math.max(ctx.node.inputs.length, ctx.node.outputs.length);
  const height = NAME_ROW + 2 + rows * ROW;
  const wires: React.ReactNode[] = [];
  const add = (port: SpikePort, index: number) => {
    if (!portWired(ctx.edges, port)) return;
    const type = port.variable ? ctx.bindings[port.variable] : port.fixed;
    const color = colorOf(type);
    const y = NAME_ROW + 1 + index * ROW + ROW / 2;
    const bend = index % 2 ? 34 : -34;
    const input = port.direction === "input";
    const ring = input
      ? WIRE_MARGIN - RING_REACH
      : WIRE_MARGIN + NODE_WIDTH + RING_REACH;
    const far = input ? ring - WIRE_RUN : ring + WIRE_RUN;
    const [x1, y1, x2, y2] = input
      ? [far, y + bend, ring, y]
      : [ring, y, far, y + bend];
    wires.push(
      <g key={`${port.direction}-${port.name}`}>
        <path
          d={`M${x1},${y1} C${x1 + 70},${y1} ${x2 - 70},${y2} ${x2},${y2}`}
          fill="none"
          stroke={color}
          strokeWidth={2}
          strokeOpacity={0.85}
        />
        <circle
          cx={far}
          cy={y + bend}
          r={4}
          fill={tokens.colorSurface}
          stroke={color}
          strokeWidth={2}
        />
      </g>,
    );
  };
  ctx.node.inputs.forEach(add);
  ctx.node.outputs.forEach(add);
  if (!wires.length) return null;
  return (
    <svg
      aria-hidden="true"
      {...stylex.props(s.wires)}
      width={NODE_WIDTH + WIRE_MARGIN * 2}
      height={height + 40}
      style={{ left: -WIRE_MARGIN, top: 0 }}
    >
      {wires}
    </svg>
  );
}

/** The types a variable can take, with "Any type" to clear it. */
function TypeMenu({
  variable,
  current,
  locked,
  onBind,
  trigger,
  triggerStyle,
  ariaLabel,
}: {
  variable: string;
  current: TypeKey | undefined;
  locked: boolean;
  onBind: (variable: string, type: TypeKey | undefined) => void;
  trigger: React.ReactNode;
  triggerStyle: ReturnType<typeof stylex.props>;
  ariaLabel: string;
}) {
  if (locked) {
    return (
      <span
        {...triggerStyle}
        title="A wire fixed this type. Disconnect the node to change it."
      >
        {trigger}
      </span>
    );
  }
  const popup = stylex.props(overlay.popup, s.menu);
  return (
    <Menu.Root>
      <Menu.Trigger aria-label={ariaLabel} {...triggerStyle}>
        {trigger}
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Positioner side="bottom" align="start" sideOffset={4}>
          <Menu.Popup {...popup}>
            <span {...stylex.props(s.menuHead)}>Type {variable}</span>
            <Menu.Item
              onClick={() => onBind(variable, undefined)}
              {...stylex.props(overlay.item, s.option, s.optionAny)}
            >
              Any type
              {current ? null : <Check size={12} />}
            </Menu.Item>
            {CHOICES.map((choice) => (
              <Menu.Item
                key={keyText(choice)}
                onClick={() => onBind(variable, choice)}
                {...stylex.props(overlay.item, s.option)}
              >
                {keyText(choice)}
                {current && keyText(current) === keyText(choice) ? (
                  <Check size={12} />
                ) : null}
              </Menu.Item>
            ))}
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.Root>
  );
}

function TypeText({ text, locked }: { text: string; locked: boolean }) {
  return (
    <>
      <span {...stylex.props(s.typeText)}>{text}</span>
      {locked ? null : (
        <ChevronDown size={9} aria-hidden="true" {...stylex.props(s.chevron)} />
      )}
    </>
  );
}

function Ball({
  ctx,
  port,
  type,
}: {
  ctx: NodeContext;
  port: SpikePort;
  type: TypeKey | undefined;
}) {
  const input = port.direction === "input";
  const color = colorOf(type);
  const open = ctx.approach === "ring" && Boolean(port.variable) && !type;
  const ring = (
    <>
      <span
        aria-hidden="true"
        {...stylex.props(s.stem, input ? s.stemIn : s.stemOut)}
        style={{ backgroundColor: color }}
      />
      <span
        aria-hidden="true"
        {...stylex.props(s.ring, open ? s.ringOpen : null)}
        style={{
          ...portMarkStyle(
            open ? tokens.colorSubtle : color,
            port.shape === "many",
          ),
        }}
      />
    </>
  );
  return (
    <span
      {...stylex.props(s.ball, input ? s.ballIn : s.ballOut)}
      title={`${port.name}: ${fullType(port.shape, type)}`}
    >
      {ring}
      {ctx.approach === "ring" && port.variable ? (
        <TypeMenu
          variable={port.variable}
          current={type}
          locked={ctx.locked}
          onBind={ctx.onBind}
          ariaLabel={`Choose the type of ${port.name}`}
          trigger={null}
          triggerStyle={stylex.props(s.ringButton)}
        />
      ) : null}
    </span>
  );
}

function PortCell({ ctx, port }: { ctx: NodeContext; port: SpikePort }) {
  const input = port.direction === "input";
  const type = port.variable ? ctx.bindings[port.variable] : port.fixed;
  const generic = Boolean(port.variable);
  const bound = Boolean(type);
  const { approach, locked, onBind } = ctx;
  const nameLabel = (
    <>
      <span {...stylex.props(s.labelText)}>{port.name}</span>
      {input && port.required ? (
        <span {...stylex.props(s.required)}>*</span>
      ) : null}
    </>
  );
  const typeButton = (extra: ReturnType<typeof stylex.props>, text: string) =>
    generic && port.variable ? (
      <TypeMenu
        variable={port.variable}
        current={type}
        locked={locked}
        onBind={onBind}
        ariaLabel={`Choose the type of ${port.name}`}
        trigger={<TypeText text={text} locked={locked} />}
        triggerStyle={extra}
      />
    ) : null;

  let body: React.ReactNode;
  if (approach === "caption") {
    body = (
      <>
        <span {...stylex.props(s.label, input ? null : s.labelOut)}>
          {nameLabel}
          {!generic && port.shape === "many" ? (
            <span {...stylex.props(s.required)}>· many</span>
          ) : null}
        </span>
        {generic ? (
          <span
            {...stylex.props(s.caption, input ? s.captionIn : s.captionOut)}
          >
            {typeButton(
              stylex.props(
                s.typeButton,
                s.captionText,
                bound ? s.typeBound : null,
                locked ? s.typeLocked : null,
              ),
              fullType(port.shape, type),
            )}
          </span>
        ) : null}
      </>
    );
  } else if (approach === "field") {
    body = generic ? (
      <span {...stylex.props(s.field, input ? null : s.fieldOut)}>
        <span {...stylex.props(s.fieldLabel)}>
          {port.name}
          {input && port.required ? " *" : ""}
        </span>
        {typeButton(
          stylex.props(
            s.typeButton,
            s.fieldBox,
            bound ? s.typeBound : null,
            locked ? s.typeLocked : null,
          ),
          fullType(port.shape, type),
        )}
      </span>
    ) : (
      <span {...stylex.props(s.label, input ? null : s.labelOut)}>
        {nameLabel}
        {port.shape === "many" ? (
          <span {...stylex.props(s.required)}>· many</span>
        ) : null}
      </span>
    );
  } else if (approach === "short") {
    body = (
      <span {...stylex.props(s.label, input ? null : s.labelOut)}>
        {nameLabel}
        {generic ? (
          typeButton(
            stylex.props(
              s.typeButton,
              bound ? s.typeBound : null,
              locked ? s.typeLocked : null,
            ),
            shortType(port.shape, type),
          )
        ) : (
          <span {...stylex.props(s.mono, s.subtle)}>
            {shortType(port.shape, type)}
          </span>
        )}
      </span>
    );
  } else if (approach === "tag") {
    body = (
      <>
        <span {...stylex.props(s.label, input ? null : s.labelOut)}>
          {nameLabel}
          {port.shape === "many" && !generic ? (
            <span {...stylex.props(s.required)}>· many</span>
          ) : null}
        </span>
        {generic ? (
          <span {...stylex.props(s.tag, input ? s.tagIn : s.tagOut)}>
            {typeButton(
              {
                ...stylex.props(
                  s.typeButton,
                  s.tagPill,
                  bound ? s.typeBound : null,
                  locked ? s.typeLocked : null,
                ),
                style: { borderColor: colorOf(type) },
              },
              shortType(port.shape, type),
            )}
          </span>
        ) : null}
      </>
    );
  } else if (approach === "signature") {
    body = (
      <span {...stylex.props(s.label, input ? null : s.labelOut)}>
        {nameLabel}
        {generic ? (
          <span {...stylex.props(s.mono, s.subtle)}>
            {`: ${port.variable}${port.shape === "many" ? "[]" : ""}`}
          </span>
        ) : port.shape === "many" ? (
          <span {...stylex.props(s.required)}>· many</span>
        ) : null}
      </span>
    );
  } else {
    body = (
      <span {...stylex.props(s.label, input ? null : s.labelOut)}>
        {nameLabel}
        {port.shape === "many" ? (
          <span {...stylex.props(s.required)}>· many</span>
        ) : null}
      </span>
    );
  }

  return (
    <div {...stylex.props(s.cell, input ? null : s.cellOut)}>
      {body}
      <Ball ctx={ctx} port={port} type={type} />
    </div>
  );
}

function SignatureParams({ ctx }: { ctx: NodeContext }) {
  const variables = [
    ...new Set(
      [...ctx.node.inputs, ...ctx.node.outputs].flatMap((port) =>
        port.variable ? [port.variable] : [],
      ),
    ),
  ];
  if (!variables.length) return null;
  return (
    <span {...stylex.props(s.params)}>
      ‹
      {variables.map((variable, index) => {
        const type = ctx.bindings[variable];
        return (
          <span key={variable} {...stylex.props(s.param)}>
            {index ? ", " : null}
            <span {...stylex.props(s.paramName)}>{variable}</span>:
            <TypeMenu
              variable={variable}
              current={type}
              locked={ctx.locked}
              onBind={ctx.onBind}
              ariaLabel={`Choose type ${variable}`}
              trigger={
                <TypeText text={shortType("one", type)} locked={ctx.locked} />
              }
              triggerStyle={stylex.props(
                s.typeButton,
                type ? s.typeBound : null,
                ctx.locked ? s.typeLocked : null,
              )}
            />
          </span>
        );
      })}
      ›
    </span>
  );
}

function SpikeNodeCard({ ctx }: { ctx: NodeContext }) {
  const rows = Math.max(ctx.node.inputs.length, ctx.node.outputs.length);
  return (
    <div {...stylex.props(s.node)}>
      <WireLayer ctx={ctx} />
      <div {...stylex.props(s.nameRow)}>
        <span {...stylex.props(s.name)}>{ctx.node.title}</span>
        {ctx.approach === "signature" ? <SignatureParams ctx={ctx} /> : null}
      </div>
      <div {...stylex.props(s.plate)}>
        {Array.from({ length: rows }, (_, index) => {
          const input = ctx.node.inputs[index];
          const output = ctx.node.outputs[index];
          return (
            <div key={index} {...stylex.props(s.row)}>
              <div>{input ? <PortCell ctx={ctx} port={input} /> : null}</div>
              <div>{output ? <PortCell ctx={ctx} port={output} /> : null}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function PortTypesSpike() {
  const [approach, setApproach] = React.useState<ApproachId>("caption");
  const [locked, setLocked] = React.useState(false);
  const [edges, setEdges] = React.useState<EdgeMode>("none");
  const stage = stylex.props(
    edges === "none" ? s.sceneStage : s.sceneStageWired,
  );
  const [bindings, setBindings] = React.useState(INITIAL_BINDINGS);
  const active = APPROACHES.find((candidate) => candidate.id === approach);

  const bindFor =
    (nodeKey: string) => (variable: string, type: TypeKey | undefined) =>
      setBindings((current) => ({
        ...current,
        [nodeKey]: { ...current[nodeKey], [variable]: type },
      }));

  const card = (node: SpikeNode, as: Approach) => (
    <SpikeNodeCard
      ctx={{
        approach: as,
        node,
        bindings: wiredBindings(node, bindings[node.key] ?? {}, edges),
        // A wire fixes a node's generic types, as on the canvas.
        locked: locked || edges !== "none",
        edges,
        onBind: bindFor(node.key),
      }}
    />
  );

  return (
    <SandboxShell
      title="Port types"
      note={active?.note ?? ""}
      variants={APPROACHES}
      activeVariant={approach}
      onVariant={(id) => setApproach(id as ApproachId)}
    >
      <div {...stylex.props(s.controls)}>
        <button
          type="button"
          aria-pressed={locked}
          {...stylex.props(s.toggle, locked ? s.toggleOn : null)}
          onClick={() => setLocked((value) => !value)}
        >
          {locked ? "Wired: types fixed" : "Free: types can be chosen"}
        </button>
        <span role="group" aria-label="Edges" {...stylex.props(s.segmented)}>
          <span {...stylex.props(s.segmentedLabel)}>Edges</span>
          {(
            [
              ["none", "None"],
              ["inputs", "Inputs wired"],
              ["all", "All wired"],
            ] as const
          ).map(([mode, label]) => (
            <button
              key={mode}
              type="button"
              aria-pressed={edges === mode}
              {...stylex.props(s.segment, edges === mode ? s.segmentOn : null)}
              onClick={() => setEdges(mode)}
            >
              {label}
            </button>
          ))}
        </span>
        <button
          type="button"
          {...stylex.props(s.toggle)}
          onClick={() => setBindings(INITIAL_BINDINGS)}
        >
          Reset types
        </button>
      </div>
      {approach === "compare" ? (
        <div {...stylex.props(s.compareGrid)}>
          {APPROACHES.filter(
            (
              candidate,
            ): candidate is (typeof APPROACHES)[number] & {
              id: Approach;
            } => candidate.id !== "compare",
          ).map((candidate) => (
            <section key={candidate.id} {...stylex.props(s.compareCell)}>
              <span {...stylex.props(s.compareTitle)}>{candidate.label}</span>
              <span {...stylex.props(s.compareNote)}>{candidate.note}</span>
              <div {...stylex.props(s.compareNodes)}>
                <div {...stage}>{card(NODES[0], candidate.id)}</div>
                <div {...stage}>{card(NODES[1], candidate.id)}</div>
              </div>
            </section>
          ))}
        </div>
      ) : (
        <div {...stylex.props(s.scenes)}>
          {NODES.map((node) => (
            <section key={node.key} {...stylex.props(s.scene)}>
              <span
                {...stylex.props(
                  s.sceneLabel,
                  edges === "none" ? s.sceneStage : s.sceneStageWired,
                )}
              >
                {node.key === "add"
                  ? "No generics (control)"
                  : node.key === "pair"
                    ? "Two different generics"
                    : node.key === "interpret"
                      ? "Generic output"
                      : "One generic sequence input"}
              </span>
              <div {...stage}>{card(node, approach as Approach)}</div>
            </section>
          ))}
        </div>
      )}
    </SandboxShell>
  );
}
