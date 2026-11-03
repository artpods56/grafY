import { notFound } from "next/navigation";

import { isSupportedWorkbenchProjectRoute } from "@/features/workbench/routes";

interface ProjectWorkbenchPageProps {
  params: Promise<{
    workspaceSlug: string;
    projectId: string;
  }>;
}

/**
 * The Project Workbench. The address names a Project: the Graphs it holds are
 * chosen inside it, and the first of them is where a person lands.
 */
export default async function ProjectWorkbenchPage({
  params,
}: ProjectWorkbenchPageProps) {
  const { workspaceSlug, projectId } = await params;
  if (!isSupportedWorkbenchProjectRoute(workspaceSlug, projectId)) {
    notFound();
  }

  return null;
}
