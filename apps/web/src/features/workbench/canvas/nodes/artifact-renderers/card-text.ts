"use client";

import { artifactInlineContentUrl, type ArtifactRef } from "@/lib/api";

import {
  isGeoMapArtifact,
  isImageArtifact,
  isPdfArtifact,
  isTableFileArtifact,
} from "../../artifact-card";
import { isHtmlPageArtifact } from "./html-page";
import { formatTextHead, readTextHead, type TextHead } from "./text-head";

/** How much of an artifact's bytes a card reads to show as text. */
export const CARD_TEXT_BYTES = 4096;
/**
 * A text value is read whole so it can be rendered: the head of a page is not a page.
 * Room for the most an Agent may create, each character at its longest once escaped.
 */
export const CARD_TEXT_VALUE_BYTES = 1_250_000;

/**
 * The card's read of one artifact's bytes. Both the artifact card and the
 * collection card ask with this key, so an artifact shown twice is fetched once.
 */
export type CardTextKey = readonly [
  "artifact-card-text",
  string,
  string,
  number,
];

export function cardTextKey(
  workspaceId: string,
  artifactId: string,
  limit: number,
): CardTextKey {
  return ["artifact-card-text", workspaceId, artifactId, limit];
}

/** The bytes a card reads, or null when they are not text at all. */
export function fetchCardText([
  ,
  workspaceId,
  artifactId,
  limit,
]: CardTextKey): Promise<TextHead | null> {
  return readTextHead(artifactInlineContentUrl(workspaceId, artifactId), limit);
}

/** How much of this artifact a card reads: a text value whole, anything else a head. */
export function cardTextLimit(ref: ArtifactRef): number {
  return ref.artifact_type === "scalar.text" ||
    ref.artifact_type === "text.markdown"
    ? CARD_TEXT_VALUE_BYTES
    : CARD_TEXT_BYTES;
}

/**
 * Whether a card shows this artifact's bytes as text — its JSON indented, or its
 * words — instead of a file tile. Pictures, pages, and file containers are read
 * by their own readers, and a table is a grid rather than a document.
 */
export function readsAsCardText(
  ref: ArtifactRef,
  {
    contentType,
    fileName,
    htmlPage = isHtmlPageArtifact(ref),
  }: {
    contentType?: string | null;
    fileName?: string | null;
    htmlPage?: boolean;
  } = {},
): boolean {
  if (htmlPage || isGeoMapArtifact(ref) || isImageArtifact(ref, contentType))
    return false;
  if (isPdfArtifact(ref, { contentType, fileName })) return false;
  if (isTableFileArtifact(ref, { contentType, fileName })) return false;
  return true;
}

/**
 * What a card prints for the bytes it read: JSON indented, with JSON carried in
 * a string opened up and the one field a text value is stored in given way to
 * the words.
 */
export function formatCardText(
  head: TextHead,
  artifactType: string | undefined,
): string {
  return formatTextHead(head, {
    expandEmbeddedJson: true,
    unwrapField:
      artifactType === "scalar.text"
        ? "value"
        : artifactType === "text.markdown"
          ? "markdown"
          : undefined,
  });
}
