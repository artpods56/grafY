"use client";

import { useOptionalWorkspaceContext } from "@/features/workspaces/WorkspaceLayout";
import { useNodeRegistry } from "@/hooks/use-api";
import type { ArtifactTypeSpec } from "@/lib/api";

const NO_ARTIFACT_TYPES: readonly ArtifactTypeSpec[] = [];

/**
 * The registry's artifact types, so a canvas node can name a type the way the
 * catalog does instead of printing its identity. SWR shares one request across
 * every subscriber of a workspace, and a node rendered without a workspace (a
 * sandbox spike, a unit test) gets full `id@version` identities back from the
 * label helpers — never a bare id that has lost its version.
 */
export function useArtifactTypeCatalog(): readonly ArtifactTypeSpec[] {
  const workspace = useOptionalWorkspaceContext();
  const { data: registry } = useNodeRegistry(workspace?.workspace.id);
  return registry?.artifact_types ?? NO_ARTIFACT_TYPES;
}
