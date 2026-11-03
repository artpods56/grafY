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

// A component still importing the graph-named hook gets the Project room rather
// than a module that fails to resolve: the canvas mounts and the session reports
// itself idle until it is addressed by project id. Without this the whole
// Workbench module throws in the browser and no canvas appears at all.
/** @deprecated a room is held around a Project. */
export { useProjectRoomSession as useGraphRoomSession } from "./useProjectRoomSession";
/** @deprecated a room is held around a Project. */
export type { UseGraphRoomSessionResult } from "./useProjectRoomSession";
