"use client";

import * as stylex from "@stylexjs/stylex";
import { ImageIcon } from "lucide-react";

import { tokens } from "@/lib/stylex/tokens.stylex";

const MONO_FONT =
  "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace";

const s = stylex.create({
  image: {
    position: "absolute",
    inset: 0,
    display: "block",
    width: "100%",
    height: "100%",
    objectFit: "cover",
    pointerEvents: "none",
    userSelect: "none",
  },
  placeholder: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    gap: "4px",
    maxWidth: "100%",
    paddingInline: "12px",
    boxSizing: "border-box",
    color: tokens.colorSubtle,
    fontSize: "10px",
    textAlign: "center",
  },
  placeholderMeta: {
    fontFamily: MONO_FONT,
    fontSize: "9px",
  },
});

function reportImageSize(
  img: HTMLImageElement | null,
  imageUrl: string | null | undefined,
  onImageLoad?: (
    imageUrl: string,
    size: { width: number; height: number },
  ) => void,
) {
  if (
    !img ||
    !imageUrl ||
    !onImageLoad ||
    img.naturalWidth <= 0 ||
    img.naturalHeight <= 0
  ) {
    return;
  }
  onImageLoad(imageUrl, {
    width: img.naturalWidth,
    height: img.naturalHeight,
  });
}

/**
 * Canvas plate for preview kind `image`.
 *
 * `ArtifactPreview` calls this with fields the scene already stored on the
 * surface. The next kind is the same shape: one component, then one case.
 */
export function ImageCardPreview({
  imageUrl,
  alt,
  dimensionsLabel,
  showDimensions = true,
  onImageLoad,
}: {
  imageUrl?: string | null;
  alt: string;
  dimensionsLabel?: string | null;
  showDimensions?: boolean;
  onImageLoad?: (
    imageUrl: string,
    size: { width: number; height: number },
  ) => void;
}) {
  if (!imageUrl) {
    return (
      <div data-artifact-placeholder="image" {...stylex.props(s.placeholder)}>
        <ImageIcon size={18} aria-hidden="true" />
        {showDimensions && dimensionsLabel ? (
          <span {...stylex.props(s.placeholderMeta)}>{dimensionsLabel}</span>
        ) : null}
      </div>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element -- artifact bytes have no predictable size for the image optimizer
    <img
      ref={(img) => {
        if (img?.complete) reportImageSize(img, imageUrl, onImageLoad);
      }}
      src={imageUrl}
      alt={alt}
      draggable={false}
      onLoad={(event) =>
        reportImageSize(event.currentTarget, imageUrl, onImageLoad)
      }
      {...stylex.props(s.image)}
    />
  );
}
