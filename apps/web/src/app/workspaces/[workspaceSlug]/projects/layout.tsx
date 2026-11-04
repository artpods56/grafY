"use client";

import type { ReactNode } from "react";
import { useParams } from "next/navigation";

import { Workbench } from "@/features/workbench";
import {
  NEW_PROJECT_ROUTE_ID,
  isSupportedWorkbenchProjectRoute,
} from "@/features/workbench/routes";
import { useWorkspaceContext } from "@/features/workspaces/WorkspaceLayout";
import { useAuthSession } from "@/features/auth/AuthSessionBoundary";

interface ProjectsLayoutProps {
  children: ReactNode;
}

export default function ProjectsLayout({ children }: ProjectsLayoutProps) {
  const { workspaceSlug, projectId } = useParams<{
    workspaceSlug: string;
    projectId?: string;
  }>();
  const { workspace } = useWorkspaceContext();
  const { session } = useAuthSession();

  if (
    !projectId ||
    !isSupportedWorkbenchProjectRoute(workspaceSlug, projectId)
  ) {
    return children;
  }

  return (
    <>
      <Workbench
        key={`${session.user_id}:${workspace.id}`}
        workspaceId={workspace.id}
        workspaceSlug={workspaceSlug}
        initialProjectId={projectId === NEW_PROJECT_ROUTE_ID ? null : projectId}
      />
      {children}
    </>
  );
}
