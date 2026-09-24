"use client";

import * as React from "react";

import type { CollaborativeHead } from "@/lib/api";

import {
  GraphRoomSession,
  type ActiveExecutionSummary,
  type GraphRoomAcceptedMeta,
  type GraphRoomFailure,
  type GraphRoomStatus,
  type GraphRoomTerminalReason,
  type PresenceParticipant,
  type PresenceUpdateSubmit,
  type RoomGraphCommand,
} from "./graph-room-session";
import type {
  ExecutionClearedMessage,
  GraphCommandAcceptedMessage,
  GraphCommandRejectedMessage,
  RoomReadyMessage,
} from "./protocol";

export interface GraphRoomSubmitResult {
  readonly receipt: Awaited<
    ReturnType<GraphRoomSession["submitCommand"]>
  >["receipt"];
  readonly accepted: Awaited<
    ReturnType<GraphRoomSession["submitCommand"]>
  >["accepted"];
  readonly head: CollaborativeHead;
}

export interface UseGraphRoomSessionResult {
  readonly status: GraphRoomStatus;
  readonly terminalReason: GraphRoomTerminalReason | null;
  readonly failure: GraphRoomFailure | null;
  readonly head: CollaborativeHead | null;
  readonly capabilities: readonly string[];
  readonly authorizationVersion: number | null;
  readonly canSubmitCommands: boolean;
  readonly canPublishPresence: boolean;
  readonly localSessionId: string | null;
  readonly participants: readonly PresenceParticipant[];
  readonly activeExecution: ActiveExecutionSummary | null;
  readonly submitCommand: (
    command: RoomGraphCommand,
  ) => Promise<GraphRoomSubmitResult>;
  /** Reconcile a full snapshot and return the effective room head. */
  readonly replaceHead: (head: CollaborativeHead) => CollaborativeHead;
  /** Reconcile a checkpoint only within the epoch of its submitted command. */
  readonly reconcileCheckpointHead: (
    head: CollaborativeHead,
    expectedRoomEpoch: string,
  ) => CollaborativeHead;
  readonly publishPresence: (
    update: Omit<PresenceUpdateSubmit, "presence_sequence">,
  ) => boolean;
  readonly retry: () => void;
}

interface UseGraphRoomSessionOptions {
  workspaceId: string;
  graphId: string | null;
  onReady?: (ready: RoomReadyMessage) => void;
  onRehydrate?: (head: CollaborativeHead) => void;
  onHeadRefreshRequired?: () => void;
  onCommandAccepted?: (
    message: GraphCommandAcceptedMessage,
    meta: GraphRoomAcceptedMeta,
  ) => void;
  onCommandRejected?: (message: GraphCommandRejectedMessage) => void;
  onActiveExecution?: (execution: ActiveExecutionSummary | null) => void;
  onExecutionCleared?: (message: ExecutionClearedMessage) => void;
  onTerminalClose?: (reason: GraphRoomTerminalReason) => void;
}

export function useGraphRoomSession({
  workspaceId,
  graphId,
  onReady,
  onRehydrate,
  onHeadRefreshRequired,
  onCommandAccepted,
  onCommandRejected,
  onActiveExecution,
  onExecutionCleared,
  onTerminalClose,
}: UseGraphRoomSessionOptions): UseGraphRoomSessionResult {
  const [stateGraphId, setStateGraphId] = React.useState<string | null>(null);
  const [status, setStatus] = React.useState<GraphRoomStatus>("idle");
  const [terminalReason, setTerminalReason] =
    React.useState<GraphRoomTerminalReason | null>(null);
  const [failure, setFailure] = React.useState<GraphRoomFailure | null>(null);
  const [head, setHead] = React.useState<CollaborativeHead | null>(null);
  const [capabilities, setCapabilities] = React.useState<readonly string[]>([]);
  const [authorizationVersion, setAuthorizationVersion] = React.useState<
    number | null
  >(null);
  const [participants, setParticipants] = React.useState<
    readonly PresenceParticipant[]
  >([]);
  const [activeExecution, setActiveExecution] =
    React.useState<ActiveExecutionSummary | null>(null);
  const [localSessionId, setLocalSessionId] = React.useState<string | null>(
    null,
  );
  const sessionRef = React.useRef<GraphRoomSession | null>(null);

  const onReadyRef = React.useRef(onReady);
  const onRehydrateRef = React.useRef(onRehydrate);
  const onHeadRefreshRequiredRef = React.useRef(onHeadRefreshRequired);
  const onCommandAcceptedRef = React.useRef(onCommandAccepted);
  const onCommandRejectedRef = React.useRef(onCommandRejected);
  const onActiveExecutionRef = React.useRef(onActiveExecution);
  const onExecutionClearedRef = React.useRef(onExecutionCleared);
  const onTerminalCloseRef = React.useRef(onTerminalClose);

  React.useEffect(() => {
    onReadyRef.current = onReady;
    onRehydrateRef.current = onRehydrate;
    onHeadRefreshRequiredRef.current = onHeadRefreshRequired;
    onCommandAcceptedRef.current = onCommandAccepted;
    onCommandRejectedRef.current = onCommandRejected;
    onActiveExecutionRef.current = onActiveExecution;
    onExecutionClearedRef.current = onExecutionCleared;
    onTerminalCloseRef.current = onTerminalClose;
  }, [
    onActiveExecution,
    onCommandAccepted,
    onCommandRejected,
    onExecutionCleared,
    onHeadRefreshRequired,
    onReady,
    onRehydrate,
    onTerminalClose,
  ]);

  React.useEffect(() => {
    if (!graphId) {
      sessionRef.current?.disconnect();
      sessionRef.current = null;
      return;
    }

    const session = new GraphRoomSession({
      workspaceId,
      graphId,
      onStatusChange: (nextStatus) => {
        setStateGraphId(graphId);
        setStatus(nextStatus);
        if (nextStatus === "connecting" || nextStatus === "reconnecting") {
          setTerminalReason(null);
        }
        if (nextStatus !== "connecting") return;
        setFailure(null);
        setHead(null);
        setCapabilities([]);
        setAuthorizationVersion(null);
        setParticipants([]);
        setActiveExecution(null);
        setLocalSessionId(null);
      },
      onReady: (ready) => {
        setHead(ready.head);
        setCapabilities(ready.capabilities.capabilities);
        setAuthorizationVersion(ready.capabilities.authorization_version);
        setTerminalReason(null);
        setFailure(null);
        setLocalSessionId(ready.graph_room_session_id);
        setParticipants(ready.participants);
        setActiveExecution(ready.active_execution);
        onReadyRef.current?.(ready);
      },
      onRehydrate: (nextHead) => {
        setHead(nextHead);
        onRehydrateRef.current?.(nextHead);
      },
      onHeadRefreshRequired: () => {
        onHeadRefreshRequiredRef.current?.();
      },
      onCommandAccepted: (message, meta) => {
        const nextHead = session.getHead();
        if (nextHead) setHead(nextHead);
        onCommandAcceptedRef.current?.(message, meta);
      },
      onCommandRejected: (message) => {
        const nextHead = session.getHead();
        if (nextHead) setHead(nextHead);
        onCommandRejectedRef.current?.(message);
      },
      onPresenceChange: setParticipants,
      onFailureChange: (nextFailure) => {
        setFailure(nextFailure);
        if (!nextFailure) return;
        setCapabilities([]);
        setAuthorizationVersion(null);
        setParticipants([]);
        setActiveExecution(null);
        setLocalSessionId(null);
      },
      onActiveExecution: (execution) => {
        setActiveExecution(execution);
        onActiveExecutionRef.current?.(execution);
      },
      onExecutionCleared: (message) => {
        onExecutionClearedRef.current?.(message);
      },
      onTerminalClose: (reason) => {
        setTerminalReason(reason);
        setCapabilities([]);
        setAuthorizationVersion(null);
        setParticipants([]);
        setActiveExecution(null);
        setLocalSessionId(null);
        onTerminalCloseRef.current?.(reason);
      },
    });
    sessionRef.current = session;
    session.connect();

    return () => {
      session.disconnect();
      if (sessionRef.current === session) {
        sessionRef.current = null;
      }
    };
  }, [workspaceId, graphId]);

  const stateIsCurrent = graphId !== null && stateGraphId === graphId;
  const currentStatus = stateIsCurrent ? status : "idle";
  const currentTerminalReason = stateIsCurrent ? terminalReason : null;
  const currentFailure = stateIsCurrent ? failure : null;
  const currentHead = stateIsCurrent ? head : null;
  const currentCapabilities = stateIsCurrent ? capabilities : [];
  const currentAuthorizationVersion = stateIsCurrent
    ? authorizationVersion
    : null;
  const currentLocalSessionId = stateIsCurrent ? localSessionId : null;
  const currentParticipants = stateIsCurrent ? participants : [];
  const currentActiveExecution = stateIsCurrent ? activeExecution : null;

  const submitCommand = React.useCallback(
    async (command: RoomGraphCommand): Promise<GraphRoomSubmitResult> => {
      if (!graphId) {
        throw new Error("Graph room is not connected.");
      }
      const session = sessionRef.current;
      if (!session) {
        throw new Error("Graph room is not connected.");
      }
      const result = await session.submitCommand(command);
      const nextHead = session.getHead();
      if (!nextHead) {
        throw new Error("Graph room head is unavailable after command submit.");
      }
      setHead(nextHead);
      return { ...result, head: nextHead };
    },
    [graphId],
  );

  const replaceHead = React.useCallback(
    (nextHead: CollaborativeHead) => {
      if (!graphId) {
        throw new Error("Graph room is not connected.");
      }
      const session = sessionRef.current;
      if (!session) {
        throw new Error("Graph room is not connected.");
      }
      session.replaceHead(nextHead);
      const effectiveHead = session.getHead();
      if (!effectiveHead) {
        throw new Error("Graph room head is unavailable after reconciliation.");
      }
      setHead(effectiveHead);
      return effectiveHead;
    },
    [graphId],
  );

  const reconcileCheckpointHead = React.useCallback(
    (checkpointHead: CollaborativeHead, expectedRoomEpoch: string) => {
      if (!graphId) {
        throw new Error("Graph room is not connected.");
      }
      const session = sessionRef.current;
      if (!session) {
        throw new Error("Graph room is not connected.");
      }
      const effectiveHead = session.reconcileCheckpointHead(
        checkpointHead,
        expectedRoomEpoch,
      );
      setHead(effectiveHead);
      return effectiveHead;
    },
    [graphId],
  );

  const publishPresence = React.useCallback(
    (update: Omit<PresenceUpdateSubmit, "presence_sequence">): boolean => {
      if (!graphId) return false;
      return sessionRef.current?.publishPresence(update) ?? false;
    },
    [graphId],
  );

  const retry = React.useCallback(() => {
    if (!graphId) return;
    sessionRef.current?.retry();
  }, [graphId]);

  return {
    status: currentStatus,
    terminalReason: currentTerminalReason,
    failure: currentFailure,
    head: currentHead,
    capabilities: currentCapabilities,
    authorizationVersion: currentAuthorizationVersion,
    canSubmitCommands:
      currentStatus === "ready" &&
      currentHead !== null &&
      currentCapabilities.includes("edit_graph") &&
      currentTerminalReason === null,
    canPublishPresence:
      currentStatus === "ready" &&
      currentCapabilities.includes("publish_presence") &&
      currentTerminalReason === null,
    localSessionId: currentLocalSessionId,
    participants: currentParticipants,
    activeExecution: currentActiveExecution,
    submitCommand,
    replaceHead,
    reconcileCheckpointHead,
    publishPresence,
    retry,
  };
}
