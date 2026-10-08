import * as stylex from "@stylexjs/stylex";

import type { ArtifactRef } from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { RemoteSelectionRing } from "../../room/RemoteSelectionRing";
import { TableArtifactRenderer } from "./artifact-renderers/table-renderer";

const s = stylex.create({
  body: {
    position: "relative",
    width: "100%",
    overflow: "hidden",
    boxSizing: "border-box",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusSm,
    backgroundColor: tokens.colorSurface,
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

export function TableArtifactBody({
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
      data-artifact-table-body="true"
      data-artifact-shadow-scope="table"
      {...bodyProps}
      className={`nodrag nopan nowheel ${bodyProps.className ?? ""}`}
      style={{ height }}
    >
      {!selected && remoteSelectionColor ? (
        <RemoteSelectionRing color={remoteSelectionColor} radius={5} />
      ) : null}
      <TableArtifactRenderer
        artifact={artifact}
        mode="table"
        presentation="canvas"
      />
    </div>
  );
}
