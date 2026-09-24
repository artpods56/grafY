import { ApiError } from "@/lib/api/client";

export class MemberListRefreshError extends Error {
  readonly cause: unknown;

  constructor(cause: unknown) {
    super(
      "Member change was saved, but the member list could not be refreshed.",
    );
    this.name = "MemberListRefreshError";
    this.cause = cause;
  }
}

export async function executeMemberMutation(
  operation: () => Promise<unknown>,
  refreshMembers: () => Promise<unknown>,
  refreshWorkspaceCapabilities: () => Promise<unknown>,
): Promise<void> {
  try {
    await operation();
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) {
      try {
        await refreshWorkspaceCapabilities();
      } catch {
        // Preserve the denied mutation as the primary outcome while authority is uncertain.
      }
    }
    throw error;
  }

  try {
    await refreshMembers();
  } catch (error) {
    throw new MemberListRefreshError(error);
  }
}
