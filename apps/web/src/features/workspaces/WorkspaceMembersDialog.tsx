"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { UserPlus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Select } from "@/components/ui/select";
import { phoneTouch } from "@/components/ui/touch-target";
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
import { tokens } from "@/lib/stylex/tokens.stylex";
import {
  executeMemberMutation,
  MemberListRefreshError,
} from "./workspace-member-mutation";
import { useWorkspaceContext } from "./WorkspaceLayout";
import { workspaceSettingsStyles as settings } from "./workspace-settings.styles";

const MONO =
  "var(--font-geist-mono), ui-monospace, SFMono-Regular, Menlo, monospace";

const roles: readonly WorkspaceRole[] = ["viewer", "editor", "owner"];
const roleDescriptions: Record<WorkspaceRole, string> = {
  viewer: "Can view graphs, artifacts, history, and shared activity.",
  editor: "Can also create, edit, and run graphs.",
  owner: "Has full access, including member and workspace administration.",
};

type MemberAction =
  | { kind: "role"; member: WorkspaceMember; role: WorkspaceRole }
  | { kind: "remove"; member: WorkspaceMember };

const s = stylex.create({
  /**
   * `.grafy-member-form` is a flex row and gave its `flex: 1` to the `label` it
   * held. A `Field` root is a div, so the share of the row has to come from here.
   */
  formField: {
    flex: "1 1 0%",
  },
  form: {
    display: "flex",
    alignItems: {
      default: "end",
      "@media (max-width: 860px)": "stretch",
    },
    flexDirection: {
      default: "row",
      "@media (max-width: 860px)": "column",
    },
    gap: "8px",
  },
  formLabel: {
    display: "grid",
    flex: "1",
    gap: "5px",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
    fontWeight: 500,
  },
  formInput: {
    minHeight: {
      default: "36px",
      "@media (max-width: 620px)": "44px",
    },
    padding: "0 10px",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: {
      default: tokens.colorBorder,
      ":focus": tokens.colorAccentBorder,
    },
    borderRadius: tokens.radiusSm,
    outline: "0",
    backgroundColor: tokens.colorSurface,
    color: tokens.colorText,
    fontSize: tokens.fontSizeMd,
  },
  memberEmpty: {
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeMd,
  },
  memberList: {
    display: "grid",
    gap: "1px",
  },
  memberRow: {
    display: "grid",
    gridTemplateColumns: {
      default: "minmax(0, 1fr) 100px auto",
      "@media (max-width: 860px)": "minmax(0, 1fr) auto",
    },
    alignItems: "center",
    gap: {
      default: "9px",
      "@media (max-width: 620px)": "12px",
    },
    padding: "11px 0",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
  },
  memberRowMain: {
    display: "grid",
    gap: "2px",
    minWidth: 0,
  },
  memberRowName: {
    overflow: "hidden",
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeMd,
    fontWeight: 500,
    textOverflow: "ellipsis",
  },
  memberRowDetail: {
    overflow: "hidden",
    color: tokens.colorMuted,
    fontFamily: MONO,
    fontSize: tokens.fontSizeXs,
    textOverflow: "ellipsis",
  },
  /** The role select's grid placement from the 860px breakpoint down. */
  memberRowSelect: {
    gridColumn: {
      default: "auto",
      "@media (max-width: 860px)": "2",
    },
    gridRow: {
      default: "auto",
      "@media (max-width: 860px)": "1",
    },
  },
  /** The remove button's grid placement from the 860px breakpoint down. */
  memberRowRemove: {
    gridColumn: {
      default: "auto",
      "@media (max-width: 860px)": "1 / -1",
    },
    justifySelf: {
      default: "unset",
      "@media (max-width: 860px)": "start",
    },
  },
  invitationConfirm: {
    display: "grid",
    gap: "8px",
    margin: "12px 0 18px",
    padding: "14px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorBg,
    fontSize: tokens.fontSizeMd,
  },
  invitationConfirmEmail: {
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
  },
  invitationActions: {
    display: "flex",
    justifyContent: "flex-end",
    gap: "8px",
  },
});

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
        size="md"
        xstyle={[phoneTouch.on, settings.action]}
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
              {...stylex.props(s.form)}
              onSubmit={(event) => void resolveCandidate(event)}
            >
              <label
                htmlFor="workspace-invite-email"
                {...stylex.props(s.formLabel)}
              >
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
                  {...stylex.props(s.formInput)}
                />
                {fieldError ? (
                  <Notice id="workspace-invite-email-error" tone="danger">
                    {fieldError}
                  </Notice>
                ) : null}
              </label>
              <Field
                label="Requested role"
                description={
                  <span {...stylex.props(s.memberEmpty)}>
                    {roleDescriptions[role]}
                  </span>
                }
                xstyle={s.formField}
              >
                <Select
                  value={role}
                  onChange={(event) => {
                    setRole(event.target.value as WorkspaceRole);
                    setCandidate(null);
                  }}
                  xstyle={phoneTouch.on}
                >
                  {roles.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </Select>
              </Field>
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
                {...stylex.props(s.invitationConfirm)}
                aria-label="Confirm invitation"
              >
                <strong>
                  {candidate.recipient.display_name ??
                    candidate.recipient.email}
                </strong>
                <span {...stylex.props(s.invitationConfirmEmail)}>
                  {candidate.recipient.email}
                </span>
                <p>
                  Invite as <strong>{role}</strong>. The invitation expires in
                  seven days and grants no access until accepted.
                </p>
                {role === "owner" ? (
                  <Notice tone="warning">
                    Owners can manage members and all workspace settings.
                  </Notice>
                ) : null}
                <div {...stylex.props(s.invitationActions)}>
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
                <div {...stylex.props(s.memberList)}>
                  {invitations.map((invitation) => (
                    <div {...stylex.props(s.memberRow)} key={invitation.id}>
                      <div {...stylex.props(s.memberRowMain)}>
                        <strong {...stylex.props(s.memberRowName)}>
                          {invitation.recipient.display_name ??
                            invitation.recipient.email}
                        </strong>
                        <span {...stylex.props(s.memberRowDetail)}>
                          {invitation.recipient.email} · {invitation.role} ·
                          expires{" "}
                          {new Date(invitation.expires_at).toLocaleDateString()}
                        </span>
                      </div>
                      <Button
                        type="button"
                        variant="danger"
                        size="xs"
                        xstyle={s.memberRowRemove}
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
              <p {...stylex.props(s.memberEmpty)}>Loading members…</p>
            ) : members.length === 0 ? (
              <p {...stylex.props(s.memberEmpty)}>No members returned.</p>
            ) : (
              <div {...stylex.props(s.memberList)}>
                {members.map((member) => (
                  <div {...stylex.props(s.memberRow)} key={member.user.id}>
                    <div {...stylex.props(s.memberRowMain)}>
                      <strong {...stylex.props(s.memberRowName)}>
                        {memberName(member)}
                      </strong>
                      <span {...stylex.props(s.memberRowDetail)}>
                        {member.user.email ?? "No email available"}
                      </span>
                    </div>
                    <Select
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
                      xstyle={[phoneTouch.on, s.memberRowSelect]}
                    >
                      {roles.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </Select>
                    <Button
                      type="button"
                      variant="danger"
                      size="xs"
                      xstyle={s.memberRowRemove}
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
                {...stylex.props(s.invitationConfirm)}
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
                <div {...stylex.props(s.invitationActions)}>
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
