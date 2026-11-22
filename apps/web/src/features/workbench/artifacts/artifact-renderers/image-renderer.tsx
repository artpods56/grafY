"use client";

import * as stylex from "@stylexjs/stylex";

import { artifactContentUrl } from "@/lib/api";
import { useWorkspaceContext } from "@/features/workspaces/WorkspaceLayout";
import { tokens } from "@/lib/stylex/tokens.stylex";

import { artifactMeta } from "./artifact-meta";
import { PrettyValue } from "./pretty-value";
import type { ArtifactRendererSpec } from "./spec";

const s = stylex.create({
  image: {
    display: "block",
    width: "100%",
    borderRadius: "8px",
    backgroundColor: tokens.colorSurface,
  },
});

export const imageRenderer: ArtifactRendererSpec = {
  id: "image",
  modes: ["preview", "meta"],
  matches: (artifact) =>
    artifact.content_type.startsWith("image/") && Boolean(artifact.content_url),
  Component: ({ artifact, mode }) => {
    const { workspace } = useWorkspaceContext();
    if (mode === "meta") {
      return <PrettyValue value={artifactMeta(artifact)} />;
    }
    const url =
      artifactContentUrl(workspace.id, artifact.content_url) ??
      artifact.content_url ??
      "";
    return (
      /* eslint-disable-next-line @next/next/no-img-element -- artifact URLs are dynamic */
      <img
        src={url}
        alt={artifact.text ?? artifact.artifact_type}
        {...stylex.props(s.image)}
      />
    );
  },
};
