import type { ArtifactRef } from "@/lib/api";
import {
  createTiffTextRegionsEditorState,
  tiffTextRegionsEditorReducer,
  type TiffTextRegionsEditorAction,
  type TiffTextRegionsEditorState,
} from "../editors/tiff-text-regions/tiff-text-regions-editor-reducer";
import {
  serializeTiffTextRegionsPayload,
  type RegionReadingField,
  type TiffTextRegionsPayload,
} from "../editors/tiff-text-regions/types";

type SaveEffect = {
  workspaceId: string;
  artifact: ArtifactRef;
  payload: Record<string, unknown>;
};

export type TiffTextEditSession =
  | { kind: "inactive" }
  | {
      kind: "editing";
      url: string;
      editor: TiffTextRegionsEditorState;
      error: string | null;
    }
  | {
      kind: "saving";
      url: string;
      editor: TiffTextRegionsEditorState;
      effect: SaveEffect;
    };

export type TiffTextEditAction =
  | {
      type: "start";
      url: string;
      payload: TiffTextRegionsPayload;
      readingField: RegionReadingField;
    }
  | { type: "stop" }
  | { type: "edit"; action: TiffTextRegionsEditorAction }
  | { type: "save"; workspaceId: string; artifact: ArtifactRef }
  | { type: "saved"; effect: SaveEffect }
  | { type: "save_failed"; effect: SaveEffect; message: string };

export function reduceTiffTextEditSession(
  state: TiffTextEditSession,
  action: TiffTextEditAction,
  exec: (effect: SaveEffect) => void,
): TiffTextEditSession {
  switch (action.type) {
    case "start":
      if (state.kind !== "inactive" && state.url === action.url) return state;
      return {
        kind: "editing",
        url: action.url,
        editor: createTiffTextRegionsEditorState(
          action.payload,
          action.readingField,
        ),
        error: null,
      };
    case "stop":
      return state.kind === "inactive" ? state : { kind: "inactive" };
    case "edit": {
      if (state.kind !== "editing") return state;
      const editor = tiffTextRegionsEditorReducer(state.editor, action.action);
      return editor === state.editor ? state : { ...state, editor };
    }
    case "save": {
      if (state.kind !== "editing" || !state.editor.isDirty) return state;
      const effect = {
        workspaceId: action.workspaceId,
        artifact: action.artifact,
        payload: serializeTiffTextRegionsPayload(state.editor),
      };
      exec(effect);
      return { kind: "saving", url: state.url, editor: state.editor, effect };
    }
    case "saved": {
      if (state.kind !== "saving" || state.effect !== action.effect)
        return state;
      const editor = createTiffTextRegionsEditorState(
        state.editor.payload,
        state.editor.newRegionReadingField,
      );
      return {
        kind: "editing",
        url: state.url,
        editor: { ...editor, pageSize: state.editor.pageSize },
        error: null,
      };
    }
    case "save_failed":
      if (state.kind !== "saving" || state.effect !== action.effect)
        return state;
      return {
        kind: "editing",
        url: state.url,
        editor: state.editor,
        error: action.message,
      };
  }
}
