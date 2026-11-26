"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { Notice } from "@/components/ui/notice";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Select } from "@/components/ui/select";
import {
  createArtifact,
  createdArtifactToRef,
  fetchArtifactJsonPayload,
  type ArtifactRef,
  type ArtifactTypeSpec,
} from "@/lib/api";
import { useEffectReducer } from "@/lib/state/use-effect-reducer";
import { tokens } from "@/lib/stylex/tokens.stylex";

import { formatArtifactTypeLabel } from "../artifact-type-label";
import {
  initialArtifactEditorDialogState,
  openArtifactEditorDialogEffects,
  reduceArtifactEditorDialog,
  type ArtifactEditorDialogAction,
  type ArtifactEditorDialogEffect,
} from "./artifact-editor-dialog-reducer";
import {
  authorableArtifactTypes,
  getArtifactEditor,
  getDefaultPayloadForType,
  JSON_EDITOR,
} from "./registry";
import type { ArtifactEditorIntent, ArtifactEditorSession } from "./types";

const s = stylex.create({
  stack: {
    display: "grid",
    gap: tokens.space3,
  },
  toolbar: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: tokens.space3,
    flexWrap: "wrap",
  },
});

function sessionIntent(session: ArtifactEditorSession): ArtifactEditorIntent {
  if (session.kind === "create") return { kind: "create" };
  if (session.kind === "edit") {
    return { kind: "edit", sourceRef: session.sourceRef };
  }
  return { kind: "duplicate", sourceRef: session.sourceRef };
}

function sessionKey(session: ArtifactEditorSession): string {
  if (session.kind === "create") {
    return `create:${session.position.x}:${session.position.y}`;
  }
  if (session.kind === "edit") {
    return `edit:${session.cardId}:${session.sourceRef.artifact_id}`;
  }
  return `duplicate:${session.sourceCardId}:${session.sourceRef.artifact_id}`;
}

function dialogTitle(intent: ArtifactEditorIntent): string {
  if (intent.kind === "create") return "Create artifact";
  if (intent.kind === "edit") return "Edit artifact";
  return "Duplicate and edit";
}

function dialogDescription(intent: ArtifactEditorIntent): string {
  if (intent.kind === "create") {
    return "Author a new artifact and place it on the canvas.";
  }
  if (intent.kind === "edit") {
    return "Save writes a new version and updates this card. Bound nodes switch to it and go stale.";
  }
  return "Save writes a new artifact and places a standalone card beside this one. The original output stays.";
}

function failureMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function ArtifactEditorDialog({
  session,
  workspaceId,
  artifactTypes,
  onSaved,
  onClose,
}: {
  session: ArtifactEditorSession | null;
  workspaceId: string;
  artifactTypes: readonly ArtifactTypeSpec[];
  onSaved: (ref: ArtifactRef, session: ArtifactEditorSession) => void;
  onClose: () => void;
}) {
  return (
    <Dialog
      open={session !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent size="wide">
        {session ? (
          <ArtifactEditorDialogSession
            key={sessionKey(session)}
            session={session}
            workspaceId={workspaceId}
            artifactTypes={artifactTypes}
            onSaved={onSaved}
            onClose={onClose}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function ArtifactEditorDialogSession({
  session,
  workspaceId,
  artifactTypes,
  onSaved,
  onClose,
}: {
  session: ArtifactEditorSession;
  workspaceId: string;
  artifactTypes: readonly ArtifactTypeSpec[];
  onSaved: (ref: ArtifactRef, session: ArtifactEditorSession) => void;
  onClose: () => void;
}) {
  const intent = React.useMemo(() => sessionIntent(session), [session]);
  const authorable = React.useMemo(
    () => authorableArtifactTypes(artifactTypes),
    [artifactTypes],
  );

  const runEffect = React.useCallback(
    (
      effect: ArtifactEditorDialogEffect,
      dispatch: React.Dispatch<ArtifactEditorDialogAction>,
    ) => {
      if (effect.type === "load") {
        void fetchArtifactJsonPayload(effect.workspaceId, effect.artifactId)
          .then((payload) => dispatch({ type: "loaded", payload }))
          .catch((error: unknown) =>
            dispatch({
              type: "load-failed",
              error: failureMessage(error, "The artifact could not be loaded."),
            }),
          );
        return;
      }
      void createArtifact(effect.workspaceId, {
        artifact_type: effect.artifactType,
        schema_version: effect.schemaVersion,
        payload: effect.payload,
        derived_from_artifact_id: effect.derivedFromArtifactId,
      })
        .then((created) => {
          onSaved(createdArtifactToRef(created), session);
          dispatch({ type: "saved" });
        })
        .catch((error: unknown) =>
          dispatch({
            type: "save-failed",
            error: failureMessage(error, "The artifact could not be saved."),
          }),
        );
    },
    [onSaved, session],
  );

  const initialState = React.useMemo(
    () =>
      initialArtifactEditorDialogState({
        workspaceId,
        intent,
        artifactType:
          intent.kind === "create" ? undefined : intent.sourceRef.artifact_type,
        schemaVersion:
          intent.kind === "create"
            ? undefined
            : intent.sourceRef.schema_version,
      }),
    [intent, workspaceId],
  );
  const [state, dispatch] = useEffectReducer(
    reduceArtifactEditorDialog,
    initialState,
    runEffect,
  );
  const loadStarted = React.useRef(false);

  React.useEffect(() => {
    if (loadStarted.current) return;
    loadStarted.current = true;
    for (const effect of openArtifactEditorDialogEffects(initialState)) {
      runEffect(effect, dispatch);
    }
  }, [dispatch, initialState, runEffect]);

  const spec =
    state.status === "ready" ||
    state.status === "loading" ||
    state.status === "failed"
      ? artifactTypes.find(
          (candidate) =>
            candidate.key.id === state.artifactType &&
            candidate.key.schema_version === state.schemaVersion,
        )
      : undefined;
  const editor =
    state.status === "ready"
      ? getArtifactEditor(state.artifactType, state.schemaVersion, spec)
      : null;
  const specialized = editor && editor !== JSON_EDITOR ? editor : null;
  const Editor =
    state.status === "ready"
      ? state.rawMode || !specialized
        ? JSON_EDITOR.Component
        : specialized.Component
      : null;

  return (
    <>
      <DialogHeader>
        <DialogTitle>{dialogTitle(intent)}</DialogTitle>
        <DialogDescription>{dialogDescription(intent)}</DialogDescription>
      </DialogHeader>
      <DialogBody>
        {state.status === "pick-type" ? (
          <div {...stylex.props(s.stack)}>
            {authorable.length === 0 ? (
              <Notice tone="warning">
                This workspace has no authorable artifact types yet.
              </Notice>
            ) : (
              <Field label="Artifact type">
                <Select
                  block
                  defaultValue=""
                  onChange={(event) => {
                    const [id, version] = event.target.value.split("@");
                    const schemaVersion = Number(version);
                    if (!id || !Number.isFinite(schemaVersion)) return;
                    dispatch({
                      type: "select-type",
                      artifactType: id,
                      schemaVersion,
                      payload: getDefaultPayloadForType(
                        id,
                        schemaVersion,
                        artifactTypes.find(
                          (candidate) =>
                            candidate.key.id === id &&
                            candidate.key.schema_version === schemaVersion,
                        ),
                      ),
                    });
                  }}
                >
                  <option value="" disabled>
                    Choose a type
                  </option>
                  {authorable.map((type) => (
                    <option
                      key={`${type.key.id}@${type.key.schema_version}`}
                      value={`${type.key.id}@${type.key.schema_version}`}
                    >
                      {formatArtifactTypeLabel(type.key, artifactTypes)}
                    </option>
                  ))}
                </Select>
              </Field>
            )}
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={onClose}
            >
              Cancel
            </Button>
          </div>
        ) : null}
        {state.status === "loading" ? (
          <Notice tone="neutral">Loading artifact…</Notice>
        ) : null}
        {state.status === "failed" ? (
          <div {...stylex.props(s.stack)}>
            <Notice tone="danger">{state.error}</Notice>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={onClose}
            >
              Close
            </Button>
          </div>
        ) : null}
        {state.status === "ready" && Editor ? (
          <div {...stylex.props(s.stack)}>
            <div {...stylex.props(s.toolbar)}>
              <span>
                {formatArtifactTypeLabel(
                  {
                    id: state.artifactType,
                    schema_version: state.schemaVersion,
                  },
                  artifactTypes,
                )}
              </span>
              {specialized ? (
                <SegmentedControl
                  aria-label="Editor mode"
                  size="sm"
                  value={state.rawMode ? "raw" : "editor"}
                  onValueChange={(value) =>
                    dispatch({
                      type: "set-raw-mode",
                      rawMode: value === "raw",
                    })
                  }
                  options={[
                    { value: "editor", label: specialized.label },
                    { value: "raw", label: "Raw JSON" },
                  ]}
                />
              ) : null}
            </div>
            <Editor
              key={`${state.artifactType}@${state.schemaVersion}:${state.rawMode ? "raw" : "editor"}`}
              workspaceId={workspaceId}
              artifactType={state.artifactType}
              schemaVersion={state.schemaVersion}
              initialPayload={state.payload}
              saving={state.saving}
              error={state.error}
              onDraftChange={(payload) => dispatch({ type: "draft", payload })}
              onCancel={onClose}
              onSave={(payload) => dispatch({ type: "save", payload })}
            />
          </div>
        ) : null}
      </DialogBody>
    </>
  );
}
