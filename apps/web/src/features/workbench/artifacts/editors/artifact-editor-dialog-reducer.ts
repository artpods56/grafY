import type { ArtifactRef } from "@/lib/api";
import type { ExecEffect } from "@/lib/state/effect-reducer";

import type { ArtifactEditorIntent } from "./types";

export type ArtifactEditorDialogState =
  | {
      status: "pick-type";
      workspaceId: string;
      intent: Extract<ArtifactEditorIntent, { kind: "create" }>;
    }
  | {
      status: "loading";
      workspaceId: string;
      intent: ArtifactEditorIntent;
      artifactType: string;
      schemaVersion: number;
    }
  | {
      status: "ready";
      workspaceId: string;
      intent: ArtifactEditorIntent;
      artifactType: string;
      schemaVersion: number;
      payload: Record<string, unknown>;
      rawMode: boolean;
      saving: boolean;
      error: string | null;
    }
  | {
      status: "failed";
      workspaceId: string;
      intent: ArtifactEditorIntent;
      artifactType: string;
      schemaVersion: number;
      error: string;
    };

export type ArtifactEditorDialogAction =
  | {
      type: "select-type";
      artifactType: string;
      schemaVersion: number;
      payload: Record<string, unknown>;
    }
  | { type: "loaded"; payload: Record<string, unknown> }
  | { type: "load-failed"; error: string }
  | { type: "set-raw-mode"; rawMode: boolean }
  | { type: "draft"; payload: Record<string, unknown> }
  | { type: "save"; payload: Record<string, unknown> }
  | { type: "save-failed"; error: string }
  | { type: "saved" };

export type ArtifactEditorDialogEffect =
  | { type: "load"; workspaceId: string; artifactId: string }
  | {
      type: "create";
      workspaceId: string;
      artifactType: string;
      schemaVersion: number;
      payload: Record<string, unknown>;
      derivedFromArtifactId: string | null;
    };

export function initialArtifactEditorDialogState(input: {
  workspaceId: string;
  intent: ArtifactEditorIntent;
  artifactType?: string;
  schemaVersion?: number;
}): ArtifactEditorDialogState {
  if (input.intent.kind === "create" && input.artifactType === undefined) {
    return {
      status: "pick-type",
      workspaceId: input.workspaceId,
      intent: input.intent,
    };
  }
  const source = sourceRef(input.intent);
  const artifactType = input.artifactType ?? source?.artifact_type;
  const schemaVersion = input.schemaVersion ?? source?.schema_version;
  if (artifactType === undefined || schemaVersion === undefined) {
    return {
      status: "failed",
      workspaceId: input.workspaceId,
      intent: input.intent,
      artifactType: artifactType ?? "",
      schemaVersion: schemaVersion ?? 1,
      error: "Choose an artifact type to edit.",
    };
  }
  if (input.intent.kind === "create") {
    return {
      status: "ready",
      workspaceId: input.workspaceId,
      intent: input.intent,
      artifactType,
      schemaVersion,
      payload: {},
      rawMode: false,
      saving: false,
      error: null,
    };
  }
  return {
    status: "loading",
    workspaceId: input.workspaceId,
    intent: input.intent,
    artifactType,
    schemaVersion,
  };
}

export function openArtifactEditorDialogEffects(
  state: ArtifactEditorDialogState,
): readonly ArtifactEditorDialogEffect[] {
  if (state.status !== "loading") return [];
  const source = sourceRef(state.intent);
  if (!source) return [];
  return [
    {
      type: "load",
      workspaceId: state.workspaceId,
      artifactId: source.artifact_id,
    },
  ];
}

export function reduceArtifactEditorDialog(
  state: ArtifactEditorDialogState,
  action: ArtifactEditorDialogAction,
  exec: ExecEffect<ArtifactEditorDialogEffect>,
): ArtifactEditorDialogState {
  switch (action.type) {
    case "select-type": {
      if (state.status !== "pick-type") return state;
      return {
        status: "ready",
        workspaceId: state.workspaceId,
        intent: state.intent,
        artifactType: action.artifactType,
        schemaVersion: action.schemaVersion,
        payload: action.payload,
        rawMode: false,
        saving: false,
        error: null,
      };
    }
    case "loaded": {
      if (state.status !== "loading") return state;
      return {
        status: "ready",
        workspaceId: state.workspaceId,
        intent: state.intent,
        artifactType: state.artifactType,
        schemaVersion: state.schemaVersion,
        payload: action.payload,
        rawMode: false,
        saving: false,
        error: null,
      };
    }
    case "load-failed": {
      if (state.status !== "loading") return state;
      return {
        status: "failed",
        workspaceId: state.workspaceId,
        intent: state.intent,
        artifactType: state.artifactType,
        schemaVersion: state.schemaVersion,
        error: action.error,
      };
    }
    case "set-raw-mode": {
      if (state.status !== "ready" || state.saving) return state;
      if (state.rawMode === action.rawMode) return state;
      return { ...state, rawMode: action.rawMode };
    }
    case "draft": {
      if (state.status !== "ready" || state.saving) return state;
      return { ...state, payload: action.payload };
    }
    case "save": {
      if (state.status !== "ready" || state.saving) return state;
      exec({
        type: "create",
        workspaceId: state.workspaceId,
        artifactType: state.artifactType,
        schemaVersion: state.schemaVersion,
        payload: action.payload,
        derivedFromArtifactId: sourceRef(state.intent)?.artifact_id ?? null,
      });
      return { ...state, payload: action.payload, saving: true, error: null };
    }
    case "save-failed": {
      if (state.status !== "ready") return state;
      return { ...state, saving: false, error: action.error };
    }
    case "saved": {
      if (state.status !== "ready") return state;
      return { ...state, saving: false, error: null };
    }
    default: {
      const _exhaustive: never = action;
      return _exhaustive;
    }
  }
}

function sourceRef(intent: ArtifactEditorIntent): ArtifactRef | null {
  if (intent.kind === "create") return null;
  return intent.sourceRef;
}
