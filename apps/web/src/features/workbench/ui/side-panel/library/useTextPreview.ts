"use client";

import * as React from "react";

import type { PlacedLibraryItem } from "@/lib/api";

/** How much of a text artifact the preview reads before it stops. */
export const PREVIEW_TEXT_LIMIT = 20_000;

export function isPreviewableText(item: PlacedLibraryItem): boolean {
  const contentType = (item.artifact.content_type ?? "").toLowerCase();
  return (
    contentType.startsWith("text/") ||
    contentType === "application/json" ||
    contentType.endsWith("+json") ||
    contentType === "application/csv" ||
    contentType === "application/x-ndjson"
  );
}

/** The head of a text artifact, read lazily for the preview tile. */
export type TextPreview = { artifactId: string; text: string };

export function useTextPreview(
  contentUrl: string | null,
  item: PlacedLibraryItem,
): { text: string | null; loading: boolean } {
  const artifactId = item.artifact.artifact_id;
  const previewable = isPreviewableText(item);
  const [read, setRead] = React.useState<TextPreview | null>(null);

  React.useEffect(() => {
    if (!previewable || contentUrl === null) return;
    const controller = new AbortController();
    fetch(contentUrl, { signal: controller.signal })
      .then((response) => response.text())
      .then((body) => {
        setRead({
          artifactId,
          text:
            body.length > PREVIEW_TEXT_LIMIT
              ? `${body.slice(0, PREVIEW_TEXT_LIMIT)}\n…`
              : body,
        });
      })
      .catch(() => {
        // A preview that will not load shows the artifact's facts instead.
        setRead({ artifactId, text: "" });
      });
    return () => controller.abort();
  }, [artifactId, contentUrl, previewable]);

  const current = read?.artifactId === artifactId ? read : null;
  return {
    text: current?.text ? current.text : null,
    loading: previewable && current === null,
  };
}
