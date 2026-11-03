export {
  PRESENCE_CLIENT_MIN_INTERVAL_MS,
  ProjectRoomCommandError,
  /** @deprecated the room belongs to a Project, not to a Graph. */
  ProjectRoomCommandError as GraphRoomCommandError,
  ProjectRoomSession,
  ROOM_COMMAND_QUEUE_CAP,
  shouldReplaceCollaborativeHead,
  type ActiveRunSummary,
  type PresenceParticipant,
  type PresenceUpdateSubmit,
  type ProjectRoomAcceptedMeta,
  type ProjectRoomCommandResult,
  type ProjectRoomFailure,
  type ProjectRoomRecoveryReason,
  type ProjectRoomSessionListeners,
  type ProjectRoomSessionOptions,
  type ProjectRoomStatus,
  type ProjectRoomTerminalReason,
  type RoomInstanceState,
  type RoomInstanceKey,
} from "./graph-room-session";
export { projectRoomWebSocketUrl } from "./project-room-url";
export {
  applyRoomCommandsToHead,
  commandBatchGraphId,
  defaultGraphId,
  savedGraphFromProjectHead,
  toLocalGraphCommand,
  toRoomGraphCommand,
  toRoomRenameGraphCommand,
  toRoomRenameProjectCommand,
  toRoomReplaceDocumentCommand,
  type RoomGraphBodyCommand,
  /** @deprecated a command is addressed to a Project, and maybe one Graph inside it. */
  type RoomGraphCommand,
  type RoomProjectCommand,
} from "./room-command-bridge";
export { PresenceOverlay } from "./PresenceOverlay";
export { RemoteSelectionRing } from "./RemoteSelectionRing";
export {
  remoteSelectedNodeIds,
  remoteSelectionColor,
} from "./remote-selection";
export {
  useProjectRoomSession,
  type ProjectRoomSubmitResult,
  type UseProjectRoomSessionResult,
} from "./useProjectRoomSession";
export { useRemoteDragPreviews } from "./useRemoteDragPreviews";
export {
  graphReadiness,
  type GraphReadiness,
  type GraphReadinessState,
} from "./graph-readiness";
export { instanceKeyText } from "./protocol";
export type {
  InstancesChangedMessage,
  PresenceActivityKind,
  PresencePoint,
  ProjectCommandAcceptedMessage,
  ProjectCommandReceiptMessage,
  ProjectCommandRejectedMessage,
  ProjectCommandSubmitMessage,
  RoomReadyMessage,
  RoomRehydrateMessage,
  RunFinishedMessage,
  RunStartedMessage,
  TransientNodePosition,
} from "./protocol";
