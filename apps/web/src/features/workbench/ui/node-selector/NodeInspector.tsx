"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import type { StyleXStyles } from "@stylexjs/stylex";
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  Cable,
  ChevronRight,
  CornerDownLeft,
  Plus,
  Settings2,
  Workflow,
} from "lucide-react";

import type { NodeRegistry, NodeSpec, Port } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { schemaFields, type SchemaField } from "../../canvas/config-schema";
import { artifactTypeColor } from "../../canvas/nodes.css";
import {
  formatArtifactTypeLabel,
  formatArtifactTypeTooltip,
} from "../../canvas/artifact-type-label";
import {
  acceptedPortShapes,
  portArtifactType,
  portArtifactTypeVariable,
  portHasInstancePlugs,
} from "../../canvas/types";
import { catalogNodeKey, catalogPlugin } from "../../model/node-catalog";
import {
  artifactTitleFor,
  CatalogNodePreview,
  fieldTypeLabel,
  portKey,
} from "../CatalogNodePreview";
import {
  compatibleNodesForPort,
  type CompatibleNode,
} from "./node-compatibility";

export const INSPECTOR_TITLE_ID = "node-selector-inspector-title";
const INSERT_DISABLED_REASON_ID = "node-selector-insert-disabled-reason";

/**
 * The node the picker would add, shown as it will sit on the canvas, then what
 * it takes and makes, what it can be wired to, and the action that adds it.
 *
 * Mount it with `key={catalogNodeKey(spec)}`: which port "Works with" follows
 * belongs to one node.
 */
export function NodeInspector({
  spec,
  registry,
  catalogRegistry,
  detailsOpen,
  canInsert,
  insertDisabledReason,
  showEnterHint,
  leading,
  onDetailsOpenChange,
  onInspect,
  onInsert,
}: {
  spec: NodeSpec;
  registry: NodeRegistry;
  /** The registry narrowed to what the picker lists; "Works with" suggests from it. */
  catalogRegistry: NodeRegistry;
  /** Settings, ports and what the node works with, folded away by default. */
  detailsOpen: boolean;
  canInsert: boolean;
  insertDisabledReason: string;
  showEnterHint: boolean;
  /** Placed above the preview: the phone layout's way back to the results. */
  leading?: React.ReactNode;
  onDetailsOpenChange: (open: boolean) => void;
  onInspect: (spec: NodeSpec) => void;
  onInsert: () => void;
}) {
  const fields = React.useMemo(() => schemaFields(spec.config_schema), [spec]);
  const ports = React.useMemo(
    () => [...spec.inputs, ...spec.outputs],
    [spec.inputs, spec.outputs],
  );
  const [chosenPortKey, setChosenPortKey] = React.useState<string | null>(null);
  const activePort =
    ports.find((port) => portKey(port) === chosenPortKey) ?? ports[0] ?? null;
  const matches = React.useMemo(
    () =>
      activePort
        ? compatibleNodesForPort(spec, activePort, catalogRegistry)
        : [],
    [activePort, catalogRegistry, spec],
  );
  // The catalog lists only what this deployment executes, so the one entry that
  // arrives not runnable is a canvas reconstruction of a saved operator that is
  // no longer in the live registry.
  const insertable = canInsert && spec.runnable !== false;
  const unavailableReason =
    "This saved operator is not in the live registry, so it cannot be inserted.";
  const disabledReason = canInsert ? unavailableReason : insertDisabledReason;
  const description =
    spec.description || "No description is available for this node.";
  const selectPort = (port: Port) => setChosenPortKey(portKey(port));

  return (
    <>
      {leading}
      <div
        {...stylex.props(s.body)}
        className={withGlobal(s.body, "grafy-node-detail")}
      >
        <div
          {...stylex.props(s.previewStage)}
          className={withGlobal(s.previewStage, "grafy-node-preview-stage")}
        >
          <CatalogNodePreview
            spec={spec}
            registry={registry}
            fields={fields}
            selectedPortKey={activePort ? portKey(activePort) : null}
            onSelectPort={selectPort}
          />
        </div>
        <div {...stylex.props(s.scroll)}>
          <header {...stylex.props(s.header)}>
            <h3 id={INSPECTOR_TITLE_ID} {...stylex.props(s.title)}>
              {spec.title}
            </h3>
            <p {...stylex.props(s.description)}>{description}</p>
            {spec.runnable === false ? (
              <p {...stylex.props(s.note)}>Catalog preview only.</p>
            ) : null}
            <PortChips spec={spec} registry={registry} />
          </header>

          <button
            type="button"
            aria-expanded={detailsOpen}
            onClick={() => onDetailsOpenChange(!detailsOpen)}
            {...stylex.props(s.disclosure)}
          >
            <ChevronRight
              size={13}
              aria-hidden="true"
              {...stylex.props(
                s.disclosureChevron,
                detailsOpen ? s.disclosureChevronOpen : null,
              )}
            />
            Details
            <span {...stylex.props(s.disclosureHint)}>
              {detailsSummary(fields.length, ports.length)}
            </span>
          </button>

          {detailsOpen ? (
            <div {...stylex.props(s.details)}>
              {fields.length ? (
                <section {...stylex.props(s.section)}>
                  <SectionTitle icon={Settings2}>Settings</SectionTitle>
                  <FieldList fields={fields} />
                </section>
              ) : null}
              <section {...stylex.props(s.section)}>
                <SectionTitle icon={Workflow}>Ports</SectionTitle>
                <p {...stylex.props(s.mono)}>
                  {spec.operator_id}@{spec.operator_version}
                </p>
                <div {...stylex.props(s.portGrid)}>
                  <PortList
                    direction="input"
                    ports={spec.inputs}
                    registry={registry}
                  />
                  <PortList
                    direction="output"
                    ports={spec.outputs}
                    registry={registry}
                  />
                </div>
              </section>
              {activePort ? (
                <WorksWith
                  ports={ports}
                  activePort={activePort}
                  matches={matches}
                  registry={registry}
                  onSelectPort={selectPort}
                  onInspect={onInspect}
                />
              ) : null}
            </div>
          ) : null}
        </div>
      </div>

      <footer {...stylex.props(s.footer)}>
        {insertable ? null : (
          <span
            id={INSERT_DISABLED_REASON_ID}
            {...stylex.props(s.visuallyHidden)}
          >
            {disabledReason}
          </span>
        )}
        <Button
          type="button"
          variant="primary"
          size="lg"
          disabled={!insertable}
          aria-describedby={insertable ? undefined : INSERT_DISABLED_REASON_ID}
          title={
            insertable ? `Add ${spec.title} to the canvas` : disabledReason
          }
          onClick={onInsert}
          xstyle={s.addButton}
        >
          <Plus size={14} aria-hidden="true" />
          Add to canvas
          {showEnterHint && insertable ? (
            <kbd aria-hidden="true" {...stylex.props(s.kbd)}>
              <CornerDownLeft size={11} />
            </kbd>
          ) : null}
        </Button>
      </footer>
    </>
  );
}

/** StyleX classes plus a global hook the app stylesheet animates. */
function withGlobal(style: StyleXStyles, globalClass: string): string {
  return [stylex.props(style).className, globalClass].filter(Boolean).join(" ");
}

function SectionTitle({
  icon: Icon,
  children,
}: {
  icon: typeof Workflow;
  children: React.ReactNode;
}) {
  return (
    <div {...stylex.props(s.sectionTitleRow)}>
      <Icon size={13} aria-hidden="true" {...stylex.props(s.sectionIcon)} />
      <h3 {...stylex.props(s.sectionTitle)}>{children}</h3>
    </div>
  );
}

function detailsSummary(fieldCount: number, portCount: number): string {
  const parts = [
    fieldCount ? `${fieldCount} setting${fieldCount === 1 ? "" : "s"}` : null,
    portCount ? `${portCount} port${portCount === 1 ? "" : "s"}` : null,
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : "Ports and connections";
}

/** What the node takes and makes, one chip per port, in the canvas's colours. */
function PortChips({
  spec,
  registry,
}: {
  spec: NodeSpec;
  registry: NodeRegistry;
}) {
  return (
    <div {...stylex.props(s.flow)}>
      <PortChipGroup
        label="Takes"
        ports={spec.inputs}
        registry={registry}
        none="Nothing — it starts a workflow"
      />
      <PortChipGroup
        label="Makes"
        ports={spec.outputs}
        registry={registry}
        none="Nothing — it ends a branch"
      />
    </div>
  );
}

function PortChipGroup({
  label,
  ports,
  registry,
  none,
}: {
  label: string;
  ports: readonly Port[];
  registry: NodeRegistry;
  none: string;
}) {
  return (
    <div {...stylex.props(s.flowRow)}>
      <span {...stylex.props(s.flowLabel)}>{label}</span>
      {ports.length ? (
        <span {...stylex.props(s.chips)}>
          {ports.map((port) => {
            const artifactType = portArtifactType(port);
            const many = port.shape === "many";
            const type = artifactTitleFor(registry, port);
            return (
              <span
                key={port.name}
                title={`${port.title ?? port.name}: ${type}${many ? " · sequence" : ""}`}
                {...stylex.props(s.chip)}
              >
                <span
                  aria-hidden="true"
                  {...stylex.props(s.chipDot, many && s.chipDotMany)}
                  style={{
                    color: artifactType
                      ? artifactTypeColor(artifactType.id, tokens.colorSubtle)
                      : tokens.colorSubtle,
                  }}
                />
                {type}
                {many ? (
                  <span {...stylex.props(s.chipMany)}>sequence</span>
                ) : null}
              </span>
            );
          })}
        </span>
      ) : (
        <span {...stylex.props(s.flowNone)}>{none}</span>
      )}
    </div>
  );
}

function PortList({
  direction,
  ports,
  registry,
}: {
  direction: "input" | "output";
  ports: readonly Port[];
  registry: NodeRegistry;
}) {
  const input = direction === "input";
  return (
    <div>
      <h4 {...stylex.props(s.columnHeading)}>
        {input ? (
          <ArrowDownToLine size={12} aria-hidden="true" />
        ) : (
          <ArrowUpFromLine size={12} aria-hidden="true" />
        )}
        {input ? "Inputs" : "Outputs"} · {ports.length}
      </h4>
      {ports.length ? (
        <div {...stylex.props(s.list)}>
          {ports.map((port) => (
            <PortRow
              key={`${direction}-${port.name}`}
              port={port}
              registry={registry}
            />
          ))}
        </div>
      ) : (
        <p {...stylex.props(s.empty)}>
          {input
            ? "No inputs. This node can start a workflow."
            : "No outputs. This node finishes a branch."}
        </p>
      )}
    </div>
  );
}

function PortRow({ port, registry }: { port: Port; registry: NodeRegistry }) {
  const artifactType = portArtifactType(port);
  const contract = artifactType
    ? formatArtifactTypeLabel(artifactType, registry.artifact_types)
    : (portArtifactTypeVariable(port) ?? "generic");
  const contractTooltip = artifactType
    ? formatArtifactTypeTooltip(artifactType)
    : undefined;
  const shapes = acceptedPortShapes(port)
    .map((shape) => (shape === "many" ? "sequence" : "single value"))
    .join(" or ");
  const rules = [
    port.required ? "required" : "optional",
    shapes,
    portHasInstancePlugs(port)
      ? "ordered input plugs"
      : port.variadic
        ? "multiple connections"
        : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div {...stylex.props(s.portRow)}>
      <span
        aria-hidden="true"
        {...stylex.props(s.portDot)}
        style={{
          backgroundColor: artifactType
            ? artifactTypeColor(artifactType.id, tokens.colorAccent)
            : tokens.colorAccent,
        }}
      />
      <div {...stylex.props(s.minZero)}>
        <div {...stylex.props(s.rowTitle)}>{port.title ?? port.name}</div>
        <div title={contractTooltip} {...stylex.props(s.contract)}>
          {artifactTitleFor(registry, port)} · {contract}
        </div>
        <div {...stylex.props(s.rules)}>{rules}</div>
        {port.description ? (
          <p {...stylex.props(s.rowDescription)}>{port.description}</p>
        ) : null}
      </div>
    </div>
  );
}

function FieldList({ fields }: { fields: readonly SchemaField[] }) {
  if (!fields.length) {
    return (
      <p {...stylex.props(s.empty)}>
        No editable scalar settings are declared. Upload or custom controls,
        when available, appear on the node after it is added.
      </p>
    );
  }
  return (
    <div {...stylex.props(s.list)}>
      {fields.map((field) => (
        <div key={field.name} {...stylex.props(s.fieldRow)}>
          <div {...stylex.props(s.minZero)}>
            <div {...stylex.props(s.rowTitle)}>{field.title}</div>
            <div {...stylex.props(s.contract)}>{field.name}</div>
          </div>
          <div {...stylex.props(s.minZero)}>
            <div {...stylex.props(s.rules)}>
              {fieldTypeLabel(field)} · {fieldConstraintLabel(field)}
            </div>
            {field.description ? (
              <p {...stylex.props(s.rowDescription)}>{field.description}</p>
            ) : null}
            {field.enumValues?.length ? (
              <p {...stylex.props(s.choices)}>
                Choices: {field.enumValues.map(String).join(", ")}
              </p>
            ) : null}
            {field.pattern ? (
              <p {...stylex.props(s.choices)}>Pattern: {field.pattern}</p>
            ) : null}
          </div>
        </div>
      ))}
    </div>
  );
}

function rangeLabel(
  min: number | undefined,
  max: number | undefined,
  unit = "",
): string | null {
  const suffix = unit ? ` ${unit}` : "";
  if (min !== undefined && max !== undefined) return `${min}–${max}${suffix}`;
  if (min !== undefined) return `min ${min}${suffix}`;
  if (max !== undefined) return `max ${max}${suffix}`;
  return null;
}

export function fieldConstraintLabel(field: SchemaField): string {
  const constraints =
    field.type === "string-list"
      ? [
          rangeLabel(field.minItems, field.maxItems, "items"),
          rangeLabel(
            field.itemMinLength,
            field.itemMaxLength,
            "characters per item",
          ),
        ]
      : [
          rangeLabel(field.minimum, field.maximum),
          rangeLabel(field.minLength, field.maxLength, "characters"),
        ];
  return [field.required ? "required" : "optional", ...constraints]
    .filter((part): part is string => part !== null)
    .join(" · ");
}

function portScopeLabel(port: Port): string {
  return `${port.title ?? port.name} ${port.direction === "input" ? "input" : "output"}`;
}

function WorksWith({
  ports,
  activePort,
  matches,
  registry,
  onSelectPort,
  onInspect,
}: {
  ports: readonly Port[];
  activePort: Port;
  matches: readonly CompatibleNode[];
  registry: NodeRegistry;
  onSelectPort: (port: Port) => void;
  onInspect: (spec: NodeSpec) => void;
}) {
  return (
    <section {...stylex.props(s.section)}>
      <div {...stylex.props(s.worksWithHeader)}>
        <Cable size={13} aria-hidden="true" {...stylex.props(s.sectionIcon)} />
        <h3 {...stylex.props(s.sectionTitle)}>Works with:</h3>
        {ports.length > 1 ? (
          <select
            aria-label="Works with port"
            value={portKey(activePort)}
            onChange={(event) => {
              const next = ports.find(
                (port) => portKey(port) === event.currentTarget.value,
              );
              if (next) onSelectPort(next);
            }}
            {...stylex.props(s.worksWithPort, s.worksWithSelect)}
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
      {matches.length ? (
        <div {...stylex.props(s.list)}>
          {matches.map((match) => (
            <button
              key={catalogNodeKey(match.spec)}
              type="button"
              aria-label={`Inspect ${match.spec.title}`}
              onClick={() => onInspect(match.spec)}
              {...stylex.props(s.match)}
            >
              <span {...stylex.props(s.matchName)}>{match.spec.title}</span>
              <span {...stylex.props(s.matchMeta)}>
                {catalogPlugin(registry, match.spec.plugin_slug).title} ·{" "}
                {match.routeSummary}
                {match.additionalRouteCount > 0
                  ? ` · +${match.additionalRouteCount} route${match.additionalRouteCount === 1 ? "" : "s"}`
                  : ""}
              </span>
            </button>
          ))}
        </div>
      ) : (
        <p {...stylex.props(s.empty)}>
          {activePort.direction === "input"
            ? "No registered node currently provides a compatible output."
            : "No registered node currently accepts this output."}
        </p>
      )}
    </section>
  );
}

const MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";
const s = stylex.create({
  body: {
    minHeight: 0,
    flex: 1,
    display: "flex",
    flexDirection: "column",
  },
  previewStage: {
    flexShrink: 0,
    maxHeight: "40%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "18px 14px",
    overflow: "auto",
  },
  scroll: { minHeight: 0, flex: 1, overflowY: "auto" },
  header: {
    display: "grid",
    justifyItems: "start",
    gap: "8px",
    padding: "4px 20px 16px",
  },
  title: {
    margin: 0,
    color: tokens.colorTextEmphasis,
    fontSize: "17px",
    fontWeight: 680,
    letterSpacing: "-0.015em",
    lineHeight: 1.25,
  },
  description: {
    maxWidth: "68ch",
    margin: 0,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.55,
  },
  note: {
    margin: 0,
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
  mono: {
    margin: 0,
    color: tokens.colorSubtle,
    fontFamily: MONO,
    fontSize: tokens.fontSizeXs,
  },

  disclosure: {
    width: "calc(100% - 24px)",
    minHeight: { default: "34px", "@media (pointer: coarse)": "44px" },
    display: "flex",
    alignItems: "center",
    gap: "6px",
    margin: "0 12px",
    padding: "0 8px",
    borderWidth: 0,
    borderTopWidth: 1,
    borderStyle: "solid",
    borderTopColor: tokens.colorDivider,
    borderRadius: 0,
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: { default: tokens.colorText, ":hover": tokens.colorTextEmphasis },
    cursor: "pointer",
    fontFamily: "inherit",
    fontSize: tokens.fontSizeSm,
    fontWeight: 600,
    textAlign: "left",
    outlineColor: tokens.colorAccent,
    outlineStyle: "solid",
    outlineOffset: "-2px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
  },
  disclosureHint: {
    marginLeft: "auto",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    fontWeight: 500,
  },
  details: { paddingBottom: "8px" },
  flow: { display: "grid", gap: "6px", marginTop: "4px" },
  flowRow: {
    display: "flex",
    alignItems: "baseline",
    gap: "10px",
    fontSize: tokens.fontSizeSm,
  },
  flowLabel: {
    width: "44px",
    flexShrink: 0,
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    fontWeight: 600,
  },
  flowNone: { color: tokens.colorSubtle, fontSize: tokens.fontSizeXs },
  chips: { display: "flex", flexWrap: "wrap", gap: "4px" },
  chip: {
    display: "inline-flex",
    alignItems: "center",
    gap: "5px",
    height: "22px",
    paddingInline: "8px",
    borderRadius: "99px",
    backgroundColor: tokens.colorSurfaceSunken,
    color: tokens.colorText,
    fontSize: tokens.fontSizeXs,
    whiteSpace: "nowrap",
  },
  chipDot: {
    width: "7px",
    height: "7px",
    flexShrink: 0,
    borderRadius: "99px",
    backgroundColor: "currentColor",
  },
  chipDotMany: { marginRight: "3px", boxShadow: "3px 0 0 -1px currentColor" },
  chipMany: { color: tokens.colorSubtle },
  disclosureChevron: { transition: "transform 140ms ease" },
  disclosureChevronOpen: { transform: "rotate(90deg)" },
  section: {
    margin: "0 12px",
    padding: "12px 8px",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
  },
  sectionTitleRow: {
    display: "flex",
    alignItems: "center",
    gap: "7px",
    marginBottom: "10px",
  },
  sectionIcon: { flexShrink: 0, color: tokens.colorSubtle },
  sectionTitle: {
    flexShrink: 0,
    margin: 0,
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeSm,
    fontWeight: 740,
  },
  portGrid: {
    display: "grid",
    gridTemplateColumns: {
      default: "repeat(2, minmax(0, 1fr))",
      "@media (max-width: 900px)": "1fr",
    },
    gap: "18px",
    marginTop: "10px",
  },
  columnHeading: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
    margin: "0 0 4px",
    color: tokens.colorSubtle,
    fontSize: "10px",
    fontWeight: 800,
    letterSpacing: "0.09em",
    textTransform: "uppercase",
  },
  list: { display: "grid" },
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
  minZero: { minWidth: 0 },
  rowTitle: {
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    fontWeight: 680,
  },
  contract: {
    marginTop: "2px",
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontFamily: MONO,
    fontSize: "10px",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  rules: { marginTop: "3px", color: tokens.colorSubtle, fontSize: "10px" },
  rowDescription: {
    margin: "5px 0 0",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
  choices: {
    margin: "4px 0 0",
    overflowWrap: "anywhere",
    color: tokens.colorSubtle,
    fontSize: "10px",
  },
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
  empty: {
    margin: 0,
    padding: "8px 0",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
  worksWithHeader: {
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    gap: "8px",
    marginBottom: "8px",
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
  worksWithSelect: {
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
  match: {
    width: "100%",
    display: "grid",
    gap: "2px",
    padding: "8px 6px",
    marginInline: "-6px",
    borderWidth: 0,
    borderRadius: tokens.radiusSm,
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: tokens.colorText,
    cursor: "pointer",
    fontFamily: "inherit",
    textAlign: "left",
    outlineColor: tokens.colorAccent,
    outlineStyle: "solid",
    outlineOffset: "-2px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
  },
  matchName: {
    overflow: "hidden",
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    fontWeight: 680,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  matchMeta: {
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontSize: "10px",
    lineHeight: 1.4,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  footer: {
    flexShrink: 0,
    display: "grid",
    padding: "12px 16px 14px",
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
  /**
   * The kit's `Button lg` is 36px on a desktop and this is the one action a person
   * aims at in this panel, so its floor stays. It is expressed as `min-height`,
   * the one property a call site may set beside the kit's `height` without StyleX
   * throwing the kit's own size away — see `components/ui/touch-target.ts`.
   */
  addButton: {
    width: "100%",
    minHeight: "44px",
    overflow: "hidden",
  },
  kbd: {
    display: "inline-grid",
    placeItems: "center",
    minWidth: "18px",
    height: "18px",
    marginLeft: "2px",
    borderRadius: "4px",
    backgroundColor: "color-mix(in srgb, currentColor 16%, transparent)",
    fontFamily: "inherit",
  },
});
