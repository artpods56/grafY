import type { ComponentType } from "react";

import type { ArtifactRef, ArtifactTypeSpec } from "@/lib/api";

export interface ArtifactEditorProps {
  workspaceId: string;
  artifactType: string;
  schemaVersion: number;
  initialPayload: Record<string, unknown>;
  saving?: boolean;
  error?: string | null;
  onSave: (nextPayload: Record<string, unknown>) => Promise<void> | void;
  onCancel: () => void;
  /** Live draft for switching Editor / Raw JSON without losing unsaved edits. */
  onDraftChange?: (nextPayload: Record<string, unknown>) => void;
}

export interface ArtifactEditorRegistration {
  typeKey: string;
  label: string;
  createDefaultPayload: () => Record<string, unknown>;
  Component: ComponentType<ArtifactEditorProps>;
}

export type ArtifactEditorIntent =
  | { kind: "create" }
  | { kind: "edit"; sourceRef: ArtifactRef }
  | { kind: "duplicate"; sourceRef: ArtifactRef };

export type ArtifactEditorSession =
  | { kind: "create"; position: { x: number; y: number } }
  | { kind: "edit"; cardId: string; sourceRef: ArtifactRef }
  | { kind: "duplicate"; sourceCardId: string; sourceRef: ArtifactRef };

export type AuthorableArtifactType = Pick<
  ArtifactTypeSpec,
  "key" | "title" | "authorable"
>;
