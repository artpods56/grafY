import { describe, expect, it } from "vitest";

import { runEffectReducer } from "@/lib/state/effect-reducer";

import {
  initialArtifactEditorDialogState,
  openArtifactEditorDialogEffects,
  reduceArtifactEditorDialog,
} from "./artifact-editor-dialog-reducer";

const SOURCE = {
  artifact_id: "11111111-1111-4111-8111-111111111111",
  artifact_type: "scalar.text",
  schema_version: 1,
  content_hash: null,
};

describe("artifact editor dialog reducer", () => {
  it("starts create on the type picker and seeds the default payload", () => {
    const start = initialArtifactEditorDialogState({
      workspaceId: "ws",
      intent: { kind: "create" },
    });
    expect(start.status).toBe("pick-type");
    const { state, effects } = runEffectReducer(
      reduceArtifactEditorDialog,
      start,
      {
        type: "select-type",
        artifactType: "scalar.text",
        schemaVersion: 1,
        payload: { value: "" },
      },
    );
    expect(effects).toEqual([]);
    expect(state).toMatchObject({
      status: "ready",
      artifactType: "scalar.text",
      payload: { value: "" },
      rawMode: false,
    });
  });

  it("loads an existing artifact and saves a derived copy", () => {
    const start = initialArtifactEditorDialogState({
      workspaceId: "ws",
      intent: { kind: "edit", sourceRef: SOURCE },
    });
    expect(start.status).toBe("loading");
    expect(openArtifactEditorDialogEffects(start)).toEqual([
      { type: "load", workspaceId: "ws", artifactId: SOURCE.artifact_id },
    ]);
    const loaded = runEffectReducer(reduceArtifactEditorDialog, start, {
      type: "loaded",
      payload: { value: "Draft" },
    }).state;
    const saved = runEffectReducer(reduceArtifactEditorDialog, loaded, {
      type: "save",
      payload: { value: "Edited" },
    });
    expect(saved.state).toMatchObject({ saving: true, error: null });
    expect(saved.effects).toEqual([
      {
        type: "create",
        workspaceId: "ws",
        artifactType: "scalar.text",
        schemaVersion: 1,
        payload: { value: "Edited" },
        derivedFromArtifactId: SOURCE.artifact_id,
      },
    ]);
  });

  it("creates from scratch without a derived_from id", () => {
    const start = initialArtifactEditorDialogState({
      workspaceId: "ws",
      intent: { kind: "create" },
      artifactType: "table.data",
      schemaVersion: 1,
    });
    const { effects } = runEffectReducer(reduceArtifactEditorDialog, start, {
      type: "save",
      payload: { columns: [], rows: [] },
    });
    expect(effects[0]).toMatchObject({
      type: "create",
      derivedFromArtifactId: null,
      artifactType: "table.data",
    });
  });
});
