"use client";

import * as stylex from "@stylexjs/stylex";

import { artifactMeta } from "./artifact-meta";
import { formatJsonSchemaPayload } from "./payload";
import { PrettyValue } from "./pretty-value";
import type { ArtifactRendererSpec } from "./spec";
import { sharedStyles } from "./styles";

export const jsonSchemaRenderer: ArtifactRendererSpec = {
  id: "json-schema",
  modes: ["pretty", "raw"],
  matches: (artifact) =>
    artifact.artifact_type === "json.schema" && artifact.schema_version === 1,
  Component: ({ artifact, payload, mode }) => {
    const value = payload === undefined ? artifactMeta(artifact) : payload;
    if (mode === "pretty") {
      const formattedSchema = formatJsonSchemaPayload(value);
      if (formattedSchema !== null) {
        return (
          <pre {...stylex.props(sharedStyles.jsonCode)}>{formattedSchema}</pre>
        );
      }
      return <PrettyValue value={value} />;
    }
    return (
      <pre {...stylex.props(sharedStyles.jsonCode)}>
        {JSON.stringify(value, null, 2)}
      </pre>
    );
  },
};

export const jsonRenderer: ArtifactRendererSpec = {
  id: "json",
  modes: ["pretty", "raw"],
  matches: (artifact, payload) =>
    payload !== undefined || artifact.content_type === "application/json",
  Component: ({ artifact, payload, mode }) => {
    const value = payload === undefined ? artifactMeta(artifact) : payload;
    if (mode === "raw") {
      return (
        <pre {...stylex.props(sharedStyles.jsonCode)}>
          {JSON.stringify(value, null, 2)}
        </pre>
      );
    }
    return <PrettyValue value={value} />;
  },
};

/** A scalar is one `{ "value": … }` object; its JSON text is the readable form. */
export const scalarRenderer: ArtifactRendererSpec = {
  id: "scalar",
  modes: ["raw", "pretty"],
  matches: (artifact, payload) =>
    artifact.schema_version === 1 &&
    ["scalar.integer", "scalar.text"].includes(artifact.artifact_type) &&
    (payload !== undefined || artifact.content_type === "application/json"),
  Component: jsonRenderer.Component,
};
