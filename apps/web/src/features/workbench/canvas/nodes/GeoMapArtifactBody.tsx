"use client";

import * as stylex from "@stylexjs/stylex";

import type { ArtifactRef } from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { RemoteSelectionRing } from "../../room/RemoteSelectionRing";
import { GeoMapArtifactRenderer } from "./geo-map-artifact-renderer";

const s = stylex.create({
  body: {
    position: "relative",
    display: "grid",
    gridTemplateRows: "minmax(0, 1fr)",
    width: "100%",
    overflow: "hidden",
    boxSizing: "border-box",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusSm,
    backgroundColor: tokens.colorSurfaceSunken,
    cursor: "default",
    boxShadow: "none",
    transitionProperty: "box-shadow",
    transitionDuration: {
      default: "180ms",
      "@media (prefers-reduced-motion: reduce)": "0ms",
    },
    transitionTimingFunction: "cubic-bezier(0.22, 1, 0.36, 1)",
  },
  raised: { boxShadow: tokens.shadowNodeActive },
  dragged: { boxShadow: tokens.shadowNodeDragged },
});

export function GeoMapArtifactBody({
  artifact,
  height,
  selected,
  tier,
  remoteSelectionColor,
}: {
  artifact: ArtifactRef;
  height: number;
  selected: boolean;
  tier: "rest" | "active" | "dragged";
  remoteSelectionColor?: string | null;
}) {
  const bodyProps = stylex.props(
    s.body,
    tier === "active" ? s.raised : null,
    tier === "dragged" ? s.dragged : null,
  );
  return (
    <div
      data-artifact-geo-map-body="true"
      data-artifact-shadow-scope="map"
      {...bodyProps}
      className={`nodrag nopan nowheel ${bodyProps.className ?? ""}`}
      style={{ height }}
    >
      {!selected && remoteSelectionColor ? (
        <RemoteSelectionRing color={remoteSelectionColor} radius={5} />
      ) : null}
      <GeoMapArtifactRenderer
        artifact={artifact}
        mode="map"
        autoLoad
        presentation="canvas"
        availableHeight={Math.max(160, height - 2)}
      />
    </div>
  );
}
