"use client";

import * as React from "react";
import { useRouter } from "next/navigation";

import { ThresholdStatus } from "@/components/threshold-status";
import { useAuthSession } from "@/features/auth/AuthSessionBoundary";
import { resolveSelectedWorkspace } from "@/features/workspaces/WorkspaceLayout";
import { useWorkspaces } from "@/hooks/use-api";

export function WorkspaceGraphRedirect() {
  const router = useRouter();
  const { session } = useAuthSession();
  const { data: workspaces, error, mutate } = useWorkspaces(session.user_id);

  React.useEffect(() => {
    if (!workspaces) return;
    const workspace =
      resolveSelectedWorkspace(workspaces, undefined) ?? workspaces[0];
    if (!workspace) {
      router.replace("/workspaces");
      return;
    }
    router.replace(`/workspaces/${encodeURIComponent(workspace.slug)}/graphs`);
  }, [router, workspaces]);

  if (error) {
    return (
      <ThresholdStatus
        title="Workspaces couldn't be loaded"
        detail="Grafy could not determine which workspace to open."
        action={
          <button type="button" onClick={() => void mutate()}>
            Try again
          </button>
        }
      />
    );
  }

  return (
    <ThresholdStatus
      title="Opening graphs"
      detail="Selecting your workspace…"
      loading
    />
  );
}

export default WorkspaceGraphRedirect;
