// @vitest-environment jsdom

import { act } from "react";
import * as React from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
}));

import type { ArtifactViewerCanvasState } from "../canvas/artifact-viewer";
import type {
  ArtifactInteractionField,
  ArtifactViewerActivity,
} from "../canvas/artifact-interactions";
import {
  useArtifactViewerCommands,
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
  fields: Record<string, ArtifactInteractionField[]>;
  runError: string | null;
};

async function mountHarness(options: {
  enabled?: boolean;
  submits: ArtifactViewerCanvasState[];
}) {
  const submitted: ArtifactViewerCanvasState[] = options.submits;
  let harness: Harness | null = null;

  function HarnessComponent() {
    const [artifactViewers, setArtifactViewers] = React.useState(EMPTY_STATE);
    const [, setArtifactViewerSelections] = React.useState({});
    const [fields, setArtifactViewerFields] = React.useState<
      Record<string, ArtifactInteractionField[]>
    >({});
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
      artifactViewerActivityRevisionRef,
      applyAuthoringCommands,
      authoredDocumentRef,
      localAuthoringBlockedMessageRef,
      localAuthoringEnabledRef,
      presentationRoomSyncRef,
      setArtifactViewerActivities,
      setArtifactViewerFields,
      setArtifactViewerSelections,
      setArtifactViewers,
      setRunError,
    });

    harness = {
      commands,
      annotations: artifactViewers.annotations.length,
      activities,
      fields,
      runError,
    };
    return null;
  }

  const root = createRoot(document.createElement("div"));
  await act(async () => {
    root.render(React.createElement(HarnessComponent));
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

  it("publishes the committed state to the room once per edit", async () => {
    const submitted: ArtifactViewerCanvasState[] = [];
    const view = await mountHarness({ submits: submitted });

    await act(async () => {
      view.harness.commands.updateAnnotationColor("note-1", "amber");
      await Promise.resolve();
    });

    expect(submitted).toEqual([EMPTY_STATE]);
    view.unmount();
  });

  it("keeps the previous field record when the reported fields are unchanged", async () => {
    const submitted: ArtifactViewerCanvasState[] = [];
    const view = await mountHarness({ submits: submitted });
    const fields: ArtifactInteractionField[] = [
      { id: "city", title: "City", valueType: "string" },
    ];

    await act(async () => {
      view.harness.commands.updateArtifactViewerFields("node-1", fields);
    });
    const afterFirst = view.harness.fields;

    await act(async () => {
      view.harness.commands.updateArtifactViewerFields("node-1", [
        { id: "city", title: "City", valueType: "string" },
      ]);
    });

    expect(view.harness.fields).toBe(afterFirst);
    expect(view.harness.fields["node-1"]).toEqual(fields);
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
