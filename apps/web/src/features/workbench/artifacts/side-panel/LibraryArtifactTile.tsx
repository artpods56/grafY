"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  ArrowUpRight,
  Boxes,
  Download,
  File as FileIcon,
  FileCode,
  FileText,
  Image as ImageIcon,
  LoaderCircle,
  Map as MapIcon,
  Table2,
  X,
  type LucideIcon,
} from "lucide-react";

import { Button, ButtonLink, IconButton } from "@/components/ui/button";
import {
  artifactContentUrl,
  type LibraryFolder,
  type PlacedLibraryItem,
} from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";
import {
  formatArtifactTypeLabel,
  formatArtifactTypeTooltip,
} from "../artifact-type-label";
import { useArtifactTypeCatalog } from "../use-artifact-type-catalog";
import {
  formatLibraryByteSize,
  isBrowserRenderableImage,
  isItemText,
  libraryFileBadge,
  libraryFileDisplayName,
  libraryFolderPath,
  libraryProvenanceLine,
  type LibraryFileBadgeKind,
} from "./library-tree";
import { panelStyles } from "./panel-styles";

const BADGE_ICONS: Record<LibraryFileBadgeKind, LucideIcon> = {
  image: ImageIcon,
  map: MapIcon,
  table: Table2,
  code: FileCode,
  text: FileText,
  model: Boxes,
  other: FileIcon,
};

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
  onOpenInstance,
  onClose,
}: {
  workspaceId: string;
  item: PlacedLibraryItem;
  folders: readonly LibraryFolder[];
  /** Jump to the Graph the artifact came from, naming the result it came from. */
  onOpenInstance: (graphId: string, resultFingerprint: string | null) => void;
  onClose: () => void;
}) {
  const name = libraryFileDisplayName(item);
  const contentUrl = artifactContentUrl(workspaceId, item.artifact.content_url);
  // An item remembers the node instance it was saved from, not the Run that
  // happened to make that result fresh: the Run is gone, the instance is not.
  const { provenance } = item;
  const fromGraph =
    provenance.source === "instance" ? provenance.graph_id : null;
  const location = ["Library", ...libraryFolderPath(folders, item.folder_id)];
  const size = formatLibraryByteSize(item.artifact.byte_size);
  const [imageFailed, setImageFailed] = React.useState(false);
  const artifactTypes = useArtifactTypeCatalog();
  const artifactType = {
    id: item.artifact.artifact_type,
    schema_version: item.artifact.schema_version,
  };
  const badge = libraryFileBadge(item);
  const TypeIcon = BADGE_ICONS[badge.kind];
  const preview = useTextHead(isItemText(item) ? contentUrl : null);

  return (
    <aside aria-label="Selected artifact" {...stylex.props(s.dock)}>
      <div {...stylex.props(s.card)}>
        <div {...stylex.props(s.header)}>
          <span aria-hidden="true" {...stylex.props(s.typeBadge)}>
            <TypeIcon size={12} strokeWidth={1.75} />
          </span>
          <span {...stylex.props(s.title)} title={name}>
            {name}
          </span>
          <IconButton
            label="Close preview"
            size="xs"
            xstyle={[panelStyles.iconButton, s.close]}
            onClick={onClose}
          >
            <X size={13} />
          </IconButton>
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

        {isBrowserRenderableImage(item) &&
        contentUrl !== null &&
        !imageFailed ? (
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

        <div {...stylex.props(s.provenance)}>
          <span {...stylex.props(s.label)}>Provenance</span>
          <span {...stylex.props(s.text)}>{libraryProvenanceLine(item)}</span>
          <span {...stylex.props(s.dateText)}>
            Saved {formatDateTime(provenance.saved_at)}
          </span>
        </div>

        {contentUrl || fromGraph ? (
          <span {...stylex.props(s.actions)}>
            {contentUrl ? (
              <ButtonLink
                href={contentUrl}
                target="_blank"
                rel="noreferrer"
                variant="secondary"
                size="xs"
              >
                <Download size={11} aria-hidden="true" />
                Open original
              </ButtonLink>
            ) : null}
            {fromGraph ? (
              <Button
                type="button"
                variant="secondary"
                size="xs"
                onClick={() =>
                  onOpenInstance(
                    fromGraph,
                    provenance.result_fingerprint ?? null,
                  )
                }
              >
                <ArrowUpRight size={11} aria-hidden="true" />
                Where it came from
              </Button>
            ) : null}
          </span>
        ) : null}
      </div>
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
  dock: {
    flexShrink: 0,
    maxHeight: "48%",
    display: "flex",
    flexDirection: "column",
    padding: "8px 8px 6px",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorSubrailBorder,
  },
  card: {
    minHeight: 0,
    overflowY: "auto",
    display: "grid",
    gap: "7px",
    padding: "10px",
    borderRadius: tokens.radiusMd,
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    backgroundColor: tokens.colorSurface,
    boxShadow: tokens.shadowNode,
  },
  header: {
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    gap: "6px",
  },
  typeBadge: {
    width: "20px",
    height: "20px",
    flexShrink: 0,
    display: "grid",
    placeItems: "center",
    borderRadius: tokens.radiusSm,
    backgroundColor: tokens.colorSurfaceRaised,
    color: tokens.colorMuted,
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
  close: { marginRight: "-2px" },
  facts: {
    marginTop: "-3px",
    color: tokens.colorMuted,
    fontSize: "10.5px",
    lineHeight: 1.4,
    overflowWrap: "anywhere",
  },
  mono: {
    fontFamily:
      "var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace)",
  },
  imageFrame: {
    display: "grid",
    placeItems: "center",
    padding: "5px",
    borderRadius: tokens.radiusSm,
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorDivider,
    backgroundColor: tokens.colorSurfaceSunken,
  },
  image: {
    display: "block",
    maxWidth: "100%",
    maxHeight: "140px",
    objectFit: "contain",
    borderRadius: "4px",
  },
  textPreview: {
    maxHeight: "104px",
    overflowY: "auto",
    margin: 0,
    padding: "6px 8px",
    borderRadius: tokens.radiusSm,
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
  provenance: {
    display: "grid",
    gap: "2px",
    paddingTop: "6px",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
  },
  label: {
    color: tokens.colorSubtle,
    fontSize: "9.5px",
    fontWeight: 640,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
  },
  text: {
    color: tokens.colorText,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.35,
    overflowWrap: "anywhere",
  },
  dateText: {
    color: tokens.colorMuted,
    fontSize: "10.5px",
    lineHeight: 1.35,
  },
  reading: { display: "flex", alignItems: "center", gap: "6px" },
  actions: {
    display: "flex",
    flexWrap: "wrap",
    gap: "6px",
    marginTop: "1px",
  },
});
