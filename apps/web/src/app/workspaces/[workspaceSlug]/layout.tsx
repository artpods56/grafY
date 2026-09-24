import type { ReactNode } from "react";

import WorkspaceLayout from "@/features/workspaces/WorkspaceLayout";

export default function WorkspaceSegmentLayout({
  children,
}: {
  children: ReactNode;
}) {
  return <WorkspaceLayout>{children}</WorkspaceLayout>;
}
