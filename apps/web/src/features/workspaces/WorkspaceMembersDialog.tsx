"use client";

import * as React from "react";
import { UserPlus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Notice, type NoticeTone } from "@/components/ui/notice";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useAuthSession } from "@/features/auth/AuthSessionBoundary";
import { useWorkspaceInvitations, useWorkspaceMembers } from "@/hooks/use-api";
import {
  cancelWorkspaceInvitation,
  changeWorkspaceMemberRole,
  createWorkspaceInvitation,
  removeWorkspaceMember,
  resolveWorkspaceInvitationCandidate,
  type WorkspaceInvitationCandidate,
  type WorkspaceMember,
  type WorkspaceRole,
} from "@/lib/api";
import { ApiError } from "@/lib/api/client";
import {
  executeMemberMutation,
  MemberListRefreshError,
} from "./workspace-member-mutation";
import { useWorkspaceContext } from "./WorkspaceLayout";

const roles: readonly WorkspaceRole[] = ["viewer", "editor", "owner"];
const roleDescriptions: Record<WorkspaceRole, string> = {
  viewer: "Can view graphs, artifacts, history, and shared activity.",
  editor: "Can also create, edit, and run graphs.",
  owner: "Has full access, including member and workspace administration.",
};

type MemberAction =
  | { kind: "role"; member: WorkspaceMember; role: WorkspaceRole }
  | { kind: "remove"; member: WorkspaceMember };

function memberName(member: WorkspaceMember): string {
  return member.user.display_name ?? member.user.email ?? "Workspace member";
}

/** A message in the members panel. Its tone is what the text actually says. */
type MemberMessage = { text: string; tone: NoticeTone };

function operationError(error: unknown): MemberMessage {
  if (error instanceof MemberListRefreshError)
    return {
      text: "Change saved, but member list refresh failed.",
      tone: "warning",
    };
  if (!(error instanceof ApiError))
    return {
      text: "The member change could not be completed.",
      tone: "danger",
    };
  if (error.status === 403)
    return {
      text: "Permission changed. This dialog was closed; the denied change was not retried.",
      tone: "danger",
    };
  if (error.status === 404)
    return {
      text: "The requested person or workspace is no longer available.",
      tone: "danger",
    };
  if (error.status === 409)
    return {
      text: "The member or invitation state changed elsewhere. Refresh and try again.",
      tone: "danger",
    };
  return { text: `Member change failed (${error.status}).`, tone: "danger" };
}

export function WorkspaceMembersDialog() {
  const { session } = useAuthSession();
  const { workspace, refreshWorkspaces } = useWorkspaceContext();
  const [open, setOpen] = React.useState(false);
  const {
    data: members,
    error: membersError,
    mutate: mutateMembers,
  } = useWorkspaceMembers(session.user_id, open ? workspace.id : undefined);
  const {
    data: invitations,
    error: invitationsError,
    mutate: mutateInvitations,
  } = useWorkspaceInvitations(session.user_id, open ? workspace.id : undefined);
  const [email, setEmail] = React.useState("");
  const [role, setRole] = React.useState<WorkspaceRole>("viewer");
  const [candidate, setCandidate] =
    React.useState<WorkspaceInvitationCandidate | null>(null);
  const [fieldError, setFieldError] = React.useState<string | null>(null);
  const [busyKey, setBusyKey] = React.useState<string | null>(null);
  const [message, setMessage] = React.useState<MemberMessage | null>(null);
  const [memberAction, setMemberAction] = React.useState<MemberAction | null>(
    null,
  );
  const [authorityUncertain, setAuthorityUncertain] = React.useState(false);
  const emailInput = React.useRef<HTMLInputElement>(null);

  const runMemberMutation = async (
    key: string,
    operation: () => Promise<unknown>,
  ): Promise<boolean> => {
    if (authorityUncertain) return false;
    setBusyKey(key);
    setMessage(null);
    try {
      await executeMemberMutation(operation, mutateMembers, refreshWorkspaces);
      return true;
    } catch (caught) {
      setMessage(operationError(caught));
      if (
        (caught instanceof ApiError && caught.status === 403) ||
        caught instanceof MemberListRefreshError
      ) {
        setAuthorityUncertain(true);
        setOpen(false);
      }
      return false;
    } finally {
      setBusyKey(null);
    }
  };

  const resolveCandidate = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedEmail = email.trim();
    setCandidate(null);
    setFieldError(null);
    setMessage(null);
    if (!normalizedEmail) {
      setFieldError(
        "Enter the verified email address of an existing GrafY user.",
      );
      emailInput.current?.focus();
      return;
    }
    setBusyKey("resolve");
    try {
      setCandidate(
        await resolveWorkspaceInvitationCandidate(workspace.id, {
          email: normalizedEmail,
        }),
      );
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 404) {
        setFieldError(
          "No eligible GrafY user was found for that verified email.",
        );
        emailInput.current?.focus();
      } else {
        setMessage(operationError(caught));
      }
    } finally {
      setBusyKey(null);
    }
  };

  const sendInvitation = async () => {
    if (!candidate) return;
    setBusyKey("invite");
    setMessage(null);
    try {
      await createWorkspaceInvitation(workspace.id, {
        email: email.trim(),
        role,
      });
      await mutateInvitations();
      setEmail("");
      setRole("viewer");
      setCandidate(null);
      setMessage({
        text: "Invitation sent. Access will begin only after it is accepted.",
        tone: "neutral",
      });
    } catch (caught) {
      setMessage(operationError(caught));
    } finally {
      setBusyKey(null);
    }
  };

  const cancelInvitation = async (invitationId: string) => {
    setBusyKey(invitationId);
    setMessage(null);
    try {
      await cancelWorkspaceInvitation(workspace.id, invitationId);
      await mutateInvitations();
      setMessage({ text: "Invitation cancelled.", tone: "neutral" });
    } catch (caught) {
      setMessage(operationError(caught));
    } finally {
      setBusyKey(null);
    }
  };

  const confirmMemberAction = async () => {
    if (!memberAction) return;
    const { member } = memberAction;
    const succeeded =
      memberAction.kind === "remove"
        ? await runMemberMutation(member.user.id, () =>
            removeWorkspaceMember(workspace.id, member.user.id),
          )
        : await runMemberMutation(member.user.id, () =>
            changeWorkspaceMemberRole(workspace.id, member.user.id, {
              role: memberAction.role,
            }),
          );
    if (succeeded) setMemberAction(null);
  };

  return (
    <>
      <Button
        variant="secondary"
        size="lg"
        className="grafy-workspace-settings__action"
        disabled={authorityUncertain}
        onClick={() => setOpen(true)}
      >
        <UserPlus size={14} /> Manage members
      </Button>
      {authorityUncertain && message ? (
        <Notice tone={message.tone}>{message.text}</Notice>
      ) : null}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Members · {workspace.name}</DialogTitle>
            <DialogDescription>
              Invite an existing GrafY user by verified email. They choose
              whether to join.
            </DialogDescription>
          </DialogHeader>
          <DialogBody className="grafy-dialog-stack">
            <form
              className="grafy-member-form"
              onSubmit={(event) => void resolveCandidate(event)}
            >
              <label htmlFor="workspace-invite-email">
                Verified email
                <input
                  ref={emailInput}
                  id="workspace-invite-email"
                  type="email"
                  required
                  value={email}
                  aria-invalid={fieldError ? true : undefined}
                  aria-describedby={
                    fieldError ? "workspace-invite-email-error" : undefined
                  }
                  onChange={(event) => {
                    setEmail(event.target.value);
                    setCandidate(null);
                    setFieldError(null);
                  }}
                  placeholder="person@example.com"
                />
                {fieldError ? (
                  <Notice id="workspace-invite-email-error" tone="danger">
                    {fieldError}
                  </Notice>
                ) : null}
              </label>
              <label htmlFor="workspace-invite-role">
                Requested role
                <select
                  id="workspace-invite-role"
                  value={role}
                  onChange={(event) => {
                    setRole(event.target.value as WorkspaceRole);
                    setCandidate(null);
                  }}
                >
                  {roles.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
                <span className="grafy-member-empty">
                  {roleDescriptions[role]}
                </span>
              </label>
              <Button
                variant="primary"
                size="lg"
                type="submit"
                disabled={busyKey !== null}
              >
                Find person
              </Button>
            </form>

            {candidate ? (
              <section
                className="grafy-invitation-confirm"
                aria-label="Confirm invitation"
              >
                <strong>
                  {candidate.recipient.display_name ??
                    candidate.recipient.email}
                </strong>
                <span>{candidate.recipient.email}</span>
                <p>
                  Invite as <strong>{role}</strong>. The invitation expires in
                  seven days and grants no access until accepted.
                </p>
                {role === "owner" ? (
                  <Notice tone="warning">
                    Owners can manage members and all workspace settings.
                  </Notice>
                ) : null}
                <div>
                  <Button
                    variant="secondary"
                    size="lg"
                    onClick={() => setCandidate(null)}
                  >
                    Back
                  </Button>
                  <Button
                    variant="primary"
                    size="lg"
                    disabled={busyKey !== null}
                    onClick={() => void sendInvitation()}
                  >
                    Send invitation
                  </Button>
                </div>
              </section>
            ) : null}

            {message ? (
              <Notice tone={message.tone}>{message.text}</Notice>
            ) : null}
            {invitationsError ? (
              <Notice tone="danger">
                Pending invitations could not be loaded.
              </Notice>
            ) : null}
            {invitations?.length ? (
              <section>
                <h3>Pending invitations</h3>
                <div className="grafy-member-list">
                  {invitations.map((invitation) => (
                    <div className="grafy-member-row" key={invitation.id}>
                      <div>
                        <strong>
                          {invitation.recipient.display_name ??
                            invitation.recipient.email}
                        </strong>
                        <span>
                          {invitation.recipient.email} · {invitation.role} ·
                          expires{" "}
                          {new Date(invitation.expires_at).toLocaleDateString()}
                        </span>
                      </div>
                      <Button
                        type="button"
                        variant="danger"
                        size="xs"
                        className="grafy-member-row__remove"
                        disabled={busyKey === invitation.id}
                        onClick={() => void cancelInvitation(invitation.id)}
                      >
                        Cancel invitation
                      </Button>
                    </div>
                  ))}
                </div>
              </section>
            ) : null}

            {membersError ? (
              <Notice tone="danger">Members could not be loaded.</Notice>
            ) : null}
            {!members ? (
              <p className="grafy-member-empty">Loading members…</p>
            ) : members.length === 0 ? (
              <p className="grafy-member-empty">No members returned.</p>
            ) : (
              <div className="grafy-member-list">
                {members.map((member) => (
                  <div className="grafy-member-row" key={member.user.id}>
                    <div>
                      <strong>{memberName(member)}</strong>
                      <span>{member.user.email ?? "No email available"}</span>
                    </div>
                    <select
                      aria-label={`Role for ${memberName(member)}`}
                      value={member.role}
                      disabled={busyKey === member.user.id}
                      onChange={(event) =>
                        setMemberAction({
                          kind: "role",
                          member,
                          role: event.target.value as WorkspaceRole,
                        })
                      }
                    >
                      {roles.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </select>
                    <Button
                      type="button"
                      variant="danger"
                      size="xs"
                      className="grafy-member-row__remove"
                      disabled={busyKey === member.user.id}
                      onClick={() =>
                        setMemberAction({ kind: "remove", member })
                      }
                    >
                      Remove
                    </Button>
                  </div>
                ))}
              </div>
            )}

            {memberAction ? (
              <section
                className="grafy-invitation-confirm"
                role="alertdialog"
                aria-label="Confirm member change"
              >
                <strong>
                  Confirm change for {memberName(memberAction.member)}
                </strong>
                <p>
                  {memberAction.kind === "remove"
                    ? "They will immediately lose workspace access and active collaboration sessions will close."
                    : `Change their role from ${memberAction.member.role} to ${memberAction.role}. ${roleDescriptions[memberAction.role]}`}
                </p>
                <div>
                  <Button
                    variant="secondary"
                    size="lg"
                    onClick={() => setMemberAction(null)}
                  >
                    Keep current access
                  </Button>
                  <Button
                    type="button"
                    variant="danger"
                    size="lg"
                    disabled={busyKey !== null}
                    onClick={() => void confirmMemberAction()}
                  >
                    Confirm change
                  </Button>
                </div>
              </section>
            ) : null}
          </DialogBody>
        </DialogContent>
      </Dialog>
    </>
  );
}
