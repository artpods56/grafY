"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Trash2 } from "lucide-react";

import { IconButton } from "@/components/ui/button";
import { Field, TextInput } from "@/components/ui/field";
import { artifactTypeTitle } from "../canvas/artifact-type-label";
import type {
  NodeRegistry,
  NodeSpec,
  SavedGraphAgent,
  SavedGraphNode,
} from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";
import {
  ARTIFACT_DROP_DATA_TYPE,
  readArtifactDrop,
} from "../model/artifact-drop";
import {
  cardContext,
  libraryItemContext,
  newToolLink,
  nodeOutputContext,
  toolPortChoices,
  withoutContext,
  withoutTool,
  withContext,
  withTool,
  withUpdatedTool,
  type LinkableDocument,
} from "./agent-links";

/**
 * The panel that chooses what an Agent is connected to (ADR 0021): the nodes it may
 * call as tools, and the outputs, cards and Library items it reads as context.
 *
 * It is controlled. It holds no Agent of its own: every edit goes through
 * `onChange(nextAgent)` with the agent the pure helpers in `agent-links.ts` produced,
 * so the card that owns the Agent stays the only place its state lives.
 */
export interface AgentLinksPanelProps {
  agent: SavedGraphAgent;
  /** This Graph's nodes and the cards drawn on its canvas. */
  document: LinkableDocument & {
    presentation?: {
      viewers: readonly {
        id: string;
        artifact_ref?: { artifact_type: string; schema_version: number } | null;
      }[];
    };
  };
  registry: NodeRegistry;
  onChange: (agent: SavedGraphAgent) => void;
  disabled?: boolean;
}

const s = stylex.create({
  // The panel lives inside a canvas card, so the root also carries React Flow's
  // `nodrag nopan nowheel` as a plain className: React Flow walks up from the event
  // target, so one set of classes covers every control below.
  root: {
    display: "grid",
    gap: "12px",
    minWidth: 0,
  },
  section: {
    display: "grid",
    gap: "6px",
    alignContent: "start",
    minWidth: 0,
    margin: 0,
    padding: 0,
    borderWidth: 0,
  },
  heading: {
    margin: 0,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    textTransform: "uppercase",
  },
  /** A fieldset's own border and padding would fight the card's grid. */
  tool: {
    display: "grid",
    gap: "6px",
    alignContent: "start",
    minWidth: 0,
    margin: 0,
    paddingBlockStart: "8px",
    paddingTop: "8px",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
    borderInlineWidth: 0,
    borderBottomWidth: 0,
  },
  line: {
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
  },
  check: {
    display: "flex",
    alignItems: "baseline",
    flexWrap: "wrap",
    gap: "6px",
    minWidth: 0,
    color: tokens.colorText,
    fontSize: tokens.fontSizeXs,
  },
  /** Why an input cannot be offered, and the node whose link the Graph cannot honour. */
  reason: {
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
  },
  contextRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "8px",
    minWidth: 0,
  },
  contextLabel: {
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    color: tokens.colorText,
    fontSize: tokens.fontSizeXs,
  },
  hint: {
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
  },
  /**
   * The kit has no select, so these keep a native one to the same silhouette as the
   * shared inputs above them.
   */
  select: {
    width: "100%",
    minWidth: 0,
    height: "31px",
    paddingInline: "10px",
    borderWidth: 0,
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorSurfaceMuted,
    color: {
      default: tokens.colorText,
      ":disabled": tokens.colorTextDisabled,
    },
    cursor: { default: "pointer", ":disabled": "not-allowed" },
    fontSize: tokens.fontSizeSm,
    outline: {
      default: "none",
      ":focus": `2px solid ${tokens.colorAccentBorder}`,
    },
  },
});

export function AgentLinksPanel({
  agent,
  document: graph,
  registry,
  onChange,
  disabled = false,
}: AgentLinksPanelProps): React.ReactElement {
  const specOf = (node: SavedGraphNode): NodeSpec | undefined =>
    registry.nodes.find(
      (spec) =>
        spec.operator_id === node.operator_id &&
        spec.operator_version === node.operator_version,
    );

  // A node may be called by one tool only, so a linked node leaves the list. Titles
  // repeat across a Graph, and two options that read alike are told apart in place.
  const addable = graph.nodes
    .map((node) => ({ node, spec: specOf(node) }))
    .filter(
      (entry): entry is { node: SavedGraphNode; spec: NodeSpec } =>
        entry.spec !== undefined &&
        !agent.tools.some((tool) => tool.node_id === entry.node.id) &&
        // Graph boundary and call nodes are not tools yet.
        entry.spec.plugin_slug !== "project-graphs",
    );
  const addableTitles = addable.map((entry) => entry.spec.title);
  const toolOptions = addable.map((entry, index) => {
    const title = entry.spec.title;
    const ordinal =
      addableTitles.slice(0, index).filter((candidate) => candidate === title)
        .length + 1;
    // The first of a repeated title keeps the plain name; the rest count off it.
    return {
      ...entry,
      label: ordinal === 1 ? title : `${title} (${ordinal})`,
    };
  });

  const outputChoices = graph.nodes.flatMap((node) => {
    const spec = specOf(node);
    if (!spec) return [];
    return spec.outputs
      .filter(
        (port) =>
          !agent.context.some(
            (link) =>
              link.kind === "node_output" &&
              link.node_id === node.id &&
              link.port === port.name,
          ),
      )
      .map((port) => ({
        node,
        spec,
        port: port.name,
        label: `${spec.title} · ${port.name}`,
      }));
  });
  const cardChoices = (graph.presentation?.viewers ?? []).flatMap((viewer) => {
    const artifactRef = viewer.artifact_ref;
    if (!artifactRef) return [];
    if (
      agent.context.some(
        (link) => link.kind === "card" && link.card_id === viewer.id,
      )
    ) {
      return [];
    }
    return [
      {
        viewer,
        // A person reads the catalog's name for a type, never its identity.
        artifactType: artifactTypeTitle(
          {
            id: artifactRef.artifact_type,
            schema_version: artifactRef.schema_version,
          },
          registry.artifact_types,
        ),
      },
    ];
  });

  return (
    <div className="nodrag nopan nowheel" {...stylex.props(s.root)}>
      <section aria-label="Tools" {...stylex.props(s.section)}>
        <h3 {...stylex.props(s.heading)}>Tools</h3>
        {agent.tools.map((link) => {
          const node = graph.nodes.find(
            (candidate) => candidate.id === link.node_id,
          );
          const spec = node ? specOf(node) : undefined;
          const remove = (
            <IconButton
              label={`Remove tool ${link.name}`}
              size="xs"
              variant="ghost"
              disabled={disabled}
              onClick={() => onChange(withoutTool(agent, link.id))}
            >
              <Trash2 size={14} />
            </IconButton>
          );
          if (!node || !spec) {
            // The node went away under the link. The Agent still names a tool the
            // server cannot build, so a person has to be able to drop it here.
            return (
              <div
                key={link.id}
                role="group"
                aria-label={`Tool ${link.name}`}
                {...stylex.props(s.contextRow)}
              >
                <span {...stylex.props(s.reason)}>
                  {`${link.name}: this node is no longer available`}
                </span>
                {remove}
              </div>
            );
          }

          const choices = toolPortChoices(link, node, spec, graph, registry);
          const returnedCount = choices.outputs.filter(
            (output) => output.returned,
          ).length;
          return (
            <fieldset
              key={link.id}
              aria-label={`Tool ${link.name}`}
              {...stylex.props(s.tool)}
            >
              <Field label="Name" disabled={disabled}>
                <TextInput
                  value={link.name}
                  disabled={disabled}
                  onChange={(event) =>
                    onChange(
                      withUpdatedTool(agent, link.id, {
                        name: event.currentTarget.value
                          .toLowerCase()
                          .replace(/[^a-z0-9_]/g, "_"),
                      }),
                    )
                  }
                />
              </Field>
              <Field label="What it does" disabled={disabled}>
                <TextInput
                  value={link.description}
                  placeholder="Say when to use it"
                  disabled={disabled}
                  onChange={(event) =>
                    onChange(
                      withUpdatedTool(agent, link.id, {
                        description: event.currentTarget.value,
                      }),
                    )
                  }
                />
              </Field>
              <span {...stylex.props(s.line)}>Inputs the model fills</span>
              {choices.inputs.map((input) => (
                <label
                  key={input.name}
                  title={input.reason ?? undefined}
                  {...stylex.props(s.check)}
                >
                  <input
                    type="checkbox"
                    checked={input.filled}
                    disabled={disabled || !input.offerable}
                    onChange={(event) => {
                      const picked = new Set(link.filled_ports);
                      if (event.currentTarget.checked) picked.add(input.name);
                      else picked.delete(input.name);
                      onChange(
                        withUpdatedTool(agent, link.id, {
                          // The node's own input order, not the order of clicks.
                          filled_ports: spec.inputs
                            .map((port) => port.name)
                            .filter((name) => picked.has(name)),
                        }),
                      );
                    }}
                  />
                  <span>{input.title}</span>
                  {input.reason ? (
                    <span {...stylex.props(s.reason)}>{input.reason}</span>
                  ) : null}
                </label>
              ))}
              <span {...stylex.props(s.line)}>Outputs it returns</span>
              {choices.outputs.map((output) => (
                <label key={output.name} {...stylex.props(s.check)}>
                  <input
                    type="checkbox"
                    checked={output.returned}
                    // A tool that returns nothing is a call worth making for none
                    // of its results, so the last returned output stays.
                    disabled={
                      disabled || (output.returned && returnedCount === 1)
                    }
                    onChange={(event) => {
                      const picked = new Set(
                        choices.outputs
                          .filter((candidate) => candidate.returned)
                          .map((candidate) => candidate.name),
                      );
                      if (event.currentTarget.checked) picked.add(output.name);
                      else picked.delete(output.name);
                      onChange(
                        withUpdatedTool(agent, link.id, {
                          // None named means all returned, so a link that asks for
                          // every output names none.
                          returned_ports: spec.outputs.every((port) =>
                            picked.has(port.name),
                          )
                            ? []
                            : spec.outputs
                                .map((port) => port.name)
                                .filter((name) => picked.has(name)),
                        }),
                      );
                    }}
                  />
                  <span>{output.title}</span>
                </label>
              ))}
              {remove}
            </fieldset>
          );
        })}
        <select
          aria-label="Add a node as a tool"
          value=""
          disabled={disabled}
          {...stylex.props(s.select)}
          onChange={(event) => {
            const chosen = toolOptions.find(
              (entry) => entry.node.id === event.currentTarget.value,
            );
            if (!chosen) return;
            onChange(
              withTool(
                agent,
                newToolLink(agent, chosen.node, chosen.spec, graph, registry),
              ),
            );
          }}
        >
          <option value="">Add a tool…</option>
          {toolOptions.map((entry) => (
            <option key={entry.node.id} value={entry.node.id}>
              {entry.label}
            </option>
          ))}
        </select>
      </section>
      <section
        aria-label="Context"
        {...stylex.props(s.section)}
        onDragOver={(event) => {
          if (
            Array.from(event.dataTransfer.types ?? []).includes(
              ARTIFACT_DROP_DATA_TYPE,
            )
          ) {
            event.preventDefault();
          }
        }}
        onDrop={(event) => {
          event.preventDefault();
          if (disabled) return;
          const dropped = readArtifactDrop(event.dataTransfer)?.value;
          // One Library card becomes one context link; a sequence or any other
          // payload is not a thing this Agent reads.
          if (dropped && "artifact_id" in dropped) {
            onChange(
              withContext(agent, libraryItemContext(dropped.artifact_id)),
            );
          }
        }}
      >
        <h3 {...stylex.props(s.heading)}>Context</h3>
        {agent.context.map((link) => {
          const node = link.node_id
            ? graph.nodes.find((candidate) => candidate.id === link.node_id)
            : undefined;
          const label =
            link.kind === "node_output"
              ? `${node ? (specOf(node)?.title ?? node.id) : (link.node_id ?? link.id)} · ${link.port ?? ""}`
              : link.kind === "card"
                ? "Card"
                : "Library item";
          return (
            <div
              key={link.id}
              role="group"
              aria-label={`Context ${label}`}
              {...stylex.props(s.contextRow)}
            >
              <span {...stylex.props(s.contextLabel)}>{label}</span>
              <IconButton
                label={`Remove context ${label}`}
                size="xs"
                variant="ghost"
                disabled={disabled}
                onClick={() => onChange(withoutContext(agent, link.id))}
              >
                <Trash2 size={14} />
              </IconButton>
            </div>
          );
        })}
        <select
          aria-label="Add context"
          value=""
          disabled={disabled}
          {...stylex.props(s.select)}
          onChange={(event) => {
            const value = event.currentTarget.value;
            if (!value) return;
            const [kind, ...parts] = value.split(":");
            if (kind === "output") {
              // The port is the part after the last colon, so the node id is what
              // is left between the two.
              const port = parts[parts.length - 1] ?? "";
              onChange(
                withContext(
                  agent,
                  nodeOutputContext(parts.slice(0, -1).join(":"), port),
                ),
              );
            } else if (kind === "card") {
              onChange(withContext(agent, cardContext(parts.join(":"))));
            }
          }}
        >
          <option value="">Add context…</option>
          <optgroup label="Node outputs">
            {outputChoices.map((choice) => (
              <option
                key={`${choice.node.id}:${choice.port}`}
                value={`output:${choice.node.id}:${choice.port}`}
              >
                {choice.label}
              </option>
            ))}
          </optgroup>
          <optgroup label="Cards">
            {cardChoices.map((choice) => (
              <option key={choice.viewer.id} value={`card:${choice.viewer.id}`}>
                {`Card · ${choice.artifactType}`}
              </option>
            ))}
          </optgroup>
        </select>
        <span {...stylex.props(s.hint)}>
          Drop an artifact here to connect it
        </span>
      </section>
    </div>
  );
}
