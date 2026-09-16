/**
 * Policy for locally-originated graph commands while local authoring is
 * paused (a persistence operation or execution is in flight).
 */

export interface AuthoringCommandOptions {
  /**
   * Skip the room broadcast. Used when a remote command is replayed locally
   * so it is not sent back to the room.
   */
  syncRoom?: boolean;
}

/**
 * Whether a locally-originated command must be rejected because local
 * authoring is paused. A room replay is exempt because it is not new
 * authoring.
 */
export function shouldBlockAuthoringCommand(
  localAuthoringEnabled: boolean,
  options?: AuthoringCommandOptions,
): boolean {
  if (options?.syncRoom === false) return false;
  return !localAuthoringEnabled;
}