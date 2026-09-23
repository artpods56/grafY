"use client";

import * as React from "react";
import { UserPlus } from "lucide-react";

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

function operationError(error: unknown): string {
  if (error instanceof MemberListRefreshError)
    return "Change saved, but member list refresh failed.";
  if (!(error instanceof ApiError))
    return "The member change could not be completed.";
  if (error.status === 403)
    return "Permission changed. This dialog was closed; the denied change was not retried.";
  if (error.status === 404)
    return "The requested person or workspace is no longer available.";
  if (error.status === 409)
    return "The member or invitation state changed elsewhere. Refresh and try again.";
  return `Member change failed (${error.status}).`;
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
  const [message, setMessage] = React.useState<string | null>(null);
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
      setMessage(
        "Invitation sent. Access will begin only after it is accepted.",
      );
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
      setMessage("Invitation cancelled.");
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
      <button
        type="button"
        className="grafy-workspace-button"
        disabled={authorityUncertain}
        onClick={() => setOpen(true)}
      >
        <UserPlus size={14} /> Manage members
      </button>
      {authorityUncertain && message ? (
        <p className="grafy-member-message" role="status">
          {message}
        </p>
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
          <DialogBody>
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
                  <span
                    id="workspace-invite-email-error"
                    className="grafy-member-message"
                    role="alert"
                  >
                    {fieldError}
                  </span>
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
              <button
                className="grafy-workspace-button grafy-workspace-button--primary"
                type="submit"
                disabled={busyKey !== null}
              >
                Find person
              </button>
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
                  <p className="grafy-member-message" role="status">
                    Owners can manage members and all workspace settings.
                  </p>
                ) : null}
                <div>
                  <button
                    type="button"
                    className="grafy-workspace-button"
                    onClick={() => setCandidate(null)}
                  >
                    Back
                  </button>
                  <button
                    type="button"
                    className="grafy-workspace-button grafy-workspace-button--primary"
                    disabled={busyKey !== null}
                    onClick={() => void sendInvitation()}
                  >
                    Send invitation
                  </button>
                </div>
              </section>
            ) : null}

            {message ? (
              <p className="grafy-member-message" role="status">
                {message}
              </p>
            ) : null}
            {invitationsError ? (
              <p className="grafy-member-message" role="status">
                Pending invitations could not be loaded.
              </p>
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
                      <button
                        type="button"
                        className="grafy-member-remove"
                        disabled={busyKey === invitation.id}
                        onClick={() => void cancelInvitation(invitation.id)}
                      >
                        Cancel invitation
                      </button>
                    </div>
                  ))}
                </div>
              </section>
            ) : null}

            {membersError ? (
              <p className="grafy-member-message" role="status">
                Members could not be loaded.
              </p>
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
                    <button
                      type="button"
                      className="grafy-member-remove"
                      disabled={busyKey === member.user.id}
                      onClick={() =>
                        setMemberAction({ kind: "remove", member })
                      }
                    >
                      Remove
                    </button>
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
                  <button
                    type="button"
                    className="grafy-workspace-button"
                    onClick={() => setMemberAction(null)}
                  >
                    Keep current access
                  </button>
                  <button
                    type="button"
                    className="grafy-member-remove"
                    disabled={busyKey !== null}
                    onClick={() => void confirmMemberAction()}
                  >
                    Confirm change
                  </button>
                </div>
              </section>
            ) : null}
          </DialogBody>
        </DialogContent>
      </Dialog>
    </>
  );
}
