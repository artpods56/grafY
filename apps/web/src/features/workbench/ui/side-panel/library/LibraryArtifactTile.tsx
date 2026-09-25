"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { ArrowUpRight, Download } from "lucide-react";

import {
  artifactContentUrl,
  type LibraryFolder,
  type PlacedLibraryItem,
} from "@/lib/api";
import { panelStyles as s } from "../panel-styles";
import {
  isItemImage,
  libraryFileDisplayName,
  libraryFolderPath,
  libraryProvenanceLine,
} from "../library-tree";
import { useTextPreview } from "./useTextPreview";

/**
 * The reserved tile under the browser. It shows the selected artifact itself —
 * an image or the head of a text file — plus where it came from.
 */
export function LibraryArtifactTile({
  workspaceId,
  item,
  folders,
  onOpenRun,
}: {
  workspaceId: string;
  item: PlacedLibraryItem;
  folders: readonly LibraryFolder[];
  onOpenRun: (graphId: string, executionId: string) => void;
}) {
  const contentUrl = artifactContentUrl(workspaceId, item.artifact.content_url);
  const run = item.run;
  const path = libraryFolderPath(folders, item.folder_id);
  const [imageFailed, setImageFailed] = React.useState(false);
  const preview = useTextPreview(contentUrl, item);

  return (
    <aside aria-label="Selected artifact" {...stylex.props(s.inspector)}>
      <span {...stylex.props(s.inspectorTitle)}>
        {libraryFileDisplayName(item)}
      </span>
      <span {...stylex.props(s.inspectorMono)}>
        {path.length > 0 ? `/${path.join("/")}` : "/"}
        {" · "}
        {item.artifact.artifact_type}@{item.artifact.schema_version}
      </span>

      {isItemImage(item) && contentUrl !== null && !imageFailed ? (
        /* eslint-disable-next-line @next/next/no-img-element -- artifact bytes have no predictable size for the image optimizer */
        <img
          key={item.artifact.artifact_id}
          src={contentUrl}
          alt={`Preview of ${libraryFileDisplayName(item)}`}
          decoding="async"
          onError={() => setImageFailed(true)}
          {...stylex.props(s.previewImage)}
        />
      ) : null}
      {preview.text !== null ? (
        <pre {...stylex.props(s.previewText)}>{preview.text}</pre>
      ) : null}
      {preview.loading ? (
        <span role="status" {...stylex.props(s.inspectorText)}>
          Reading preview…
        </span>
      ) : null}

      <span {...stylex.props(s.inspectorLabel)}>Provenance</span>
      <span {...stylex.props(s.inspectorText)}>
        {libraryProvenanceLine(item)}
      </span>
      {run ? (
        <span {...stylex.props(s.inspectorText)}>
          {run.finished_at
            ? `finished ${new Date(run.finished_at).toLocaleString()}`
            : "run still in history"}
        </span>
      ) : null}
      <span {...stylex.props(s.inspectorActions)}>
        {contentUrl ? (
          <a
            href={contentUrl}
            target="_blank"
            rel="noreferrer"
            {...stylex.props(s.action)}
          >
            <Download size={11} aria-hidden="true" />
            Open original
          </a>
        ) : null}
        {run ? (
          <button
            type="button"
            {...stylex.props(s.action)}
            onClick={() => onOpenRun(run.graph_id, run.execution_id)}
          >
            <ArrowUpRight size={11} aria-hidden="true" />
            Execution history
          </button>
        ) : null}
      </span>
    </aside>
  );
}
