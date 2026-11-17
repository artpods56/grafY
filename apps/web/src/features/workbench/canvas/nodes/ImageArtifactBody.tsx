import type * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { TiffArtifactView } from "./TiffArtifactView";
import { ImageOff } from "lucide-react";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { RemoteSelectionRing } from "../../room/RemoteSelectionRing";
import { ArtifactStack, type StackPlace } from "./ArtifactStack";

const s = stylex.create({
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "12px",
    height: "24px",
    fontSize: tokens.fontSizeXs,
    userSelect: "none",
    transitionProperty: "opacity",
    transitionDuration: "120ms",
    "@media (prefers-reduced-motion: reduce)": { transitionDuration: "0ms" },
  },
  quiet: { opacity: 0.55 },
  name: {
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  // The name wins the row: the type gives way first, down to under half.
  contract: {
    flexShrink: 1,
    minWidth: 0,
    maxWidth: "45%",
    overflow: "hidden",
    color: tokens.colorMuted,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  stack: { position: "relative", width: "100%" },
  media: {
    position: "relative",
    width: "100%",
    overflow: "hidden",
    borderRadius: tokens.radiusSm,
    backgroundColor: "transparent",
    boxShadow: "none",
    // The shadow tokens share a layer count, so tiers cross-fade with the lift.
    transitionProperty: "box-shadow",
    transitionDuration: {
      default: "180ms",
      "@media (prefers-reduced-motion: reduce)": "0ms",
    },
    transitionTimingFunction: "cubic-bezier(0.22, 1, 0.36, 1)",
  },
  raised: { boxShadow: tokens.shadowNodeActive },
  dragged: { boxShadow: tokens.shadowNodeDragged },
  image: {
    display: "block",
    width: "100%",
    height: "100%",
    objectFit: "contain",
  },
  stacked: {
    position: "absolute",
    backgroundColor: tokens.colorSurface,
  },
  unavailable: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "8px",
    height: "100%",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
  },
});

/** Shared with file artifacts so both kinds label the same way. */
export const ARTIFACT_LABEL_HEIGHT = "24px";

export function ArtifactLabel({
  title,
  contract,
  contractTooltip,
  selected,
  image = false,
}: {
  title: string;
  contract: string;
  /** The full `id@version` behind the label, shown on hover. */
  contractTooltip?: string;
  selected: boolean;
  image?: boolean;
}) {
  return (
    <div
      data-artifact-label="true"
      data-artifact-image-header={image ? "true" : undefined}
      {...stylex.props(s.header, !selected ? s.quiet : null)}
    >
      <span title={title} {...stylex.props(s.name)}>
        {title}
      </span>
      <span title={contractTooltip ?? contract} {...stylex.props(s.contract)}>
        {contract}
      </span>
    </div>
  );
}

export function ImageArtifactBody({
  images,
  workspaceId,
  sequence,
  mediaHeight,
  selected,
  tier,
  remoteSelectionColor,
  frontIndex = 0,
  overlay,
  onSize,
  onError,
}: {
  workspaceId: string;
  images: readonly {
    id: string;
    url: string;
    name: string;
    failed: boolean;
    tiff: boolean;
  }[];
  sequence: boolean;
  mediaHeight: number;
  selected: boolean;
  tier: "rest" | "active" | "dragged";
  remoteSelectionColor?: string | null;
  /** The image at the front of a sequence; `images` keep their own order. */
  frontIndex?: number;
  /** Drawn over the front image, e.g. its pager. */
  overlay?: React.ReactNode;
  onSize: (id: string, width: number, height: number) => void;
  onError: (id: string) => void;
}) {
  type Image = (typeof images)[number];
  const media = (
    image: Image,
    {
      front,
      tail,
      place,
    }: { front: boolean; tail?: boolean; place?: StackPlace },
  ) => (
    <div
      {...place}
      data-artifact-media={tail ? undefined : "true"}
      data-artifact-shadow-scope={
        tail ? undefined : sequence ? "sequence-item" : "image"
      }
      {...stylex.props(
        s.media,
        sequence ? s.stacked : null,
        tier === "active" ? s.raised : null,
        tier === "dragged" ? s.dragged : null,
      )}
      style={{ height: mediaHeight, ...place?.style }}
    >
      {!selected && remoteSelectionColor && front ? (
        <RemoteSelectionRing color={remoteSelectionColor} radius={5} />
      ) : null}
      {image.tiff ? (
        <TiffArtifactView
          workspaceId={workspaceId}
          artifactId={image.id}
          name={image.name}
        />
      ) : image.failed ? (
        <div {...stylex.props(s.unavailable)}>
          <ImageOff size={18} /> Preview unavailable
        </div>
      ) : (
        /* eslint-disable-next-line @next/next/no-img-element -- workspace artifact bytes bypass the public image optimizer */
        <img
          src={image.url}
          alt={image.name}
          loading="lazy"
          decoding="async"
          draggable={false}
          onLoad={(event) => {
            const { naturalWidth, naturalHeight } = event.currentTarget;
            if (naturalWidth && naturalHeight)
              onSize(image.id, naturalWidth, naturalHeight);
          }}
          onError={() => onError(image.id)}
          {...stylex.props(s.image)}
        />
      )}
    </div>
  );

  if (sequence)
    return (
      <ArtifactStack
        count={images.length}
        index={frontIndex}
        frontHeight={mediaHeight}
        overlay={overlay}
        renderLayer={(slot, place) => {
          const image = images[slot.item];
          return image
            ? media(image, {
                front: slot.slot === 0 && !slot.tail,
                tail: slot.tail,
                place,
              })
            : null;
        }}
      />
    );
  const image = images[0];
  return (
    <div {...stylex.props(s.stack)} style={{ height: mediaHeight }}>
      {image ? media(image, { front: true }) : null}
    </div>
  );
}
