"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { ArrowUpRight, Download, LoaderCircle, X } from "lucide-react";

import {
  artifactContentUrl,
  type LibraryFolder,
  type PlacedLibraryItem,
} from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";
import {
  formatArtifactTypeLabel,
  formatArtifactTypeTooltip,
} from "../../canvas/artifact-type-label";
import { useArtifactTypeCatalog } from "../../canvas/use-artifact-type-catalog";
import {
  formatLibraryByteSize,
  isItemImage,
  isItemText,
  libraryFileDisplayName,
  libraryFolderPath,
  libraryProvenanceLine,
} from "./library-tree";
import { panelStyles } from "./panel-styles";

/** How much of a text artifact the preview reads before it stops. */
const PREVIEW_TEXT_LIMIT = 20_000;

/**
 * The tile under the browser. It shows the selected artifact itself — an image
 * or the head of a text file — plus where it is filed and where it came from.
 *
 * Mount it with `key={artifactId}`: its preview state belongs to one artifact.
 */
export function LibraryArtifactTile({
  workspaceId,
  item,
  folders,
  onOpenRun,
  onClose,
}: {
  workspaceId: string;
  item: PlacedLibraryItem;
  folders: readonly LibraryFolder[];
  onOpenRun: (graphId: string, executionId: string) => void;
  onClose: () => void;
}) {
  const name = libraryFileDisplayName(item);
  const contentUrl = artifactContentUrl(workspaceId, item.artifact.content_url);
  const { run } = item;
  const location = ["Library", ...libraryFolderPath(folders, item.folder_id)];
  const size = formatLibraryByteSize(item.artifact.byte_size);
  const [imageFailed, setImageFailed] = React.useState(false);
  const artifactTypes = useArtifactTypeCatalog();
  const artifactType = {
    id: item.artifact.artifact_type,
    schema_version: item.artifact.schema_version,
  };
  const preview = useTextHead(isItemText(item) ? contentUrl : null);

  return (
    <aside aria-label="Selected artifact" {...stylex.props(s.tile)}>
      <div {...stylex.props(s.header)}>
        <span {...stylex.props(s.title)} title={name}>
          {name}
        </span>
        <button
          type="button"
          aria-label="Close preview"
          title="Close preview"
          onClick={onClose}
          {...stylex.props(panelStyles.iconButton, s.close)}
        >
          <X size={13} />
        </button>
      </div>
      <span {...stylex.props(s.facts)}>
        {location.join(" / ")}
        {" · "}
        <span
          title={formatArtifactTypeTooltip(artifactType)}
          {...stylex.props(s.mono)}
        >
          {formatArtifactTypeLabel(artifactType, artifactTypes)}
        </span>
        {size ? ` · ${size}` : null}
      </span>

      {isItemImage(item) && contentUrl !== null && !imageFailed ? (
        <span {...stylex.props(s.imageFrame)}>
          {/* eslint-disable-next-line @next/next/no-img-element -- artifact bytes have no predictable size for the image optimizer */}
          <img
            src={contentUrl}
            alt={`Preview of ${name}`}
            decoding="async"
            onError={() => setImageFailed(true)}
            {...stylex.props(s.image)}
          />
        </span>
      ) : null}
      {preview.loading ? (
        <span role="status" {...stylex.props(s.text, s.reading)}>
          <LoaderCircle
            size={11}
            aria-hidden="true"
            {...stylex.props(panelStyles.spinner)}
          />
          Reading preview…
        </span>
      ) : null}
      {preview.text ? (
        <pre {...stylex.props(s.textPreview)}>{preview.text}</pre>
      ) : null}

      <span {...stylex.props(s.label)}>Provenance</span>
      <span {...stylex.props(s.text)}>{libraryProvenanceLine(item)}</span>
      {run?.finished_at ? (
        <span {...stylex.props(s.text)}>
          Run finished {formatDateTime(run.finished_at)}
        </span>
      ) : null}

      {contentUrl || run ? (
        <span {...stylex.props(s.actions)}>
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
              onClick={() => onOpenRun(run.graph_id, run.execution_id)}
              {...stylex.props(s.action)}
            >
              <ArrowUpRight size={11} aria-hidden="true" />
              Execution history
            </button>
          ) : null}
        </span>
      ) : null}
    </aside>
  );
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

/**
 * The head of a text artifact, or null when there is none to show. A preview
 * that will not load leaves the tile to the artifact's facts.
 */
function useTextHead(url: string | null): {
  text: string | null;
  loading: boolean;
} {
  const [read, setRead] = React.useState<{ text: string | null } | null>(null);

  React.useEffect(() => {
    if (url === null) return;
    const controller = new AbortController();
    readTextHead(url, controller.signal).then(
      (text) => setRead({ text }),
      () => {
        if (!controller.signal.aborted) setRead({ text: null });
      },
    );
    return () => controller.abort();
  }, [url]);

  return {
    text: read?.text || null,
    loading: url !== null && read === null,
  };
}

/** Reads no more of the body than the preview shows. */
async function readTextHead(
  url: string,
  signal: AbortSignal,
): Promise<string | null> {
  const response = await fetch(url, { signal });
  if (!response.ok) return null;
  if (!response.body) return clip(await response.text());

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let text = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return clip(text + decoder.decode());
    text += decoder.decode(value, { stream: true });
    if (text.length > PREVIEW_TEXT_LIMIT) {
      void reader.cancel();
      return clip(text);
    }
  }
}

function clip(text: string): string {
  return text.length > PREVIEW_TEXT_LIMIT
    ? `${text.slice(0, PREVIEW_TEXT_LIMIT)}\n…`
    : text;
}

const s = stylex.create({
  tile: {
    flexShrink: 0,
    // The tile never takes the tree's whole column; what does not fit scrolls.
    maxHeight: "55%",
    overflowY: "auto",
    display: "grid",
    gap: "6px",
    padding: "8px 10px 12px",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
    backgroundColor: tokens.colorSurfaceMuted,
  },
  header: {
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    gap: "6px",
  },
  title: {
    minWidth: 0,
    flex: 1,
    overflow: "hidden",
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeSm,
    fontWeight: 620,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  close: { width: "22px", height: "22px", marginRight: "-4px" },
  facts: {
    marginTop: "-4px",
    color: tokens.colorSubtle,
    fontSize: "10.5px",
    lineHeight: 1.45,
    overflowWrap: "anywhere",
  },
  mono: { fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" },
  imageFrame: {
    display: "grid",
    placeItems: "center",
    padding: "6px",
    borderRadius: "6px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorDivider,
    backgroundColor: tokens.colorSurfaceSunken,
  },
  image: {
    display: "block",
    maxWidth: "100%",
    maxHeight: "200px",
    borderRadius: "3px",
  },
  textPreview: {
    maxHeight: "132px",
    overflowY: "auto",
    margin: 0,
    padding: "6px 7px",
    borderRadius: "6px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorDivider,
    backgroundColor: tokens.colorSurfaceSunken,
    color: tokens.colorText,
    fontFamily: "var(--font-mono, ui-monospace, monospace)",
    fontSize: "10.5px",
    lineHeight: 1.45,
    whiteSpace: "pre-wrap",
    overflowWrap: "anywhere",
  },
  label: {
    marginTop: "2px",
    color: tokens.colorSubtle,
    fontSize: "10px",
    fontWeight: 620,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
  },
  text: {
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.4,
    overflowWrap: "anywhere",
  },
  reading: { display: "flex", alignItems: "center", gap: "6px" },
  actions: {
    display: "flex",
    flexWrap: "wrap",
    gap: "6px",
    marginTop: "2px",
  },
  action: {
    height: "24px",
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
    paddingInline: "7px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "6px",
    backgroundColor: {
      default: tokens.colorBg,
      ":hover": tokens.colorSurfaceSunken,
    },
    color: tokens.colorText,
    cursor: "pointer",
    fontFamily: "inherit",
    fontSize: tokens.fontSizeXs,
    fontWeight: 560,
    textDecoration: "none",
  },
});
