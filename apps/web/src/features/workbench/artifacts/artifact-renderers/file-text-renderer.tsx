"use client";

import * as stylex from "@stylexjs/stylex";
import useSWR from "swr";

import { artifactContentUrl } from "@/lib/api";
import { useWorkspaceContext } from "@/features/workspaces/WorkspaceLayout";
import { tokens } from "@/lib/stylex/tokens.stylex";

import { artifactMeta } from "./artifact-meta";
import { PrettyValue } from "./pretty-value";
import type { ArtifactRendererSpec } from "./spec";
import { sharedStyles } from "./styles";
import {
  formatTextHead,
  readTextHead,
  TEXT_HEAD_BYTE_LIMIT,
} from "./text-head";

const s = stylex.create({
  notice: {
    marginTop: 0,
    marginBottom: "6px",
    color: tokens.colorSubtle,
    fontSize: "10px",
    lineHeight: 1.45,
  },
});

export const fileTextRenderer: ArtifactRendererSpec = {
  id: "file-text",
  modes: ["text", "meta"],
  matches: (artifact) =>
    artifact.artifact_type.startsWith("file.") && Boolean(artifact.content_url),
  Component: ({ artifact, mode }) => {
    const { workspace } = useWorkspaceContext();
    const url = artifactContentUrl(workspace.id, artifact.content_url);
    const { data, error, isLoading } = useSWR(
      mode === "text" && url ? ["artifact-text-head", url] : null,
      ([, contentUrl]) => readTextHead(contentUrl),
    );

    if (mode === "meta") return <PrettyValue value={artifactMeta(artifact)} />;
    if (isLoading) {
      return (
        <p role="status" aria-live="polite" {...stylex.props(s.notice)}>
          Loading…
        </p>
      );
    }
    if (error || !data) {
      return (
        <>
          <p {...stylex.props(s.notice)}>
            {error
              ? "Content could not be loaded; showing artifact metadata."
              : "Binary content; showing artifact metadata."}
          </p>
          <PrettyValue value={artifactMeta(artifact)} />
        </>
      );
    }
    return (
      <>
        {data.truncated ? (
          <p {...stylex.props(s.notice)}>
            Showing the first {TEXT_HEAD_BYTE_LIMIT / 1_024} KB.
          </p>
        ) : null}
        <pre {...stylex.props(sharedStyles.jsonCode)}>
          {formatTextHead(data)}
        </pre>
      </>
    );
  },
};
