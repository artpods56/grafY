"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Popover } from "@base-ui/react/popover";
import { ChevronRight } from "lucide-react";

import { useNodeRegistry } from "@/hooks/use-api";
import { useWorkspaceContext } from "@/features/workspaces/WorkspaceLayout";
import type { Port } from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { overlay } from "@/lib/stylex/overlay.stylex";
import {
  portArtifactTypeVariable,
  resolvedPortArtifactType,
  type WorkflowArtifactTypeBindings,
} from "../types";
import {
  findOutlineNode,
  outlineCrumbLabel,
  schemaOutline,
  schemaTitle,
  schemaTypeLabel,
  type OutlineNode,
} from "./schema-outline";

export { schemaTypeLabel };

/**
 * Port type inspector — a popover that drills one object at a time through
 * the artifact payload schema. Informative only: it does not start
 * connections or pick a projection.
 */

const PORT_POPOVER_OFFSET = 24;

function canvasOverlayProps(props: ReturnType<typeof stylex.props>) {
  return {
    ...props,
    className: `nodrag nowheel${props.className ? ` ${props.className}` : ""}`,
  };
}

const s = stylex.create({
  positioner: { zIndex: 90 },
  popup: {
    width: "min(360px, calc(100vw - 24px))",
    maxHeight: "calc(100dvh - 32px)",
    display: "grid",
    gridTemplateRows: "auto minmax(0, 1fr)",
    overflow: "hidden",
  },
  header: {
    display: "grid",
    gap: "4px",
    padding: "11px 14px 10px",
  },
  contract: {
    color: tokens.colorSubtle,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: tokens.fontSizeXs,
    fontWeight: 700,
  },
  description: {
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
  section: {
    minHeight: 0,
    display: "grid",
    gridTemplateRows: "auto minmax(0, 1fr)",
    padding: "10px 14px 14px",
    overflow: "hidden",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
  },
  tree: {
    minHeight: 0,
    display: "grid",
    gap: "1px",
    maxHeight: "360px",
    overflowY: "auto",
    overscrollBehaviorY: "contain",
  },
  row: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    minHeight: "26px",
    width: "100%",
    padding: "3px 8px",
    borderWidth: 0,
    borderRadius: tokens.radiusSm,
    backgroundColor: "transparent",
    color: "inherit",
    font: "inherit",
    textAlign: "left",
  },
  rowButton: {
    minHeight: {
      default: "28px",
      "@media (max-width: 620px)": "44px",
    },
    cursor: "pointer",
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorHover,
    },
  },
  fieldName: {
    color: tokens.colorTextEmphasis,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: tokens.fontSizeSm,
  },
  branchName: {
    color: tokens.colorMuted,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: tokens.fontSizeSm,
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
  crumbs: {
    display: "flex",
    flexWrap: "wrap",
    gap: "6px",
    marginBottom: "10px",
    paddingBottom: "8px",
    alignItems: "center",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
  },
  crumb: {
    minHeight: {
      default: "auto",
      "@media (max-width: 620px)": "44px",
    },
    display: "inline-flex",
    alignItems: "center",
    padding: 0,
    borderWidth: 0,
    backgroundColor: "transparent",
    color: tokens.colorMuted,
    cursor: "pointer",
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: tokens.fontSizeXs,
  },
  crumbCurrent: {
    color: tokens.colorTextEmphasis,
    cursor: "default",
  },
  crumbSep: {
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
  },
  empty: {
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
  emptyError: { color: tokens.colorDanger },
});

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

export function SchemaDrill({
  schema,
  rootLabel,
}: {
  schema: Record<string, unknown>;
  rootLabel?: string;
}) {
  const outline = schemaOutline(schema);
  const [path, setPath] = React.useState<string[]>([]);
  const current =
    path.length === 0
      ? undefined
      : findOutlineNode(outline, path[path.length - 1]!);
  const rows = current?.children ?? outline;
  const crumbs = path
    .map((id) => findOutlineNode(outline, id))
    .filter((node): node is OutlineNode => Boolean(node));
  const root = rootLabel ?? schemaTitle(schema);

  if (!outline.length) {
    return (
      <p {...stylex.props(s.empty)}>
        No declared payload schema — this artifact carries opaque content.
      </p>
    );
  }

  return (
    <>
      <nav aria-label="Payload schema path" {...stylex.props(s.crumbs)}>
        <button
          type="button"
          aria-current={path.length === 0 ? "page" : undefined}
          {...stylex.props(s.crumb, path.length === 0 ? s.crumbCurrent : null)}
          onClick={() => setPath([])}
        >
          {root}
        </button>
        {crumbs.map((node, index) => (
          <React.Fragment key={node.id}>
            <span {...stylex.props(s.crumbSep)}>/</span>
            <button
              type="button"
              aria-current={index === crumbs.length - 1 ? "page" : undefined}
              {...stylex.props(
                s.crumb,
                index === crumbs.length - 1 ? s.crumbCurrent : null,
              )}
              onClick={() => setPath(path.slice(0, index + 1))}
            >
              {outlineCrumbLabel(node)}
            </button>
          </React.Fragment>
        ))}
      </nav>
      <div
        role="region"
        aria-label="Payload schema fields"
        {...canvasOverlayProps(stylex.props(s.tree))}
      >
        {rows.map((node) =>
          node.expandable ? (
            <button
              key={node.id}
              type="button"
              {...stylex.props(s.row, s.rowButton)}
              onClick={() => setPath([...path, node.id])}
            >
              <TypeMark node={node} />
              <span {...stylex.props(s.chevron)}>
                <ChevronRight size={13} />
              </span>
            </button>
          ) : (
            <div key={node.id} {...stylex.props(s.row)}>
              <TypeMark node={node} />
            </div>
          ),
        )}
      </div>
    </>
  );
}

export function PortTypePopover({
  port,
  shape,
  artifactTypeBindings = {},
  open,
  onOpenChange,
  children,
}: {
  port: Port;
  shape: Port["shape"];
  artifactTypeBindings?: WorkflowArtifactTypeBindings;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  children: React.ReactNode;
}) {
  const { workspace } = useWorkspaceContext();
  const {
    data: registry,
    error: registryError,
    isLoading: registryLoading,
  } = useNodeRegistry(workspace.id);
  const artifactType = resolvedPortArtifactType(port, artifactTypeBindings);
  const variable = portArtifactTypeVariable(port);
  const spec = artifactType
    ? registry?.artifact_types.find(
        (artifact) =>
          artifact.key.id === artifactType.id &&
          artifact.key.schema_version === artifactType.schema_version,
      )
    : undefined;
  const contract = artifactType
    ? `${artifactType.id}@${artifactType.schema_version}`
    : "Any artifact";
  const payloadSchema = (spec?.payload_schema ?? {}) as Record<string, unknown>;
  const rootLabel = schemaTitle(payloadSchema, spec?.title ?? "Payload");

  return (
    <Popover.Root open={open} onOpenChange={onOpenChange}>
      {children}
      <Popover.Portal>
        <Popover.Positioner
          {...stylex.props(s.positioner)}
          side={port.direction === "input" ? "left" : "right"}
          align="start"
          sideOffset={PORT_POPOVER_OFFSET}
          collisionAvoidance={{
            side: "shift",
            align: "shift",
            fallbackAxisSide: "none",
          }}
          collisionPadding={12}
        >
          <Popover.Popup
            {...canvasOverlayProps(stylex.props(overlay.popup, s.popup))}
          >
            <header {...stylex.props(s.header)}>
              <span {...stylex.props(s.contract)}>
                {shape === "many" ? `list[${contract}]` : contract}
              </span>
              {port.description ? (
                <span {...stylex.props(s.description)}>{port.description}</span>
              ) : null}
            </header>
            <section {...stylex.props(s.section)}>
              {!artifactType ? (
                <p {...stylex.props(s.empty)}>
                  This generic port binds to a concrete artifact type when it is
                  connected{variable ? ` (${variable})` : ""}.
                </p>
              ) : registryLoading ? (
                <p {...stylex.props(s.empty)}>Loading payload schema…</p>
              ) : registryError ? (
                <p
                  title={
                    registryError instanceof Error
                      ? registryError.message
                      : undefined
                  }
                  {...stylex.props(s.empty, s.emptyError)}
                >
                  Payload schema unavailable.
                </p>
              ) : spec ? (
                <SchemaDrill
                  key={contract}
                  schema={payloadSchema}
                  rootLabel={rootLabel}
                />
              ) : (
                <p {...stylex.props(s.empty)}>
                  This artifact type is not declared in the current registry.
                </p>
              )}
            </section>
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
  );
}
