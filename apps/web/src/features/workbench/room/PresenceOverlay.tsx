"use client";

import * as stylex from "@stylexjs/stylex";
import type { PresenceActivityKind } from "./protocol";
import type { ProjectRoomPresenceStore } from "./presence-store";
import { usePresenceCollaborators } from "./usePresenceStore";

const s = stylex.create({
  strip: {
    position: "absolute",
    zIndex: 25,
    top: "62px",
    right: "13px",
    display: "flex",
    flexWrap: "wrap",
    justifyContent: "flex-end",
    gap: "6px",
    maxWidth: "min(280px, 40vw)",
    pointerEvents: "none",
  },
  chip: {
    display: "inline-flex",
    alignItems: "center",
    gap: "5px",
    minHeight: "24px",
    padding: "2px 8px 2px 6px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor:
      "light-dark(rgba(15, 23, 42, 0.12), rgba(255, 255, 255, 0.14))",
    borderRadius: "999px",
    backgroundColor:
      "light-dark(rgba(255, 255, 255, 0.88), rgba(24, 26, 30, 0.88))",
    color: "light-dark(#1f2937, #e5e7eb)",
    fontSize: "11px",
    fontWeight: 600,
    lineHeight: 1,
    boxShadow: "0 1px 2px rgba(0, 0, 0, 0.08)",
  },
  dot: {
    width: "8px",
    height: "8px",
    borderRadius: "999px",
    flex: "0 0 auto",
  },
  activity: {
    color: "light-dark(#6b7280, #9ca3af)",
    fontWeight: 500,
  },
});

function activityLabel(activity: PresenceActivityKind | null): string | null {
  if (activity === "moving_nodes") return "moving";
  if (activity === "editing_node") return "editing";
  if (activity === "connecting") return "connecting";
  return null;
}

export interface PresenceOverlayProps {
  store: ProjectRoomPresenceStore;
  graphId: string | null;
}

export function PresenceOverlay({ store, graphId }: PresenceOverlayProps) {
  return <CollaboratorStrip store={store} graphId={graphId} />;
}

function CollaboratorStrip({ store, graphId }: PresenceOverlayProps) {
  const collaborators = usePresenceCollaborators(store, graphId);

  if (collaborators.length === 0) return null;
  return (
    <div {...stylex.props(s.strip)} aria-label="Collaborators">
      {collaborators.map((collaborator) => {
        const activity = activityLabel(collaborator.activity);
        return (
          <span
            key={collaborator.sessionId}
            {...stylex.props(s.chip)}
            title={collaborator.displayName}
          >
            <span
              {...stylex.props(s.dot)}
              style={{ backgroundColor: collaborator.color }}
            />
            {collaborator.displayName}
            {activity ? (
              <span {...stylex.props(s.activity)}>{activity}</span>
            ) : null}
          </span>
        );
      })}
    </div>
  );
}
