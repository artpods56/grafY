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
  ExternalLink,
  Plus,
  Settings2,
  Workflow,
} from "lucide-react";

import type { NodeRegistry, NodeSpec, Port } from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { schemaFields, type SchemaField } from "../../canvas/config-schema";
import { artifactTypeColor } from "../../canvas/nodes.css";
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
  moduleReleases,
  technicalDetailsOpen,
  canInsert,
  insertDisabledReason,
  showEnterHint,
  leading,
  onTechnicalDetailsOpenChange,
  onSelectRelease,
  onInspect,
  onInsert,
  onOpenGraph,
}: {
  spec: NodeSpec;
  registry: NodeRegistry;
  /** The registry narrowed to what the picker lists; "Works with" suggests from it. */
  catalogRegistry: NodeRegistry;
  moduleReleases: readonly NodeSpec[];
  technicalDetailsOpen: boolean;
  canInsert: boolean;
  insertDisabledReason: string;
  showEnterHint: boolean;
  /** Placed above the preview: the phone layout's way back to the results. */
  leading?: React.ReactNode;
  onTechnicalDetailsOpenChange: (open: boolean) => void;
  onSelectRelease: (releaseKey: string) => void;
  onInspect: (spec: NodeSpec) => void;
  onInsert: () => void;
  onOpenGraph?: (graphId: string) => void;
}) {
  const fields = React.useMemo(
    () => schemaFields(spec.config_schema),
    [spec.config_schema],
  );
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
  const plugin = catalogPlugin(registry, spec.plugin_slug);
  const isModule = plugin.entry_kind === "module";
  const catalogOnlyReason =
    spec.non_runnable_detail ??
    "This Plugin release is catalog-only until its isolated runtime is available.";
  const insertable = canInsert && spec.runnable !== false;
  const disabledReason = canInsert ? catalogOnlyReason : insertDisabledReason;
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
            {isModule ? (
              <div {...stylex.props(s.provenance)}>
                <span {...stylex.props(s.eyebrow)}>
                  Module · release {spec.module_graph_revision}
                </span>
                <span {...stylex.props(s.badge)}>
                  {spec.publication_state ?? "published"}
                </span>
              </div>
            ) : null}
            <h3 id={INSPECTOR_TITLE_ID} {...stylex.props(s.title)}>
              {spec.title}
            </h3>
            {isModule ? (
              <ModuleFacts
                spec={spec}
                releases={moduleReleases}
                onSelectRelease={onSelectRelease}
                onOpenGraph={onOpenGraph}
              />
            ) : null}
            <p {...stylex.props(s.description)}>{description}</p>
            {spec.runnable === false ? (
              <p {...stylex.props(s.note)}>
                Catalog preview only. {catalogOnlyReason}
              </p>
            ) : null}
            {isModule ? null : (
              <>
                <NodeSummary spec={spec} registry={registry} fields={fields} />
                <button
                  type="button"
                  aria-expanded={technicalDetailsOpen}
                  onClick={() =>
                    onTechnicalDetailsOpenChange(!technicalDetailsOpen)
                  }
                  {...stylex.props(s.disclosure)}
                >
                  <ChevronRight
                    size={13}
                    aria-hidden="true"
                    {...stylex.props(
                      s.disclosureChevron,
                      technicalDetailsOpen ? s.disclosureChevronOpen : null,
                    )}
                  />
                  Technical details
                </button>
              </>
            )}
          </header>

          {isModule || technicalDetailsOpen ? (
            <>
              <section {...stylex.props(s.section)}>
                <SectionTitle icon={Workflow}>
                  {isModule ? "Module contract" : "Ports"}
                </SectionTitle>
                {isModule ? null : (
                  <p {...stylex.props(s.mono)}>
                    {spec.operator_id}@{spec.operator_version}
                  </p>
                )}
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
              <section {...stylex.props(s.section)}>
                <SectionTitle icon={Settings2}>Configuration</SectionTitle>
                <FieldList fields={fields} />
              </section>
            </>
          ) : null}

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
        <button
          type="button"
          disabled={!insertable}
          aria-describedby={insertable ? undefined : INSERT_DISABLED_REASON_ID}
          title={
            insertable
              ? isModule
                ? `Insert module call for ${spec.title}`
                : `Add ${spec.title} to the canvas`
              : disabledReason
          }
          onClick={onInsert}
          {...stylex.props(
            s.addButton,
            insertable ? null : s.addButtonDisabled,
          )}
        >
          <Plus size={14} aria-hidden="true" />
          {isModule ? "Insert module call" : "Add to canvas"}
          {showEnterHint && insertable ? (
            <kbd aria-hidden="true" {...stylex.props(s.kbd)}>
              <CornerDownLeft size={11} />
            </kbd>
          ) : null}
        </button>
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

function ModuleFacts({
  spec,
  releases,
  onSelectRelease,
  onOpenGraph,
}: {
  spec: NodeSpec;
  releases: readonly NodeSpec[];
  onSelectRelease: (releaseKey: string) => void;
  onOpenGraph?: (graphId: string) => void;
}) {
  const graphId = spec.module_graph_id;
  return (
    <>
      <div {...stylex.props(s.mono)}>
        Module contract · release {spec.module_graph_revision}
      </div>
      {releases.length > 1 ? (
        <label {...stylex.props(s.mono)}>
          Release{" "}
          <select
            aria-label="Module release"
            value={catalogNodeKey(spec)}
            onChange={(event) => onSelectRelease(event.currentTarget.value)}
          >
            {releases.map((release) => (
              <option
                key={catalogNodeKey(release)}
                value={catalogNodeKey(release)}
              >
                Release {release.module_graph_revision}
                {release.is_current_library_release ? " (current)" : ""}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {spec.publication_state === "deprecated" ? (
        <p {...stylex.props(s.note)}>
          This Module is deprecated. New inserts are discouraged; existing pins
          keep working.
        </p>
      ) : null}
      {graphId && onOpenGraph ? (
        <button
          type="button"
          title="Open the saved graph that defines this module"
          onClick={() => onOpenGraph(graphId)}
          {...stylex.props(s.smallButton)}
        >
          <ExternalLink size={10} aria-hidden="true" />
          Open source graph
        </button>
      ) : null}
    </>
  );
}

/** "Accepts … / Produces … / Configuration: …" in words, for a plain node. */
function NodeSummary({
  spec,
  registry,
  fields,
}: {
  spec: NodeSpec;
  registry: NodeRegistry;
  fields: readonly SchemaField[];
}) {
  return (
    <div {...stylex.props(s.summary)}>
      <p {...stylex.props(s.statement)}>
        <PortStatement
          verb="Accepts"
          ports={spec.inputs}
          registry={registry}
          none="Starts a workflow"
        />
      </p>
      <p {...stylex.props(s.statement)}>
        <PortStatement
          verb="Produces"
          ports={spec.outputs}
          registry={registry}
          none="Ends a workflow branch"
        />
      </p>
      <div {...stylex.props(s.configuration)}>
        <span {...stylex.props(s.strong)}>Configuration:</span>
        <span>
          {fields.length
            ? `${fields.map((field) => field.title).join(", ")} ${fields.length === 1 ? "is" : "are"} editable after adding.`
            : "No editable settings."}
        </span>
      </div>
    </div>
  );
}

function PortStatement({
  verb,
  ports,
  registry,
  none,
}: {
  verb: string;
  ports: readonly Port[];
  registry: NodeRegistry;
  none: string;
}) {
  const first = ports[0];
  if (!first) return <>{none}</>;
  const artifactType = portArtifactType(first);
  return (
    <>
      {verb}{" "}
      <span
        {...stylex.props(s.strong)}
        style={{
          color: artifactType
            ? artifactTypeColor(artifactType.id, tokens.colorTextEmphasis)
            : tokens.colorTextEmphasis,
        }}
      >
        {artifactTitleFor(registry, first)}
      </span>
      {ports.length > 1
        ? ` + ${ports.length - 1} more`
        : ` · ${first.shape === "many" ? "sequence" : "single value"}`}
    </>
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
    ? `${artifactType.id}@${artifactType.schema_version}`
    : (portArtifactTypeVariable(port) ?? "generic");
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
        <div {...stylex.props(s.contract)}>
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
  scroll: { minHeight: 0, flex: 1, overflowY: "auto" },
  header: {
    display: "grid",
    justifyItems: "start",
    gap: "6px",
    padding: "14px 16px",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorBorder,
  },
  provenance: { display: "flex", alignItems: "center", gap: "7px" },
  eyebrow: {
    color: tokens.colorAccent,
    fontSize: "10px",
    fontWeight: 820,
    letterSpacing: "0.11em",
    textTransform: "uppercase",
  },
  badge: {
    minHeight: "17px",
    display: "inline-flex",
    alignItems: "center",
    paddingInline: "6px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorderStrong,
    borderRadius: "99px",
    backgroundColor: tokens.colorSurfaceSunken,
    color: tokens.colorMuted,
    fontSize: "9px",
    fontWeight: 760,
    letterSpacing: "0.06em",
    lineHeight: 1,
    textTransform: "uppercase",
    whiteSpace: "nowrap",
  },
  title: {
    margin: 0,
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeLg,
    fontWeight: 740,
    letterSpacing: "-0.015em",
    lineHeight: 1.2,
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
  smallButton: {
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
    fontSize: "10px",
    fontWeight: 700,
    outlineColor: tokens.colorAccent,
    outlineStyle: "solid",
    outlineOffset: "2px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
  },
  summary: { display: "grid", gap: "6px", marginTop: "4px" },
  statement: {
    margin: 0,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.5,
  },
  strong: { color: tokens.colorTextEmphasis, fontWeight: 680 },
  configuration: {
    display: "grid",
    gap: "2px",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.5,
  },
  disclosure: {
    minHeight: { default: "28px", "@media (max-width: 720px)": "44px" },
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
    marginTop: "2px",
    marginLeft: "-4px",
    paddingInline: "4px 8px",
    borderWidth: 0,
    borderRadius: tokens.radiusSm,
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: { default: tokens.colorMuted, ":hover": tokens.colorText },
    cursor: "pointer",
    fontSize: tokens.fontSizeXs,
    fontWeight: 680,
    outlineColor: tokens.colorAccent,
    outlineStyle: "solid",
    outlineOffset: "2px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
  },
  disclosureChevron: { transition: "transform 140ms ease" },
  disclosureChevronOpen: { transform: "rotate(90deg)" },
  section: {
    padding: "16px",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorBorder,
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
    padding: "10px 16px",
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
    fontSize: tokens.fontSizeSm,
    fontWeight: 720,
    whiteSpace: "nowrap",
    outlineColor: tokens.colorAccent,
    outlineStyle: "solid",
    outlineOffset: "2px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
  },
  addButtonDisabled: {
    backgroundColor: {
      default: tokens.colorAccentDisabled,
      ":hover": tokens.colorAccentDisabled,
    },
    color: tokens.colorTextDisabled,
    cursor: "not-allowed",
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
