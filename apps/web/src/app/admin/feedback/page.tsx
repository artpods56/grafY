"use client";

import * as stylex from "@stylexjs/stylex";

import { useAuthSession } from "@/features/auth/AuthSessionBoundary";
import { FeedbackInbox } from "@/features/feedback/FeedbackInbox";
import { WorkspaceRail } from "@/features/workspaces/WorkspaceLayout";
import { useWorkspaces } from "@/hooks/use-api";

import { workspacesPageStyles as styles } from "../../workspaces/page.styles";

/** Operators read and triage the feedback people send from the app. */
export default function FeedbackReportsPage() {
  const { session, logout } = useAuthSession();
  const { data: workspaces } = useWorkspaces(session.user_id);

  return (
    <div className={stylex.props(styles.directory).className}>
      {workspaces ? (
        <WorkspaceRail
          workspaces={workspaces}
          session={session}
          onLogout={logout}
        />
      ) : null}
      <header className={stylex.props(styles.topBar).className}>
        <div className={stylex.props(styles.topBarInner).className}>
          <div className={stylex.props(styles.topBarTitleGroup).className}>
            <h1 className={stylex.props(styles.headerTitle).className}>
              Feedback reports
            </h1>
            <span className={stylex.props(styles.badge).className}>
              Operators
            </span>
          </div>
        </div>
      </header>
      <main className={stylex.props(styles.main).className}>
        <FeedbackInbox />
      </main>
    </div>
  );
}
