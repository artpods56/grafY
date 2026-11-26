// @vitest-environment jsdom

import { act } from "react";
import * as React from "react";
import { annotationsFromPresentation } from "../authoring/annotations";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

import type { ArtifactViewerCanvasState } from "../artifacts/artifact-viewer";
import type { ArtifactViewerActivity } from "../artifacts/artifact-interactions";
import {
  useArtifactViewerCommands,
  useArtifactViewerState,
  type ArtifactViewerRoomSync,
} from "./workbench-artifact-viewers";

const EMPTY_STATE: ArtifactViewerCanvasState = {
  nodes: [],
  edges: [],
  bindings: [],
  annotations: [],
};

const BLOCKED_MESSAGE =
  "Editing is unavailable until this graph is synchronized.";

type Commands = ReturnType<typeof useArtifactViewerCommands>;

type Harness = {
  commands: Commands;
  annotations: number;
  activities: Record<
    string,
    { activity: ArtifactViewerActivity; revision: number }
  >;
  runError: string | null;
};

async function mountHarness(options: {
  enabled?: boolean;
  submits: ArtifactViewerCanvasState[];
}) {
  const submitted: ArtifactViewerCanvasState[] = options.submits;
  let harness: Harness | null = null;

  function HarnessComponent() {
    const [artifactViewers, setArtifactViewers, artifactViewersRef] =
      useArtifactViewerState(EMPTY_STATE);
    const [activities, setArtifactViewerActivities] = React.useState<
      Record<string, { activity: ArtifactViewerActivity; revision: number }>
    >({});
    const [runError, setRunError] = React.useState<string | null>(null);

    const localAuthoringEnabledRef = React.useRef(options.enabled ?? true);
    const localAuthoringBlockedMessageRef = React.useRef(BLOCKED_MESSAGE);
    const artifactViewerActivityRevisionRef = React.useRef(0);
    const presentationRoomSyncRef = React.useRef<ArtifactViewerRoomSync>({
      submitReplace: (state) => {
        submitted.push(state);
      },
    });
    const authoredDocumentRef = React.useRef<{ origins: [] }>({ origins: [] });
    const applyAuthoringCommands = vi.fn();

    const commands = useArtifactViewerCommands({
      artifactViewers,
      artifactViewersRef,
      artifactViewerActivityRevisionRef,
      applyAuthoringCommands,
      authoredDocumentRef,
      localAuthoringBlockedMessageRef,
      localAuthoringEnabledRef,
      presentationRoomSyncRef,
      setArtifactViewerActivities,
      setArtifactViewers,
      setRunError,
    });

    harness = {
      commands,
      annotations: artifactViewers.annotations.length,
      activities,
      runError,
    };
    return null;
  }

  const root = createRoot(document.createElement("div"));
  await act(async () => {
    root.render(
      React.createElement(
        React.StrictMode,
        null,
        React.createElement(HarnessComponent),
      ),
    );
  });
  return {
    get harness(): Harness {
      if (!harness) {
        throw new Error("harness did not render");
      }
      return harness;
    },
    unmount: () => root.unmount(),
  };
}

describe("useArtifactViewerCommands", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("refuses an annotation edit and reports why while authoring is blocked", async () => {
    const submitted: ArtifactViewerCanvasState[] = [];
    const view = await mountHarness({ enabled: false, submits: submitted });

    await act(async () => {
      view.harness.commands.updateAnnotationText(
        "note-1",
        "typed while blocked",
      );
    });

    expect(submitted).toEqual([]);
    expect(view.harness.runError).toBe(BLOCKED_MESSAGE);
    view.unmount();
  });

  it("submits one presentation edit under Strict Mode", async () => {
    const submitted: ArtifactViewerCanvasState[] = [];
    const view = await mountHarness({ submits: submitted });

    await act(async () => {
      const annotations = annotationsFromPresentation({
        annotations: [
          {
            id: "note-1",
            kind: "text",
            position: { x: 0, y: 0 },
            text: "Note",
            color: "#ffaa33",
            layout: { width: 240, height: 160 },
          },
        ],
      });
      view.harness.commands.commitArtifactViewers((current) => ({
        ...current,
        annotations,
      }));
      await Promise.resolve();
    });

    expect(submitted).toHaveLength(1);
    expect(view.harness.annotations).toBe(1);
    expect(submitted[0]?.annotations[0]?.id).toBe("note-1");
    view.unmount();
  });

  it("numbers each activity so a stale result cannot overwrite a newer one", async () => {
    const submitted: ArtifactViewerCanvasState[] = [];
    const view = await mountHarness({ submits: submitted });
    const activity = (title: string): ArtifactViewerActivity => ({
      state: "working",
      title,
      message: "",
    });

    await act(async () => {
      view.harness.commands.updateArtifactViewerActivity(
        "node-1",
        activity("one"),
      );
    });
    const first = view.harness.activities["node-1"];

    await act(async () => {
      view.harness.commands.updateArtifactViewerActivity(
        "node-1",
        activity("two"),
      );
    });
    const second = view.harness.activities["node-1"];

    expect(first?.revision).toBe(1);
    expect(second?.revision).toBe(2);
    expect(second?.activity.title).toBe("two");

    await act(async () => {
      view.harness.commands.updateArtifactViewerActivity("node-1", null);
    });
    expect(view.harness.activities["node-1"]).toBeUndefined();
    view.unmount();
  });
});
