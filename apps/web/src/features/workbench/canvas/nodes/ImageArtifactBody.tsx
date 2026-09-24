import * as stylex from "@stylexjs/stylex";
import { ImageOff } from "lucide-react";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { RemoteSelectionRing } from "../../room/RemoteSelectionRing";

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
  contract: { flexShrink: 0, color: tokens.colorMuted },
  stack: { position: "relative", width: "100%" },
  media: {
    position: "relative",
    width: "100%",
    overflow: "hidden",
    borderRadius: tokens.radiusSm,
    backgroundColor: "transparent",
    boxShadow: "none",
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
  selected,
  image = false,
}: {
  title: string;
  contract: string;
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
      <span title={contract} {...stylex.props(s.contract)}>
        {contract}
      </span>
    </div>
  );
}

export function ImageArtifactBody({
  images,
  sequence,
  mediaHeight,
  selected,
  tier,
  remoteSelectionColor,
  onSize,
  onError,
}: {
  images: readonly { id: string; url: string; name: string; failed: boolean }[];
  sequence: boolean;
  mediaHeight: number;
  selected: boolean;
  tier: "rest" | "active" | "dragged";
  remoteSelectionColor?: string | null;
  onSize: (id: string, width: number, height: number) => void;
  onError: (id: string) => void;
}) {
  // The first item is the front image; the visible layers behind it follow order.
  const visible = images.slice(0, 3);
  return (
    <div
      aria-label={sequence ? `${images.length} items in sequence` : undefined}
      {...stylex.props(s.stack)}
      style={{
        height: mediaHeight + (sequence ? (visible.length - 1) * 8 : 0),
      }}
    >
      {visible.map((image, index) => (
        <div
          key={image.id}
          data-artifact-media="true"
          data-artifact-shadow-scope={sequence ? "sequence-item" : "image"}
          {...stylex.props(
            s.media,
            sequence ? s.stacked : null,
            tier === "active" ? s.raised : null,
            tier === "dragged" ? s.dragged : null,
          )}
          style={{
            height: mediaHeight,
            ...(sequence
              ? {
                  width: `calc(100% - ${(visible.length - 1) * 12}px)`,
                  left: (visible.length - 1 - index) * 12,
                  top: index * 8,
                  zIndex: visible.length - index,
                }
              : {}),
          }}
        >
          {!selected && remoteSelectionColor && index === 0 ? (
            <RemoteSelectionRing color={remoteSelectionColor} radius={5} />
          ) : null}
          {image.failed ? (
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
      ))}
    </div>
  );
}
