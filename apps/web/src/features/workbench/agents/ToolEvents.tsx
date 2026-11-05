"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import type { components } from "@/lib/api/generated/grafy";
import { Button } from "@/components/ui/button";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { writeArtifactDrop } from "../model/artifact-drop";
import {
  formatArtifactTypeLabel,
  formatArtifactTypeSequence,
  type ArtifactTypeCatalog,
} from "../canvas/artifact-type-label";

type S = components["schemas"];

/** Cut to `limit` characters, marking a cut with a trailing ellipsis. */
function clip(text: string, limit: number): string {
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

const s = stylex.create({
  // Every row is a wrapping line of small parts — a sentence, then chips or a
  // button — and a nested line of chips uses the same contract. `minWidth: 0`
  // lets a long summary shrink instead of pushing the thread wider than its
  // card.
  row: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    gap: "6px",
    minWidth: 0,
  },
  text: {
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
  },
  failed: {
    color: tokens.colorDanger,
    fontSize: tokens.fontSizeXs,
  },
  chip: {
    display: "inline-flex",
    cursor: "grab",
    fontSize: tokens.fontSizeXs,
    padding: "2px 8px",
    borderRadius: tokens.radiusMd,
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    backgroundColor: tokens.colorSurfaceRaised,
    userSelect: "none",
  },
});

/** One tool call the model made, and the arguments it gave. */
export function ToolCallRow({
  payload,
}: {
  payload: S["ToolCallPayload"];
}): React.ReactElement {
  const pairs = Object.entries(payload.arguments ?? {}).map(([key, value]) =>
    // A string is what a person would have typed; anything else is shown as
    // the JSON it was, so a nested object does not read as `[object Object]`.
    clip(
      `${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`,
      60,
    ),
  );
  const summary = pairs.length > 0 ? clip(pairs.join(", "), 160) : null;
  return (
    <div
      role="group"
      aria-label={`Tool call: ${payload.tool_name}`}
      {...stylex.props(s.row)}
    >
      <span {...stylex.props(s.text)}>
        Called <code>{payload.tool_name}</code>
        {summary === null ? "" : ` with ${summary}`}
      </span>
    </div>
  );
}

/** How one tool call ended: what it produced, or why it did not. */
export function ToolResultRow({
  payload,
  artifactTypes,
}: {
  payload: S["ToolResultPayload"];
  artifactTypes: ArtifactTypeCatalog;
}): React.ReactElement {
  if (!payload.ok) {
    return (
      <div
        role="group"
        aria-label={`Tool result: ${payload.tool_name}`}
        {...stylex.props(s.row)}
      >
        <span role="status" {...stylex.props(s.failed)}>
          <code>{payload.tool_name}</code> failed:{" "}
          {payload.error ?? "no reason given"}
        </span>
      </div>
    );
  }
  return (
    <div
      role="group"
      aria-label={`Tool result: ${payload.tool_name}`}
      {...stylex.props(s.row)}
    >
      <span {...stylex.props(s.text)}>
        <code>{payload.tool_name}</code>{" "}
        {payload.artifacts.length > 0 ? "returned" : "returned nothing"}
      </span>
      {payload.artifacts.length > 0 && (
        <span {...stylex.props(s.row)}>
          {payload.artifacts.map((entry) => (
            <ArtifactChip
              key={entry.port}
              port={entry.port}
              artifact={entry.artifact}
              artifactTypes={artifactTypes}
            />
          ))}
        </span>
      )}
    </div>
  );
}

/** One produced artifact, readable as text and draggable onto the canvas. */
export function ArtifactChip({
  port,
  artifact,
  artifactTypes,
}: {
  port: string;
  artifact: S["ToolResultArtifact"]["artifact"];
  artifactTypes: ArtifactTypeCatalog;
}): React.ReactElement {
  const artifactType = {
    id: artifact.artifact_type,
    schema_version: artifact.schema_version,
  };
  const label =
    "item_refs" in artifact
      ? formatArtifactTypeSequence(
          formatArtifactTypeLabel(artifactType, artifactTypes),
        )
      : formatArtifactTypeLabel(artifactType, artifactTypes);
  return (
    <div
      draggable={true}
      aria-label={`${port}: ${label}`}
      title="Drag onto the canvas, an input or the Library"
      onDragStart={(event) => {
        writeArtifactDrop(event.dataTransfer, artifact);
        event.dataTransfer.effectAllowed = "copy";
      }}
      {...stylex.props(s.chip)}
    >
      {port} · {label}
    </div>
  );
}

/** The turn stopped before another tool call: a person decides whether it goes on. */
export function ConfirmationRow({
  payload,
  onContinue,
  disabled,
}: {
  payload: S["ConfirmationRequestedPayload"];
  onContinue: () => void;
  disabled: boolean;
}): React.ReactElement {
  return (
    <div role="group" aria-label="Confirmation needed" {...stylex.props(s.row)}>
      <span {...stylex.props(s.text)}>
        This turn made {payload.tool_calls} tool calls. Carry on?
      </span>
      <Button variant="soft" size="xs" disabled={disabled} onClick={onContinue}>
        Continue
      </Button>
    </div>
  );
}
